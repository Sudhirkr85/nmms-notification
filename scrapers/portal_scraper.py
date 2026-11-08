import requests
from bs4 import BeautifulSoup
import re
import urllib3
import hashlib
import logging
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import List, Dict
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, quote
from data.storage import is_already_posted

logger = logging.getLogger(__name__)

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Upgrade-Insecure-Requests": "1"
}

# Strict blacklist of junk / administrative materials that paying students / subscribers DO NOT care about
JUNK_KEYWORDS = [
    # Question papers / Answer sheets / Practice material (Not breaking updates)
    "question paper", "question_paper", "questionpaper", "sample paper", "model paper",
    "practice paper", "pyq", "previous year", "omr sheet",
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
    "pravesh patra", "answer key", "ans key", "uttar kunji", "uttar mala", "objection",
    "result", "merit list", "selected list", "selection list", "parinam", "cutoff",
    "extend", "extended", "extension", "last date", "deadline", "date badha",
    "revised schedule", "exam date", "schedule", "time table", "pariksha tithi",
    "notification", "vigyapti", "vigyapan", "press note", "guidelines", "circular",
    "scholarship", "nmmss", "nmms"
]

# Verified high-priority announcements buffer for critical breaking events
ACTIVE_VERIFIED_ANNOUNCEMENTS = [
    {
        "state": "Uttar Pradesh",
        "authority": "Exam Regulatory Authority UP / SCERT UP",
        "title": "UP NMMS 2027-28 Provisional Answer Key Out - File Objections by 13 Nov",
        "update_type": "Provisional Answer Key & Objection",
        "apply_link": "https://entdata.co.in",
        "pdf_link": "",
        "apply_start": "Active Now",
        "last_date": "13 November 2026 (06:00 PM)",
        "exam_date": "01 November 2026",
        "content_context": "परीक्षा नियामक प्राधिकारी उत्तर प्रदेश, प्रयागराज द्वारा 1 नवंबर 2026 को आयोजित राष्ट्रीय आय एवं योग्यता आधारित छात्रवृत्ति योजना (NMMS) परीक्षा 2027-28 की अनंतिम उत्तरमाला (Provisional Answer Key) आधिकारिक वेबसाइट entdata.co.in पर जारी कर दी गई है। यदि किसी अभ्यर्थी को किसी प्रश्न के उत्तर पर आपत्ति है, तो वे दिनांक 13.11.2026 की सायं 06:00 बजे तक आधिकारिक ईमेल nmmsntsexam@gmail.com पर साक्ष्य सहित ऑनलाइन आपत्ति भेज सकते हैं। बिना साक्ष्य आपत्ति निरस्त कर दी जाएगी।"
    }
]

def get_academic_cycle():
    """
    Computes current base year and active academic sessions dynamically.
    Works automatically for 2026, 2027, 2028, and every year in future!
    """
    now = datetime.now()
    cur_year = now.year
    # In Jan-May, the previous calendar year's exam session is still in the result/merit phase
    base_year = (cur_year - 1) if now.month <= 5 else cur_year

    active_sessions = [
        f"{base_year}-{str(base_year + 1)[-2:]}",       # e.g. 2026-27
        f"{base_year + 1}-{str(base_year + 2)[-2:]}",   # e.g. 2027-28 (used by UP)
        f"{base_year - 1}-{str(base_year)[-2:]}"        # e.g. 2025-26 (for recent results declared)
    ]
    return base_year, active_sessions

def is_junk_notice(title: str, url: str = "") -> bool:
    """
    Returns True if notice is internal administrative noise, old question paper, or center staff material.
    Guarantees critical student updates (Answer Key, Objection, Admit Card, Result) are NEVER dropped!
    """
    combined = f"{title} {url}".lower()

    # WHITELIST: High-value student actionable notices must NEVER be dropped as junk!
    actionable_whitelist = [
        "answer key", "answerkey", "ans key", "uttar kunji", "uttar mala", "उत्तर कुंजी", "उत्तरमाला",
        "objection", "आपत्ति",
        "admit card", "admitcard", "hall ticket", "pravesh patra", "प्रवेश पत्र",
        "result", "merit list", "selected list", "selection list", "parinam", "परिणाम", "cutoff",
        "extend", "extended", "last date", "deadline"
    ]
    if any(w in combined for w in actionable_whitelist):
        return False

    return any(k in combined for k in JUNK_KEYWORDS)

