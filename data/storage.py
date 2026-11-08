"""
MongoDB Atlas storage layer and deduplication interface for NMMS Bot.
Fail-Closed in Production:
- If MONGO_URI is missing or Atlas connection fails (serverSelectionTimeoutMS=10000 + ping),
  logs clear error and exits with non-zero code BEFORE scraping or posting.
- In-memory storage is allowed ONLY when NMMS_TEST_MODE=1 or DRY_RUN=1.
- In DRY_RUN=1, no writes to MongoDB are performed (reads allowed if MONGO_URI is set).
"""

import os
import sys
import re
import hashlib
import logging
from datetime import datetime, date, timedelta, timezone
from typing import Dict, Any, Optional, List
from zoneinfo import ZoneInfo

try:
    from pymongo import MongoClient, ASCENDING
    from pymongo.errors import DuplicateKeyError
except ImportError:
    MongoClient = None
    DuplicateKeyError = Exception

logger = logging.getLogger(__name__)

# Primary IST timezone
try:
    IST = ZoneInfo("Asia/Kolkata")
except Exception:
    IST = timezone(timedelta(hours=5, minutes=30))

DB_NAME = "nmms_bot"
COLLECTION_NAME = "notices"

_client: Optional[Any] = None
_db: Optional[Any] = None
_collection: Optional[Any] = None
_indexes_created = False

# In-memory storage fallback ONLY for NMMS_TEST_MODE=1 or DRY_RUN=1
_memory_store: Dict[str, Dict[str, Any]] = {}

def is_dry_run() -> bool:
    """Returns True if DRY_RUN mode is active."""
    return os.getenv("DRY_RUN", "").strip() == "1"

def is_test_mode() -> bool:
    """Returns True if test mode is active."""
    return os.getenv("NMMS_TEST_MODE", "").strip() == "1"

def is_test_or_dry_run() -> bool:
    """Returns True if running under test or dry_run."""
    return is_test_mode() or is_dry_run()

def get_ist_now() -> datetime:
    """Returns current datetime in IST."""
    return datetime.now(IST)

def get_ist_today() -> date:
    """Returns today's date in IST."""
    return datetime.now(IST).date()

def init_mongo_storage():
    """
    Initializes and verifies MongoDB connection.
    In PRODUCTION (neither DRY_RUN nor TEST_MODE):
    Exits with sys.exit(1) if MONGO_URI is missing or ping fails!
    """
    global _client, _db, _collection, _indexes_created

    mongo_uri = os.getenv("MONGO_URI", "").strip()

    if not mongo_uri:
        if not is_test_or_dry_run():
            logger.error("[STORAGE_FAIL_CLOSED] MONGO_URI environment variable is missing! Production runs require MongoDB Atlas. Exiting.")
            sys.exit(1)
        else:
            logger.info("[STORAGE] Running in TEST_MODE / DRY_RUN without MONGO_URI. Using isolated in-memory store.")
            return None

    if MongoClient is None:
        if not is_test_or_dry_run():
            logger.error("[STORAGE_FAIL_CLOSED] pymongo is not installed in production environment. Exiting.")
            sys.exit(1)
        return None

    try:
        # serverSelectionTimeoutMS=10000 per user specification
        _client = MongoClient(mongo_uri, serverSelectionTimeoutMS=10000)
        # Ping check at startup
        _client.admin.command("ping")
        _db = _client[DB_NAME]
        _collection = _db[COLLECTION_NAME]

        if not _indexes_created:
            try:
                _collection.create_index([("content_hash", ASCENDING)], unique=True)
                _collection.create_index([("key", ASCENDING)], unique=True, sparse=True)
                _collection.create_index([("state", ASCENDING), ("created_at", ASCENDING)])
                _indexes_created = True
            except Exception as ie:
                logger.warning(f"[STORAGE] Notice index creation warning: {ie}")

        logger.info("[STORAGE] Successfully connected and pinged MongoDB Atlas (DB: nmms_bot).")
        return _collection
    except Exception as e:
        logger.error(f"[STORAGE_FAIL_CLOSED] MongoDB Atlas connection/ping failed: {e}")
        if not is_test_or_dry_run():
            sys.exit(1)
        return None

def _get_collection():
    """Returns cached collection or calls init_mongo_storage."""
    if _collection is not None:
        return _collection
    return init_mongo_storage()

