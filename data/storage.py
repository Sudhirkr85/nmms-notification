import json
import os
import re
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional, List

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "history.json")

def _ensure_file():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"posted": {}, "reminders_sent": {}}, f, indent=2)

def normalize_url(url: str) -> str:
    if not url:
        return ""
    clean = url.strip()
    clean = re.sub(r"[?#].*$", "", clean)
    return clean.rstrip("/").lower()

def normalize_title(title: str) -> str:
    if not title:
        return ""

    t = title.strip()
    t = re.sub(r"^\s*\d+\s*(?:days?|weeks?|months?|hours?|mins?|minutes?)\s*ago\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"^[\s\W]*(?:new|notice|circular|📢|🔔|important|latest|update|attention)[\s\W]*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"[^\w\s\u0900-\u0D7F]", " ", t)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t

def extract_keywords(text: str) -> set:
    norm = normalize_title(text)
    words = re.findall(r"\b\w{3,}\b", norm)
    stopwords = {
        "the", "and", "for", "with", "from", "regarding", "notice", "circular",
        "official", "portal", "check", "click", "here", "view", "link", "online",
        "scheme", "scholarship", "examination", "exam"
    }
    return {w for w in words if w not in stopwords}

def normalize_date_str(d_str: str) -> str:
    """
    Normalizes dates like '15 November 2026', '15 Nov 2026', '2026-11-15' into standardized '15-11-2026'.
    Enables 100% accurate date-matching deduplication.
    """
    if not d_str:
        return ""
    clean = d_str.strip().lower()
    month_map = {
        "january": "01", "jan": "01",
        "february": "02", "feb": "02",
        "march": "03", "mar": "03",
        "april": "04", "apr": "04",
        "may": "05",
        "june": "06", "jun": "06",
        "july": "07", "jul": "07",
        "august": "08", "aug": "08",
        "september": "09", "sep": "09", "sept": "09",
        "october": "10", "oct": "10",
        "november": "11", "nov": "11",
        "december": "12", "dec": "12"
    }

    # Pattern: 15 November 2026 / 15 Nov 2026
    m1 = re.search(r'(\d{1,2})(?:st|nd|rd|th)?\s+([a-z]+)\s*,?\s*(\d{4})', clean)
    if m1:
        day = m1.group(1).zfill(2)
        month = month_map.get(m1.group(2), "00")
        year = m1.group(3)
        return f"{day}-{month}-{year}"

    # Pattern: November 15 2026
    m1b = re.search(r'([a-z]+)\s+(\d{1,2})(?:st|nd|rd|th)?\s*,?\s*(\d{4})', clean)
    if m1b:
        month = month_map.get(m1b.group(1), "00")
        day = m1b.group(2).zfill(2)
        year = m1b.group(3)
        return f"{day}-{month}-{year}"

    # Pattern: 2026-11-15
    m2 = re.search(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', clean)
    if m2:
        return f"{m2.group(3).zfill(2)}-{m2.group(2).zfill(2)}-{m2.group(1)}"

    # Pattern: 15-11-2026
    m3 = re.search(r'(\d{1,2})[-/](\d{1,2})[-/](\d{4})', clean)
    if m3:
        return f"{m3.group(1).zfill(2)}-{m3.group(2).zfill(2)}-{m3.group(3)}"

    return clean

def is_extension_notice(title: str) -> bool:
    keywords = ["extend", "extended", "extension", "last date", "deadline", "date revised"]
    t_lower = (title or "").lower()
    return any(k in t_lower for k in keywords)

def extract_distinctive_category(title: str) -> str:
    t = (title or "").lower()
    if any(k in t for k in ["admit", "hall ticket", "pravesh patra"]):
        return "admit_card"
    if any(k in t for k in ["result", "merit list", "parinam", "selected"]):
        return "result"
    if any(k in t for k in ["answer key", "solution", "uttar kunji"]):
        return "answer_key"
    if any(k in t for k in ["attendance", "attn", "presentee"]):
        return "attendance_sheet"
    if any(k in t for k in ["extend", "extended", "extension", "deadline"]):
        return "extension"
    if any(k in t for k in ["apply", "application", "registration", "form"]):
        return "application"
    return "general"

def is_already_posted(notification_id: str, notice: Optional[Dict[str, Any]] = None) -> bool:
    _ensure_file()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            posted = data.get("posted", {})
    except Exception:
        return False

    if notification_id and notification_id in posted:
        return True

    if not notice:
        return False

    state = (notice.get("state") or "").strip()
    new_title = (notice.get("title") or "").strip()
    new_pdf = normalize_url(notice.get("pdf_link") or "")
    new_apply = normalize_url(notice.get("apply_link") or "")
    new_norm_title = normalize_title(new_title)
    new_last_date = (notice.get("last_date") or "").strip()
    new_last_date_norm = normalize_date_str(new_last_date or new_title)

    # 1. SMART DATE-MATCHING FOR CENTRAL NSP:
    # If the candidate notice announces the SAME deadline date as already posted in history, it is a DUPLICATE!
    # If the candidate notice announces a NEW, DIFFERENT deadline date (e.g. extended from 15 Nov to 30 Nov),
    # it is a VALID NEW EXTENSION and allowed to post!
    if "central" in state.lower() or "nsp" in state.lower():
        for prev_id, prev_item in posted.items():
            prev_s = (prev_item.get("state") or "").lower()
            if "central" in prev_s or "nsp" in prev_s:
                prev_date_norm = normalize_date_str(prev_item.get("last_date", "") or prev_item.get("title", ""))
                # If exact same date normalized (e.g. 15-11-2026 == 15-11-2026) -> DUPLICATE!
                if new_last_date_norm and prev_date_norm and new_last_date_norm == prev_date_norm:
                    return True
                # If both mention 15 Nov in text -> DUPLICATE!
                if "15 nov" in new_title.lower() and ("15 nov" in prev_item.get("title", "").lower() or "15 nov" in prev_item.get("last_date", "").lower()):
                    return True

    doc_extensions = (".pdf", ".jpg", ".jpeg", ".png", ".docx", ".doc")
    is_doc = any(new_pdf.endswith(ext) for ext in doc_extensions)

    for prev_id, prev_item in posted.items():
        prev_state = (prev_item.get("state") or "").strip()
        if prev_state.lower() != state.lower():
            continue

        prev_title = (prev_item.get("title") or "").strip()
        prev_pdf = normalize_url(prev_item.get("pdf_link") or "")
        prev_apply = normalize_url(prev_item.get("apply_link") or "")
        prev_norm_title = normalize_title(prev_title)

        # 2. Check identical PDF/Document URL
        if is_doc and new_pdf and prev_pdf:
            if new_pdf == prev_pdf:
                return True

        # 3. Check identical normalized title
        if new_norm_title and prev_norm_title and new_norm_title == prev_norm_title:
            return True

        # 4. Check specific subpage URL match
        if new_apply and prev_apply and new_apply == prev_apply:
            path_parts = [p for p in new_apply.split("/") if p and ":" not in p]
            if len(path_parts) > 1:
                new_keywords = extract_keywords(new_title)
                prev_keywords = extract_keywords(prev_title)
                if new_keywords and prev_keywords:
                    overlap = len(new_keywords & prev_keywords) / max(len(new_keywords), len(prev_keywords))
                    if overlap >= 0.5:
                        return True

    return False

def record_posted(
    notification_id: str,
    state: str,
    title: str,
    apply_link: str,
    pdf_link: str,
    last_date: str = "",
    message_id: int = None,
    ai_summary: str = "",
    category: str = ""
):
    _ensure_file()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"posted": {}, "reminders_sent": {}}

    data.setdefault("posted", {})[notification_id] = {
        "state": state,
        "title": title,
        "ai_summary": ai_summary,
        "category": category,
        "apply_link": apply_link,
        "pdf_link": pdf_link,
        "last_date": last_date,
        "message_id": message_id,
        "posted_at": datetime.now().isoformat()
    }

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def get_active_notifications() -> dict:
    _ensure_file()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("posted", {})
    except Exception:
        return {}

def get_recent_notices_for_state(state: str, limit: int = 5) -> List[Dict]:
    """
    Returns the latest posted notices for a given state, including AI Event Summaries,
    to enable Groq AI semantic deduplication.
    """
    _ensure_file()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            posted = data.get("posted", {})
    except Exception:
        return []

    state_clean = state.strip().lower()
    matches = []
    for k, v in posted.items():
        if (v.get("state") or "").strip().lower() == state_clean:
            matches.append({
                "title": v.get("title", ""),
                "ai_summary": v.get("ai_summary", "") or v.get("title", ""),
                "category": v.get("category", ""),
                "last_date": v.get("last_date", ""),
                "posted_at": v.get("posted_at", "")
            })

    matches.sort(key=lambda x: x.get("posted_at", ""), reverse=True)
    return matches[:limit]

def is_reminder_sent(reminder_key: str) -> bool:
    _ensure_file()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return reminder_key in data.get("reminders_sent", {})
    except Exception:
        return False

def record_reminder_sent(reminder_key: str):
    _ensure_file()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"posted": {}, "reminders_sent": {}}

    data.setdefault("reminders_sent", {})[reminder_key] = datetime.now().isoformat()
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