def is_outdated_archive(title: str, url: str = "") -> bool:
    """
    Returns True if the notice/document belongs to old expired cycles.
    Dynamically computes cutoffs so it works in 2026, 2027, 2028, etc. without code changes.
    """
    base_year, active_sessions = get_academic_cycle()
    combined = f"{title} {url}".lower()

    # Reject URLs explicitly filed in expired past years
    for past_y in range(2018, base_year):
        if f"/{past_y}/" in combined or f"/{past_y}-" in combined or f"_{past_y}_" in combined:
            return True
        # Reject past academic sessions (e.g. 2024-25 when base is 2026)
        past_session = f"{past_y}-{str(past_y + 1)[-2:]}"
        if past_session in combined and not any(s in combined for s in active_sessions[:2]):
            return True

    # Reject early months of base year during fresh application season (Aug - Dec)
    now = datetime.now()
    if now.month >= 8:
        early_months = ["january", "february", "march", "april", "may", "june", "july"]
        for m in early_months:
            if f"/{base_year}/{m}/" in combined:
                return True

    return False

def is_bare_scheme_name(title: str) -> bool:
    """
    Returns True if title is merely a generic navigation link like "NMMS", "NMMS 2027-28", "NMMSS Exam"
    without any actual notice action word (form, admit card, result, notice, circular, key, etc.).
    """
    clean = re.sub(r"[^\w\s]", " ", title).strip().lower()
    pattern = r"^(?:national\s+means\s+cum\s+merit(?:\s+scholarship)?|nmms|nmmss|nmmse)(?:\s+(?:exam|scholarship|scheme))?(?:\s+\d{4}(?:\s*[-/]?\s*\d{2,4})?)?$"
    return bool(re.fullmatch(pattern, clean))

def generate_notification_id(state: str, title: str, doc_url: str = "") -> str:
    doc_extensions = (".pdf", ".jpg", ".jpeg", ".png", ".docx", ".doc")
    clean_doc = (doc_url or "").strip().lower()
    clean_doc = re.sub(r"[?#].*$", "", clean_doc).rstrip("/")
    if clean_doc and any(clean_doc.endswith(ext) for ext in doc_extensions):
        cleaned = f"{state.strip().lower()}_{clean_doc}"
    else:
        t = re.sub(r"^\s*\d+\s*(?:days?|weeks?|months?|hours?|mins?|minutes?)\s*ago\s*", "", title, flags=re.IGNORECASE)
        t = re.sub(r"^\s*(?:new|notice|circular|📢|🔔)[\s\W]*", "", t, flags=re.IGNORECASE)
        t = re.sub(r"\s+", " ", t).strip().lower()
        cleaned = f"{state.strip().lower()}_{t}"
    return hashlib.md5(cleaned.encode("utf-8")).hexdigest()

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

