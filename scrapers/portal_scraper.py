import requests
from bs4 import BeautifulSoup
import re
import urllib3
import hashlib
from typing import List, Dict
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, quote
from data.storage import is_already_posted

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Strict blacklist of junk / administrative materials that paying students / subscribers DO NOT care about
JUNK_KEYWORDS = [
    # Question papers / Answer sheets / Practice material (Not breaking updates)
    "question paper", "question_paper", "questionpaper", "sample paper", "model paper",
    "practice paper", "pyq", "previous year", "omr sheet", "answer sheet",
    # Administrative & internal officer letters
    "letter to deo", "letter to deos", "letter to principal", "letter to center",
    "instructions to superintendent", "superintendent", "centre superintendent",
    "center superintendent", "nodal officer", "letter to all deos",
    # Attendance & center arrangements
    "attendance sheet", "attn sheet", "attn. sheet", "seat matrix", "centre list",
    "center list", "room allotment", "duty list", "seating plan", "allotment list",
    # Procurement / Tenders
    "tender", "quotation", "auction", "procurement", "bid", "e-tender", "rfp",
    # Internal meetings / Administrative orders
    "meeting", "minutes of meeting", "proceeding", "samiksha", "baithak",
    "transfer", "deputation", "staff", "clerk", "voucher"
]

# High-value actionable student keywords
ACTIONABLE_KEYWORDS = [
    "apply", "application", "form", "registration", "online form", "aavedan",
    "portal", "login", "candidate", "admit card", "admit", "hall ticket",
    "pravesh patra", "answer key", "ans key", "uttar kunji", "objection",
    "result", "merit list", "selected list", "selection list", "parinam", "cutoff",
    "extend", "extended", "extension", "last date", "deadline", "date badha",
    "revised schedule", "exam date", "schedule", "time table", "pariksha tithi",
    "notification", "vigyapti", "vigyapan", "press note", "guidelines", "circular",
    "scholarship", "nmmss", "nmms"
]

def is_junk_notice(title: str, url: str = "") -> bool:
    """
    Returns True if notice is internal administrative noise, old question paper, or center staff material.
    """
    combined = f"{title} {url}".lower()
    return any(k in combined for k in JUNK_KEYWORDS)

def is_outdated_archive(title: str, url: str = "") -> bool:
    """
    Returns True if the notice/document belongs to old expired cycles (2020-2025 or early 2026 archives).
    Current valid session is 2026-27 (or 2027-28 for UP).
    """
    combined = f"{title} {url}".lower()

    # Reject URLs explicitly filed in 2020-2025 folders or early 2026 months
    old_folder_patterns = [
        r"/(?:202[0-5])/",
        r"/(?:instructions|circulars|notices|downloads)/(?:202[0-5]|2026/(?:january|february|march|april|may|june|july))/",
        r"202[0-4]-\d{2,4}",  # e.g. 2024-25, 2023-24
    ]
    for p in old_folder_patterns:
        if re.search(p, combined):
            return True

    # If document URL has 2025 in path and title does NOT explicitly mention current session
    if "/2025/" in url.lower() and not ("2026-27" in combined or "2027-28" in combined):
        return True

    # If title mentions old years 2020-2024 without mentioning 2026-27/2027-28
    has_old = bool(re.search(r"\b202[0-4]\b", combined))
    has_current = bool(re.search(r"\b202[6-8]\b", combined))
    if has_old and not has_current:
        return True

    return False

def is_bare_scheme_name(title: str) -> bool:
    """
    Returns True if title is merely a generic navigation link like "NMMS", "NMMS 2027-28", "NMMSS Exam"
    without any actual notice action word (form, admit card, result, notice, circular, etc.).
    """
    clean = re.sub(r"[^\w\s]", " ", title).strip().lower()
    # Matches strings that ONLY consist of name + optional exam/scheme + optional years
    pattern = r"^(?:national\s+means\s+cum\s+merit(?:\s+scholarship)?|nmms|nmmss|nmmse)(?:\s+(?:exam|scholarship|scheme))?(?:\s+\d{4}(?:\s*[-/]?\s*\d{2,4})?)?$"
    return bool(re.fullmatch(pattern, clean))

def generate_notification_id(state: str, title: str, doc_url: str = "") -> str:
    """
    Generates a deterministic ID.
    If the notification points to a document/PDF, the clean document URL is its canonical identity.
    Otherwise, normalized semantic title is used.
    """
    doc_extensions = (".pdf", ".jpg", ".jpeg", ".png", ".docx", ".doc")
    clean_doc = (doc_url or "").strip().lower()
    clean_doc = re.sub(r"[?#].*$", "", clean_doc).rstrip("/")
    if clean_doc and any(clean_doc.endswith(ext) for ext in doc_extensions):
        cleaned = f"{state.strip().lower()}_{clean_doc}"
    else:
        # Normalize title: strip time prefixes (e.g. 126 days ago, 2 days ago), punctuation, whitespace
        t = re.sub(r"^\s*\d+\s*(?:days?|weeks?|months?|hours?|mins?|minutes?)\s*ago\s*", "", title, flags=re.IGNORECASE)
        t = re.sub(r"^\s*(?:new|notice|circular|📢|🔔)[\s\W]*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+", " ", t).strip().lower()
        cleaned = f"{state.strip().lower()}_{t}"
    return hashlib.md5(cleaned.encode("utf-8")).hexdigest()

