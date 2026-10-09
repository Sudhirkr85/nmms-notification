import requests
from bs4 import BeautifulSoup
import re
import urllib3
import hashlib
from typing import List, Dict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def generate_notification_id(state: str, title: str) -> str:
    cleaned = f"{state.strip().lower()}_{title.strip().lower()}"
    return hashlib.md5(cleaned.encode("utf-8")).hexdigest()

def extract_dates_from_text(text: str):
    """
    Extracts dates like 15-10-2026, 15/10/2026, 15 Oct 2026, etc.
    """
    patterns = [
        r'\b\d{1,2}[-/\.]\d{1,2}[-/\.]\d{2,4}\b',
        r'\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{2,4}\b'
    ]
    found = []
    for p in patterns:
        matches = re.findall(p, text, re.IGNORECASE)
        found.extend(matches)
    return found

from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit, quote

def clean_and_normalize_url(base_url: str, href: str, onclick: str = "") -> str:
    """
    Guarantees a clean, absolute, valid URL from relative paths, protocols, anchors, spaces, and javascript handlers.
    """
    candidate = (href or "").strip()

    # Check if href is javascript or empty or #, but has real link embedded or in onclick
    if not candidate or candidate.startswith("javascript:") or candidate == "#":
        text_to_search = f"{candidate} {onclick or ''}"
        # Extract url from window.open('...'), openDoc('...'), etc.
        match = re.search(r"""(?:href|window\.open|openDoc|viewPdf|location\.href)[=\s(]['"]([^'"]+)['"]""", text_to_search, re.IGNORECASE)
        if match:
            candidate = match.group(1).strip()
        else:
            match_path = re.search(r"""['"]([^'"]+\.(?:pdf|docx?|html?|aspx?|php))['"]""", text_to_search, re.IGNORECASE)
            if match_path:
                candidate = match_path.group(1).strip()
            else:
                return base_url

    if not candidate or candidate.startswith("javascript:") or candidate.startswith("#"):
        return base_url

    # Handle protocol-relative URLs like //example.com/doc.pdf
    if candidate.startswith("//"):
        candidate = "https:" + candidate

    full_url = urljoin(base_url, candidate)
    try:
        parts = urlsplit(full_url)
        if not parts.scheme or not parts.netloc:
            return base_url

        # Ensure scheme is http or https
        scheme = parts.scheme.lower()
        if scheme not in ["http", "https"]:
            scheme = "https"

        # Properly quote path to encode spaces and special characters without double-quoting
        clean_path = quote(parts.path, safe="/:@&?=+%#")
        clean_url = urlunsplit((scheme, parts.netloc, clean_path, parts.query, parts.fragment))
        return clean_url
    except Exception:
        return base_url

def scrape_state_website(state: str, config: dict) -> List[Dict]:
    """
    Scrapes an official state education portal looking for NMMS links or notifications.
    """
    notifications = []
    url = config.get("official_url")
    keywords = config.get("keywords", ["NMMS"])

    try:
        resp = requests.get(url, headers=HEADERS, timeout=12, verify=False)
        if resp.status_code != 200:
            return notifications

        soup = BeautifulSoup(resp.text, "html.parser")
        
        # Search all anchor tags
        for a_tag in soup.find_all("a"):
            text = a_tag.get_text(strip=True)
            raw_href = a_tag.get("href", "").strip()
            raw_onclick = a_tag.get("onclick", "").strip()

            # Match any NMMS keyword
            if any(k.lower() in text.lower() for k in keywords):
                # Clean and resolve absolute URL
                resolved_url = clean_and_normalize_url(url, raw_href, raw_onclick)
                is_pdf = resolved_url.lower().endswith(".pdf") or ".pdf" in raw_href.lower() or ".pdf" in raw_onclick.lower()

                pdf_link = resolved_url if is_pdf else ""
                apply_link = resolved_url if not is_pdf else url

                notif_id = generate_notification_id(state, text)
                notifications.append({
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
                })
                if len(notifications) >= 2:
                    break

    except Exception:
        pass

    return notifications