def scrape_state_news_rss(state: str, config: dict) -> List[Dict]:
    """
    Fallback & live radar: Queries Google News RSS for state NMMS updates.
    Crucial for states whose portals are behind Cloudflare JS challenges (e.g. entdata.co.in),
    are down, or block cloud runner IP addresses.
    """
    notifications = []
    seen_ids = set()
    alias = config.get("alias", "")
    hindi_name = config.get("hindi_name", "")

    queries = []
    if alias and alias.lower() != state.lower():
        queries.append(f'https://news.google.com/rss/search?q=%22NMMS%22+(%22{state}%22+OR+%22{alias}%22)+when:7d&hl=en-IN&gl=IN&ceid=IN:en')
    else:
        queries.append(f'https://news.google.com/rss/search?q=%22NMMS%22+%22{state}%22+when:7d&hl=en-IN&gl=IN&ceid=IN:en')

    if hindi_name:
        queries.append(f'https://news.google.com/rss/search?q=%22NMMS%22+%22{hindi_name}%22+when:7d&hl=hi&gl=IN&ceid=IN:hi')

    if state == "Uttar Pradesh":
        queries.append('https://news.google.com/rss/search?q=(%22entdata%22+OR+%22nmmsntsexam%22)+when:7d&hl=en-IN&gl=IN&ceid=IN:en')

    # Other states list to prevent cross-state false positives
    other_states = [
        "bihar", "rajasthan", "madhya pradesh", "maharashtra", "gujarat",
        "haryana", "punjab", "delhi", "west bengal", "odisha", "jharkhand",
        "chhattisgarh", "karnataka", "kerala", "tamil nadu", "andhra", "telangana", "assam"
    ]
    cur_state_l = state.lower()

    for rss_url in queries:
        try:
            resp = requests.get(rss_url, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                continue

            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                raw_title = item.findtext("title") or ""
                clean_title = re.sub(r"\s*-\s*[^-]+$", "", raw_title).strip()
                if len(clean_title) < 15:
                    continue

                t_lower = clean_title.lower()

                if not any(k in t_lower for k in ["nmms", "nmmss", "national means", "मेधा छात्रवृत्ति"]):
                    continue

                # Ensure it belongs to this state
                state_match = (
                    cur_state_l in t_lower or
                    (alias and f" {alias.lower()} " in f" {t_lower} ") or
                    (hindi_name and hindi_name in clean_title) or
                    ("entdata" in t_lower and state == "Uttar Pradesh")
                )
                if not state_match:
                    continue

                # Avoid other states mentioned predominantly
                conflicting = any(os in t_lower for os in other_states if os != cur_state_l and os not in cur_state_l)
                if conflicting and cur_state_l not in t_lower and not ("entdata" in t_lower and state == "Uttar Pradesh"):
                    continue

                # Actionable check
                actionable_match = any(k in t_lower for k in [
                    "answer key", "ans key", "uttar kunji", "objection", "उत्तर कुंजी", "उत्तरमाला", "आपत्ति",
                    "admit card", "admit", "hall ticket", "pravesh patra", "प्रवेश पत्र",
                    "result", "merit list", "selected list", "selection list", "parinam", "परिणाम", "cutoff",
                    "apply", "registration", "application", "form", "aavedan", "आवेदन",
                    "extend", "extended", "last date", "deadline", "date badha"
                ])
                if not actionable_match:
                    continue

                if is_junk_notice(clean_title, ""):
                    continue
                if is_outdated_archive(clean_title, ""):
                    continue

                notif_id = generate_notification_id(state, clean_title, "")
                if notif_id in seen_ids:
                    continue
                seen_ids.add(notif_id)

                item_data = {
                    "id": notif_id,
                    "state": state,
                    "authority": config.get("authority", "State Education Board"),
                    "title": clean_title,
                    "update_type": "Official Update",
                    "apply_link": config.get("official_url", ""),
                    "pdf_link": "",
                    "apply_start": "",
                    "last_date": "",
                    "exam_date": ""
                }

                if is_already_posted(notif_id, item_data):
                    continue

                notifications.append(item_data)
                if len(notifications) >= 2:
                    break

            if notifications:
                break
        except Exception as e:
            logger.warning(f"Error in state news RSS for {state}: {e}")

    return notifications

def scrape_state_website(state: str, config: dict) -> List[Dict]:
    """
    Scrapes an official state education portal looking for genuine student NMMS notifications.
    Includes active verified announcements buffer and automatic fallback to Google News RSS
    when portals are blocked by Cloudflare (e.g. entdata.co.in) or down.
    """
    notifications = []
    seen_ids = set()
    url = config.get("official_url")
    keywords = config.get("keywords", ["NMMS"])

    # 1. Check verified breaking announcements buffer for this state
    for active_item in ACTIVE_VERIFIED_ANNOUNCEMENTS:
        if active_item.get("state", "").lower() == state.lower():
            notif_id = generate_notification_id(state, active_item["title"], active_item.get("pdf_link", ""))
            candidate = {
                **active_item,
                "id": notif_id
            }
            if not is_already_posted(notif_id, candidate):
                notifications.append(candidate)
                seen_ids.add(notif_id)

    # 2. Direct Portal Scraping
    portal_found = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for a_tag in soup.find_all("a"):
                raw_text = a_tag.get_text(strip=True)

                if not raw_text:
                    img_tag = a_tag.find("img")
                    if img_tag:
                        raw_text = img_tag.get("alt", "").strip() or img_tag.get("title", "").strip()
                    if not raw_text:
                        raw_text = a_tag.get("title", "").strip() or a_tag.get("aria-label", "").strip()

                text = re.sub(r"^\s*[\d\s]+(?:days?|weeks?|months?|hours?|minutes?)\s*ago\s*", "", raw_text, flags=re.IGNORECASE).strip()
                if not text:
                    continue

                raw_href = a_tag.get("href", "").strip()
                raw_onclick = a_tag.get("onclick", "").strip()
                if not raw_href and not raw_onclick:
                    continue

                if not any(k.lower() in text.lower() for k in keywords):
                    continue

                resolved_url = clean_and_normalize_url(url, raw_href, raw_onclick)
                url_lower = resolved_url.lower()
                raw_href_lower = raw_href.lower()
                raw_onclick_lower = raw_onclick.lower()

                doc_extensions = (".pdf", ".jpg", ".jpeg", ".png")
                is_doc = any(url_lower.endswith(ext) or ext in raw_href_lower or ext in raw_onclick_lower for ext in doc_extensions)

                if is_junk_notice(text, resolved_url):
                    continue
                if is_outdated_archive(text, resolved_url):
                    continue
                if not is_doc and is_bare_scheme_name(text):
                    continue
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

                if is_already_posted(notif_id, item_data):
                    continue

                portal_found.append(item_data)
                if len(portal_found) >= 3:
                    break
    except Exception as e:
        logger.warning(f"Error scraping portal for {state}: {e}")

    notifications.extend(portal_found)

    # 3. Fallback to Google News RSS if no notifications found from portal
    if not notifications:
        rss_notices = scrape_state_news_rss(state, config)
        notifications.extend(rss_notices)

    return notifications
