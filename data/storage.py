import json
import os
import re
import hashlib
from datetime import datetime
from typing import Dict, Any, Optional

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "history.json")

def _ensure_file():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"posted": {}, "reminders_sent": {}}, f, indent=2)

def normalize_url(url: str) -> str:
    """
    Normalizes a URL by stripping fragments, query params, trailing slashes, and lowercasing.
    """
    if not url:
        return ""
    clean = url.strip()
    clean = re.sub(r"[?#].*$", "", clean)  # Remove query and hash
    return clean.rstrip("/").lower()

def normalize_title(title: str) -> str:
    """
    Cleans title to extract core semantic words:
    - Removes emojis, badges (NEW, Click here, etc.)
    - Removes relative time phrases ('126 days ago', '2 weeks ago', etc.)
    - Removes punctuation and extra whitespace
    - Lowercases
    """
    if not title:
        return ""

    t = title.strip()
    # Strip relative time e.g. "126 days ago", "127 days ago", "yesterday", etc.
    t = re.sub(r"^\s*\d+\s*(?:days?|weeks?|months?|hours?|mins?|minutes?)\s*ago\s*", "", t, flags=re.IGNORECASE)
    # Remove leading common announcement symbols/prefixes
    t = re.sub(r"^[\s\W]*(?:new|notice|circular|📢|🔔|important|latest|update|attention)[\s\W]*", "", t, flags=re.IGNORECASE)
    # Retain alphanumeric and Indic scripts (Devanagari, Gujarati, Kannada, Tamil, Telugu, Malayalam, Gurmukhi, Bengali)
    t = re.sub(r"[^\w\s\u0900-\u0D7F]", " ", t)
    # Normalize whitespace
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t

def extract_keywords(text: str) -> set:
    """
    Extracts significant words (length >= 3, excluding ultra-common filler words).
    """
    norm = normalize_title(text)
    words = re.findall(r"\b\w{3,}\b", norm)
    stopwords = {
        "the", "and", "for", "with", "from", "regarding", "notice", "circular",
        "official", "portal", "check", "click", "here", "view", "link", "online",
        "scheme", "scholarship", "examination", "exam"
    }
    return {w for w in words if w not in stopwords}

def is_extension_notice(title: str) -> bool:
    keywords = ["extend", "extended", "extension", "last date", "deadline", "date revised"]
    t_lower = (title or "").lower()
    return any(k in t_lower for k in keywords)

def extract_distinctive_category(title: str) -> str:
    """
    Detects critical category to prevent cross-category false positives.
    E.g. Admit Card vs Result vs Form vs Attendance Sheet should NEVER conflict.
    """
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
    """
    Robust multi-level duplicate detection:
    1. Direct notification ID check in history.json
    2. Same PDF / document file already posted for this state
    3. Same specific subpage URL already posted for this state
    4. Exact normalized title match for the same state
    5. Event-level deduplication for Central NSP (same date extension, high semantic similarity)

    Safeguards:
    - Different categories (e.g. Admit Card vs Result vs Attendance) are NEVER duplicates!
    - Different extension dates (e.g. 15 Nov vs 30 Dec) are NEVER duplicates!
    - Different states are NEVER duplicates!
    """
    _ensure_file()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            posted = data.get("posted", {})
    except Exception:
        return False

    # 1. Exact ID check
    if notification_id and notification_id in posted:
        return True

    if not notice:
        return False

    state = (notice.get("state") or "").strip()
    new_title = (notice.get("title") or "").strip()
    new_pdf = normalize_url(notice.get("pdf_link") or "")
    new_apply = normalize_url(notice.get("apply_link") or "")
    new_last_date = (notice.get("last_date") or "").strip().lower()
    new_norm_title = normalize_title(new_title)
    new_keywords = extract_keywords(new_title)
    new_category = extract_distinctive_category(new_title)

    doc_extensions = (".pdf", ".jpg", ".jpeg", ".png", ".docx", ".doc")
    is_doc = any(new_pdf.endswith(ext) for ext in doc_extensions)

    for prev_id, prev_item in posted.items():
        prev_state = (prev_item.get("state") or "").strip()
        if prev_state.lower() != state.lower():
            continue  # Different state, never a duplicate

        prev_title = (prev_item.get("title") or "").strip()
        prev_pdf = normalize_url(prev_item.get("pdf_link") or "")
        prev_apply = normalize_url(prev_item.get("apply_link") or "")
        prev_last_date = (prev_item.get("last_date") or "").strip().lower()
        prev_norm_title = normalize_title(prev_title)
        prev_category = extract_distinctive_category(prev_title)

        # Category Safeguard: If one is Admit Card and the other is Result or Attendance, never duplicate
        if new_category != "general" and prev_category != "general" and new_category != prev_category:
            continue

        # 2. Check identical PDF/Document URL for the same state
        if is_doc and new_pdf and prev_pdf:
            if new_pdf == prev_pdf:
                return True

        # 3. Check identical normalized title
        if new_norm_title and prev_norm_title and new_norm_title == prev_norm_title:
            return True

        # 4. Check specific subpage URL match (not root homepage)
        # E.g. entdata.co.in/NMMS202728/ADMIT_ATTN/ATTN/attnsearch.php
        if new_apply and prev_apply and new_apply == prev_apply:
            path_parts = [p for p in new_apply.split("/") if p and ":" not in p]
            if len(path_parts) > 1:  # Specific subpage/script
                prev_keywords = extract_keywords(prev_title)
                if new_keywords and prev_keywords:
                    overlap = len(new_keywords & prev_keywords) / max(len(new_keywords), len(prev_keywords))
                    if overlap >= 0.5:
                        return True

        # 5. Central NSP Event & Headline similarity deduplication
        if "central" in state.lower() or "nsp" in state.lower():
            # Check if both are deadline extension notices
            if is_extension_notice(new_title) and is_extension_notice(prev_title):
                # If both mention the same last_date (e.g. 15 Nov / 15 November)
                if new_last_date and prev_last_date and (new_last_date in prev_last_date or prev_last_date in new_last_date):
                    return True

            # Check headline keyword similarity (different media outlets reporting same event)
            prev_keywords = extract_keywords(prev_title)
            if new_keywords and prev_keywords:
                intersection = len(new_keywords & prev_keywords)
                union = len(new_keywords | prev_keywords)
                jaccard = intersection / union if union > 0 else 0
                if jaccard >= 0.60:
                    return True

    return False

def record_posted(notification_id: str, state: str, title: str, apply_link: str, pdf_link: str, last_date: str = "", message_id: int = None):
    _ensure_file()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        data = {"posted": {}, "reminders_sent": {}}

    data.setdefault("posted", {})[notification_id] = {
        "state": state,
        "title": title,
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