def extract_dates_from_text(text: str):
    patterns = [
        r'\b\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}\b',
        r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}\b'
    ]
    found = []
    for p in patterns:
        matches = re.findall(p, text, re.IGNORECASE)
        found.extend(matches)
    return found

def clean_and_normalize_url(base_url: str, href: str, onclick: str = "") -> str:
    candidate = (href or "").strip()

    if not candidate or candidate.startswith("javascript:") or candidate == "#":
        text_to_search = f"{candidate} {onclick or ''}"
        match = re.search(r"""(?:href|window\.open|openDoc|viewPdf|location\.href)[=\s(]['"]([^'"]+)['"]""", text_to_search, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
        else:
            match_path = re.search(r"""['"]([^'"]+\.(?:pdf|docx?|html?|aspx?|php|jpe?g|png))['"]""", text_to_search, re.IGNORECASE)
            if match_path:
                candidate = match_path.group(1).strip()
            else:
                return base_url

    if not candidate or candidate.startswith("javascript:") or candidate.startswith("#"):
        return base_url

    if candidate.startswith("//"):
        candidate = "https:" + candidate

    full_url = urljoin(base_url, candidate)
    try:
        parts = urlsplit(full_url)
        if not parts.scheme or not parts.netloc:
            return base_url

        scheme = parts.scheme.lower()
        if scheme not in ["http", "https"]:
            scheme = "https"

        clean_path = quote(parts.path, safe="/:@&?=+%#")
        clean_url = urlunsplit((scheme, parts.netloc, clean_path, parts.query, parts.fragment))
        return clean_url
    except Exception:
        return base_url

def scrape_state_website(state: str, config: dict) -> List[Dict]:
    """
    Scrapes an official state education portal looking for genuine student NMMS notifications.
    Strictly filters out:
    1. Internal administrative noise / DEO letters / Question papers / Attendance sheets
    2. Outdated archive notices from past years (2020-2025)
    3. Bare menu navigation buttons (e.g. "NMMS 2027-28" without any document)
    """
    notifications = []
    seen_ids = set()
    url = config.get("official_url")
    keywords = config.get("keywords", ["NMMS"])

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        if resp.status_code != 200:
            return notifications

        soup = BeautifulSoup(resp.text, "html.parser")

        # Search all anchor tags
        for a_tag in soup.find_all("a"):
            raw_text = a_tag.get_text(strip=True)

            if not raw_text:
                img_tag = a_tag.find("img")
                if img_tag:
                    raw_text = img_tag.get("alt", "").strip() or img_tag.get("title", "").strip()
                if not raw_text:
                    raw_text = a_tag.get("title", "").strip() or a_tag.get("aria-label", "").strip()

            # Strip dynamic relative time prefixes e.g. "126 days ago"
            text = re.sub(r"^\s*[\d\s]+(?:days?|weeks?|months?|hours?|minutes?)\s*ago\s*", "", raw_text, flags=re.IGNORECASE).strip()
            if not text:
                continue

            raw_href = a_tag.get("href", "").strip()
            raw_onclick = a_tag.get("onclick", "").strip()
            if not raw_href and not raw_onclick:
                continue

            # Must match NMMS keywords
            if not any(k.lower() in text.lower() for k in keywords):
                continue

            # Clean and resolve absolute URL
            resolved_url = clean_and_normalize_url(url, raw_href, raw_onclick)
            url_lower = resolved_url.lower()
            raw_href_lower = raw_href.lower()
            raw_onclick_lower = raw_onclick.lower()

            doc_extensions = (".pdf", ".jpg", ".jpeg", ".png")
            is_doc = any(url_lower.endswith(ext) or ext in raw_href_lower or ext in raw_onclick_lower for ext in doc_extensions)

            # GATE 1: Reject internal administrative noise, question papers, staff documents
            if is_junk_notice(text, resolved_url):
                continue

            # GATE 2: Reject outdated archives from 2020-2025 or early 2026 months
            if is_outdated_archive(text, resolved_url):
                continue

            # GATE 3: If not a document, reject bare menu buttons like "NMMS", "NMMS 2027-28"
            if not is_doc and is_bare_scheme_name(text):
                continue

            # GATE 4: If not a document, must contain at least one meaningful student action keyword
            if not is_doc and not any(k in text.lower() for k in ["form", "apply", "registration", "admit", "result", "date", "key", "portal", "aavedan"]):
                continue

            pdf_link = resolved_url if is_doc else ""
            apply_link = resolved_url if not is_doc else url

            notif_id = generate_notification_id(state, text, pdf_link)
            if notif_id in seen_ids:
                continue
            seen_ids.add(notif_id)

            item_data = {
                "id": notif_id,
                "state": state,
                "authority": config.get("authority", "State Education Board"),
                "title": text,
                "update_type": "Official Update",
                "apply_link": apply_link,
                "pdf_link": pdf_link,
                "apply_start": "",
                "last_date": "",
                "exam_date": ""
            }

            # GATE 5: Multi-level duplicate protection
            if is_already_posted(notif_id, item_data):
                continue

            notifications.append(item_data)
            if len(notifications) >= 3:
                break

    except Exception:
        pass

    return notifications