# Date parsing & normalization utilities
HINDI_NUMERALS = {'०':'0', '१':'1', '२':'2', '३':'3', '४':'4', '५':'5', '६':'6', '७':'7', '८':'8', '९':'9'}

MONTH_MAP = {
    'january': 1, 'jan': 1, 'जनवरी': 1,
    'february': 2, 'feb': 2, 'फ़रवरी': 2, 'फरवरी': 2,
    'march': 3, 'mar': 3, 'मार्च': 3,
    'april': 4, 'apr': 4, 'अप्रैल': 4,
    'may': 5, 'मई': 5,
    'june': 6, 'jun': 6, 'जून': 6,
    'july': 7, 'jul': 7, 'जुलाई': 7,
    'august': 8, 'aug': 8, 'अगस्त': 8,
    'september': 9, 'sep': 9, 'sept': 9, 'सितंबर': 9, 'सितम्बर': 9,
    'october': 10, 'oct': 10, 'अक्टूबर': 10, 'अक्तूबर': 10,
    'november': 11, 'nov': 11, 'नवंबर': 11, 'नवम्बर': 11,
    'december': 12, 'dec': 12, 'दिसंबर': 12, 'दिसम्बर': 12
}

def to_english_numerals(text: str) -> str:
    if not text:
        return ""
    res = text
    for h_num, e_num in HINDI_NUMERALS.items():
        res = res.replace(h_num, e_num)
    return res

