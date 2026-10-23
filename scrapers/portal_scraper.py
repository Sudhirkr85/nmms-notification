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
            match_path = re.search(r"""['"]([^'"]+\.(?:pdf|docx?|html?|aspx?|php|jpe?g|png))['"]""", text_to_search, re.IGNORECASE)
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
    Supports regular links, PDFs, and image/poster notices (via alt/title attributes).
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
        
        # Generic navbar labels to ignore unless they link directly to a document/PDF
        generic_labels = {
            "nmms", "nmmss", "nmmse", "nmms exam", "nmms scholarship",
            "nmmss scholarship", "📢 nmms scholarship"
        }

        # Search all anchor tags
        for a_tag in soup.find_all("a"):
            raw_text = a_tag.get_text(strip=True)

            # If no direct inner text, extract from alt, title, or aria-label of child img or anchor
            if not raw_text:
                img_tag = a_tag.find("img")
                if img_tag:
                    raw_text = img_tag.get("alt", "").strip() or img_tag.get("title", "").strip()
                if not raw_text:
                    raw_text = a_tag.get("title", "").strip() or a_tag.get("aria-label", "").strip()

            # Strip dynamic relative time prefixes like "126 days ago" or "142 weeks ago"
            text = re.sub(r"^[\d\s]+(?:days?|weeks?|months?|hours?|minutes?)\s+ago\s*", "", raw_text, flags=re.IGNORECASE).strip()
            if not text:
                continue

            raw_href = a_tag.get("href", "").strip()
            raw_onclick = a_tag.get("onclick", "").strip()
            if not raw_href and not raw_onclick:
                continue

            # Match any NMMS keyword in the anchor text or image alt
            if any(k.lower() in text.lower() for k in keywords):
                # Clean and resolve absolute URL
                resolved_url = clean_and_normalize_url(url, raw_href, raw_onclick)
                url_lower = resolved_url.lower()
                raw_href_lower = raw_href.lower()
                raw_onclick_lower = raw_onclick.lower()

                # Document extensions including PDFs and notice images/scans
                doc_extensions = (".pdf", ".jpg", ".jpeg", ".png")
                is_doc = any(url_lower.endswith(ext) or ext in raw_href_lower or ext in raw_onclick_lower for ext in doc_extensions)

                # Skip generic 1-2 word menu bar links that are not documents
                if not is_doc and text.lower() in generic_labels:
                    continue

                # Skip outdated archive notices from 2020-2024 unless 2025/2026/2027 is mentioned
                combined_check = f"{text} {resolved_url}"
                has_old_year = bool(re.search(r"202[0-4]", combined_check))
                has_current_year = bool(re.search(r"202[5-8]", combined_check))
                if has_old_year and not has_current_year:
                    continue

                pdf_link = resolved_url if is_doc else ""
                apply_link = resolved_url if not is_doc else url

                notif_id = generate_notification_id(state, text)
                if notif_id in seen_ids:
                    continue
                seen_ids.add(notif_id)

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
                if len(notifications) >= 5:
                    break

    except Exception:
        pass

    return notifications