def parse_date_to_ist(date_str: str, fallback_year: Optional[int] = None) -> Optional[date]:
    """
    Parses date string in English or Hindi into a standard date object.
    Supports formats like '15 November 2026', '15 नवम्बर 2026', '१५ नवंबर २०२६', 'DD-MM-YYYY'.
    CRITICAL RULE:
    - Dates must be parsed with their full year as written in evidence text.
    - NEVER assume current year when year is missing: if absent, take only from fallback_year (article pub date), else return None.
    """
    if not date_str:
        return None

    if isinstance(date_str, date):
        return date_str

    clean = to_english_numerals(str(date_str).strip().lower())

    # 1. Day Month Year (e.g., 15 November 2026 / 15-Nov-2026)
    m1 = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+([a-zA-Z\u0900-\u097f]+)\s*,?\s*(\d{4})', clean)
    if m1:
        day = int(m1.group(1))
        month_str = m1.group(2)
        year = int(m1.group(3))
        month = MONTH_MAP.get(month_str)
        if month and 1 <= day <= 31:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # 2. Month Day Year (e.g., November 15, 2026)
    m1b = re.search(r'([a-zA-Z\u0900-\u097f]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})', clean)
    if m1b:
        month_str = m1b.group(1)
        day = int(m1b.group(2))
        year = int(m1b.group(3))
        month = MONTH_MAP.get(month_str)
        if month and 1 <= day <= 31:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # 3. Numeric DD-MM-YYYY or DD/MM/YYYY
    m2 = re.search(r'(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})', clean)
    if m2:
        day = int(m2.group(1))
        month = int(m2.group(2))
        year = int(m2.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # 4. Numeric YYYY-MM-DD
    m3 = re.search(r'(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})', clean)
    if m3:
        year = int(m3.group(1))
        month = int(m3.group(2))
        day = int(m3.group(3))
        if 1 <= month <= 12 and 1 <= day <= 31:
            try:
                return date(year, month, day)
            except ValueError:
                pass

    # 5. Missing Year: Only parse if fallback_year is explicitly provided (e.g. from article pub date)
    if fallback_year and isinstance(fallback_year, int) and 2000 <= fallback_year <= 2100:
        m_noyear1 = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+([a-zA-Z\u0900-\u097f]+)', clean)
        if m_noyear1:
            day = int(m_noyear1.group(1))
            month_str = m_noyear1.group(2)
            month = MONTH_MAP.get(month_str)
            if month and 1 <= day <= 31:
                try:
                    return date(fallback_year, month, day)
                except ValueError:
                    pass

        m_noyear2 = re.search(r'([a-zA-Z\u0900-\u097f]+)\s+(\d{1,2})(?:st|nd|rd|th)?', clean)
        if m_noyear2:
            month_str = m_noyear2.group(1)
            day = int(m_noyear2.group(2))
            month = MONTH_MAP.get(month_str)
            if month and 1 <= day <= 31:
                try:
                    return date(fallback_year, month, day)
                except ValueError:
                    pass

    return None

def normalize_date_str(date_input: Any, fallback_year: Optional[int] = None) -> str:
    """Returns standardized 'YYYY-MM-DD' or empty string."""
    if isinstance(date_input, date):
        return date_input.strftime("%Y-%m-%d")
    parsed = parse_date_to_ist(date_input, fallback_year=fallback_year)
    if parsed:
        return parsed.strftime("%Y-%m-%d")
    return ""

def is_last_date_expired(last_date_input: Any, fallback_year: Optional[int] = None) -> bool:
    """Returns True if last_date is found and strictly before today (IST)."""
    if isinstance(last_date_input, date):
        return last_date_input < get_ist_today()
    parsed = parse_date_to_ist(last_date_input, fallback_year=fallback_year)
    if not parsed:
        return False
    today = get_ist_today()
    return parsed < today

def compute_content_hash(state: str, title: str, url: str) -> str:
    """SHA-256 hash of raw candidate state, normalized title, and url."""
    norm_title = re.sub(r"\s+", " ", (title or "").strip().lower())
    norm_url = (url or "").strip().lower().rstrip("/")
    norm_state = (state or "").strip().lower()
    raw = f"{norm_state}::{norm_title}::{norm_url}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def compute_event_key(state: str, event_type: str, normalized_date: str) -> str:
    """
    key = sha256(state + event_type + normalized event_date/last_date).
    For CENTRAL events, always uses 'CENTRAL' so national notices are never repeated.
    """
    s = "CENTRAL" if (state or "").strip().upper() == "CENTRAL" else (state or "").strip().lower()
    e = (event_type or "").strip().upper()
    d = (normalized_date or "").strip()
    raw = f"{s}::{e}::{d}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

# ----------------- MongoDB Interface Implementation ----------------- #

def find_recent(state: str, max_entries: int = 15, max_days: int = 30) -> List[Dict[str, Any]]:
    """Fetches last 30 days or max 15 POSTED notices for this state to feed AI Gatekeeper."""
    col = _get_collection()
    state_clean = (state or "").strip().lower()
    cutoff_dt = datetime.now(timezone.utc) - timedelta(days=max_days)

    results = []
    if col is not None:
        try:
            query = {
                "status": "POSTED",
                "created_at": {"$gte": cutoff_dt}
            }
            if "central" in state_clean or "nsp" in state_clean:
                query["$or"] = [
                    {"state": {"$regex": "central", "$options": "i"}},
                    {"state": {"$regex": "nsp", "$options": "i"}}
                ]
            else:
                query["state"] = {"$regex": f"^{re.escape(state)}$", "$options": "i"}

            cursor = col.find(query).sort("created_at", -1).limit(max_entries)
            for doc in cursor:
                results.append({
                    "title": doc.get("title", ""),
                    "event_type": doc.get("event_type", ""),
                    "dates": doc.get("dates", []) or [{"label": "Last Date", "value": doc.get("last_date", "")}],
                    "summary_hi": doc.get("summary_hi", ""),
                    "summary_en": doc.get("summary_en", ""),
                    "last_date": doc.get("last_date", ""),
                    "event_date": doc.get("event_date", ""),
                    "created_at": doc.get("created_at")
                })
            return results
        except Exception as e:
            logger.error(f"[STORAGE_ERROR] find_recent failed: {e}")
            if not is_test_or_dry_run():
                return []

    if is_test_or_dry_run():
        for doc in _memory_store.values():
            if doc.get("status") != "POSTED":
                continue
            d_state = (doc.get("state") or "").strip().lower()
            match = ("central" in state_clean and "central" in d_state) or (d_state == state_clean)
            if match:
                results.append({
                    "title": doc.get("title", ""),
                    "event_type": doc.get("event_type", ""),
                    "dates": doc.get("dates", []) or [{"label": "Last Date", "value": doc.get("last_date", "")}],
                    "summary_hi": doc.get("summary_hi", ""),
                    "summary_en": doc.get("summary_en", ""),
                    "last_date": doc.get("last_date", ""),
                    "event_date": doc.get("event_date", "")
                })
    return results[:max_entries]

def is_extension_valid(state: str, new_date_str: str) -> bool:
    """Checks if an EXTENSION event announces a date later than previously recorded last_date."""
    new_dt = parse_date_to_ist(new_date_str)
    if not new_dt:
        return True

    recents = find_recent(state, max_entries=5, max_days=60)
    for r in recents:
        old_str = r.get("last_date", "")
        old_dt = parse_date_to_ist(old_str)
        if old_dt:
            if new_dt <= old_dt:
                return False
    return True

def try_insert(candidate_data: dict) -> bool:
    """
    Attempts to insert candidate notice with status PENDING.
    In DRY_RUN: Does NOT write to MongoDB (checks duplicates and returns True/False).
    In Production: Fails closed on any MongoDB exception (returns False).
    """
    content_hash = candidate_data.get("content_hash")
    key = candidate_data.get("key")
    state = candidate_data.get("state", "")
    now_utc = datetime.now(timezone.utc)
    one_hour_ago = now_utc - timedelta(hours=1)

    if is_dry_run():
        # In DRY_RUN, do not write to MongoDB
        lookup_id = key or content_hash
        if lookup_id in _memory_store:
            return False
        _memory_store[lookup_id] = {**candidate_data, "status": "PENDING", "created_at": now_utc}
        return True

    col = _get_collection()

    doc = {
        "key": key,
        "content_hash": content_hash,
        "state": state,
        "event_type": candidate_data.get("event_type", ""),
        "title": candidate_data.get("title", ""),
        "summary_hi": candidate_data.get("summary_hi", ""),
        "summary_en": candidate_data.get("summary_en", ""),
        "last_date": candidate_data.get("last_date", ""),
        "event_date": candidate_data.get("event_date", ""),
        "dates": candidate_data.get("dates", []),
        "source_url": candidate_data.get("source_url", ""),
        "official_url": candidate_data.get("official_url", ""),
        "status": "PENDING",
        "telegram_message_id": None,
        "created_at": now_utc,
        "posted_at": None,
        "reminder_3d_sent": False,
        "reminder_1d_sent": False
    }

    if col is not None:
        try:
            col.insert_one(doc)
            return True
        except DuplicateKeyError:
            query = {"$or": []}
            if content_hash:
                query["$or"].append({"content_hash": content_hash})
            if key:
                query["$or"].append({"key": key})

            existing = col.find_one(query) if query["$or"] else None
            if not existing:
                return False

            status = existing.get("status")
            created_at = existing.get("created_at")

            if status in ["POSTED", "REJECTED"]:
                return False

            if status == "FAILED" or (status == "PENDING" and created_at and created_at < one_hour_ago):
                col.update_one(
                    {"_id": existing["_id"]},
                    {"$set": {
                        "status": "PENDING",
                        "created_at": now_utc,
                        "key": key or existing.get("key"),
                        "last_error": None
                    }}
                )
                return True

            return False
        except Exception as e:
            logger.error(f"[STORAGE_ERROR] try_insert MongoDB error: {e}")
            # Fail closed mid-run
            return False

    if is_test_mode():
        lookup_id = key or content_hash
        if lookup_id in _memory_store:
            existing = _memory_store[lookup_id]
            status = existing.get("status")
            c_at = existing.get("created_at", now_utc)
            if status in ["POSTED", "REJECTED"]:
                return False
            if status == "FAILED" or (status == "PENDING" and c_at < one_hour_ago):
                existing["status"] = "PENDING"
                existing["created_at"] = now_utc
                return True
            return False

        _memory_store[lookup_id] = doc
        if content_hash:
            _memory_store[content_hash] = doc
        return True

    return False

def mark_posted(key: str, content_hash: str, telegram_message_id: int):
    """Marks notice as POSTED. In DRY_RUN mode, skips DB write."""
    if is_dry_run():
        return

    now_utc = datetime.now(timezone.utc)
    col = _get_collection()

    if col is not None:
        try:
            filter_q = {"$or": []}
            if content_hash:
                filter_q["$or"].append({"content_hash": content_hash})
            if key:
                filter_q["$or"].append({"key": key})

            if filter_q["$or"]:
                col.update_one(
                    filter_q,
                    {"$set": {
                        "status": "POSTED",
                        "telegram_message_id": telegram_message_id,
                        "posted_at": now_utc
                    }}
                )
        except Exception as e:
            logger.error(f"[STORAGE_ERROR] Failed to mark POSTED in MongoDB: {e}")

    if is_test_mode():
        for k in [key, content_hash]:
            if k and k in _memory_store:
                _memory_store[k]["status"] = "POSTED"
                _memory_store[k]["telegram_message_id"] = telegram_message_id
                _memory_store[k]["posted_at"] = now_utc

def mark_failed(key: str, content_hash: str, error_msg: str = ""):
    """Marks notice as FAILED. In DRY_RUN mode, skips DB write."""
    if is_dry_run():
        return

    col = _get_collection()
    if col is not None:
        try:
            filter_q = {"$or": []}
            if content_hash:
                filter_q["$or"].append({"content_hash": content_hash})
            if key:
                filter_q["$or"].append({"key": key})

            if filter_q["$or"]:
                col.update_one(
                    filter_q,
                    {"$set": {
                        "status": "FAILED",
                        "last_error": str(error_msg)[:300]
                    }}
                )
        except Exception as e:
            logger.error(f"[STORAGE_ERROR] Failed to mark FAILED in MongoDB: {e}")

    if is_test_mode():
        for k in [key, content_hash]:
            if k and k in _memory_store:
                _memory_store[k]["status"] = "FAILED"
                _memory_store[k]["last_error"] = str(error_msg)[:300]

def mark_rejected(content_hash: str, state: str, title: str, reason: str, event_type: str = ""):
    """Saves rejected notices' content_hash in MongoDB with status REJECTED. Skips in DRY_RUN."""
    if not content_hash or is_dry_run():
        return

    now_utc = datetime.now(timezone.utc)
    col = _get_collection()

    doc = {
        "content_hash": content_hash,
        "key": None,
        "state": state,
        "title": title,
        "event_type": event_type,
        "status": "REJECTED",
        "rejection_reason": reason,
        "created_at": now_utc
    }

    if col is not None:
        try:
            col.update_one(
                {"content_hash": content_hash},
                {"$setOnInsert": doc},
                upsert=True
            )
        except Exception as e:
            logger.error(f"[STORAGE_ERROR] Failed to record REJECTED notice in MongoDB: {e}")

    if is_test_mode():
        _memory_store[content_hash] = doc

def is_content_hash_seen(content_hash: str) -> bool:
    """Checks whether this content_hash is already POSTED or REJECTED."""
    if not content_hash:
        return False

    col = _get_collection()
    if col is not None:
        try:
            doc = col.find_one({"content_hash": content_hash})
            if doc:
                status = doc.get("status")
                if status in ["POSTED", "REJECTED"]:
                    return True
                if status == "PENDING":
                    c_at = doc.get("created_at")
                    if c_at and (datetime.now(timezone.utc) - c_at) < timedelta(hours=1):
                        return True
            return False
        except Exception as e:
            logger.error(f"[STORAGE_ERROR] is_content_hash_seen failed: {e}")
            if not is_test_or_dry_run():
                # Fail-closed: assume seen to prevent duplicates on DB error
                return True

    if is_test_or_dry_run():
        if content_hash in _memory_store:
            doc = _memory_store[content_hash]
            if doc.get("status") in ["POSTED", "REJECTED"]:
                return True
    return False

def get_active_notices_for_reminders() -> List[Dict[str, Any]]:
    """Returns active POSTED notices that have a last_date for reminder checks."""
    col = _get_collection()
    results = []

    if col is not None:
        try:
            cursor = col.find({
                "status": "POSTED",
                "last_date": {"$exists": True, "$ne": ""}
            })
            for doc in cursor:
                results.append(doc)
            return results
        except Exception as e:
            logger.error(f"[STORAGE_ERROR] get_active_notices_for_reminders error: {e}")

    if is_test_or_dry_run():
        for doc in _memory_store.values():
            if doc.get("status") == "POSTED" and doc.get("last_date"):
                results.append(doc)
    return results

def mark_reminder_sent(content_hash: str, reminder_field: str):
    """Sets reminder_3d_sent or reminder_1d_sent to True. Skips in DRY_RUN."""
    if is_dry_run():
        return

    col = _get_collection()
    if col is not None:
        try:
            col.update_one(
                {"content_hash": content_hash},
                {"$set": {reminder_field: True}}
            )
        except Exception as e:
            logger.warning(f"[STORAGE_ERROR] mark_reminder_sent error: {e}")

    if is_test_mode() and content_hash in _memory_store:
        _memory_store[content_hash][reminder_field] = True
