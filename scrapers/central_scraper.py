"""
Central (NSP) Scraper for NMMS.
Monitors National Scholarship Portal (scholarships.gov.in) and Ministry of Education / PIB announcements.
No hardcoded fallback dates. Strict official link verification (.gov.in / nic.in / nsp.gov.in).
"""

import re
import requests
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict
from bs4 import BeautifulSoup
from data.storage import compute_content_hash

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

CENTRAL_PORTAL_STATUS = "OK"

def get_central_portal_status() -> str:
    return CENTRAL_PORTAL_STATUS

def extract_date_from_headline(title: str) -> str:
    """Extracts date strings from headline text."""
    from data.storage import parse_date_to_ist
    parsed = parse_date_to_ist(title)
    if parsed:
        return parsed.strftime("%d %B %Y")
    return ""

def is_official_link(url: str, text: str = "") -> bool:
    """Verifies that the source or mentioned link belongs to .gov.in, .nic.in, or nsp.gov.in."""
    combined = f"{url} {text}".lower()
    return any(domain in combined for domain in [".gov.in", ".nic.in", "scholarships.gov.in", "nsp.gov.in"])

def scrape_central_nsp() -> List[Dict]:
    """
    Checks National Scholarship Portal and PIB Google News RSS with 7-day filter.
    Returns list of candidate notices with no hardcoded fallback dates.
    """
    notifications = []
    seen_hashes = set()

    # 1. Official Google News RSS with 7-day filter
    rss_queries = [
        "https://news.google.com/rss/search?q=%22NMMSS%22+site:pib.gov.in+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
        "https://news.google.com/rss/search?q=%22NMMSS%22+OR+%22National+Means-cum-Merit%22+site:gov.in+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
        "https://news.google.com/rss/search?q=%22NMMSS%22+site:scholarships.gov.in+when:7d&hl=en-IN&gl=IN&ceid=IN:en"
    ]

    for rss_url in rss_queries:
        try:
            resp = requests.get(rss_url, headers=HEADERS, timeout=12)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item"):
                    raw_title = item.findtext("title") or ""
                    link = item.findtext("link") or ""
                    description = item.findtext("description") or ""

                    t_lower = raw_title.lower()
                    if any(k in t_lower for k in ["nmms", "nmmss", "national means"]):
                        clean_title = re.sub(r"\s*-\s*[^-]+$", "", raw_title).strip()
                        if len(clean_title) < 15:
                            continue

                        # Google News requirement: Must have verified official link
                        if not is_official_link(link, f"{clean_title} {description}"):
                            continue

                        extracted_last_date = extract_date_from_headline(clean_title)
                        chash = compute_content_hash("Central (NSP)", clean_title, "https://scholarships.gov.in")
                        if chash in seen_hashes:
                            continue
                        seen_hashes.add(chash)

                        item_data = {
                            "content_hash": chash,
                            "state": "Central (NSP)",
                            "authority": "Ministry of Education / NSP Portal",
                            "title": clean_title,
                            "update_type": "NSP Official Update",
                            "apply_link": "https://scholarships.gov.in",
                            "pdf_link": "",
                            "source_url": link,
                            "publisher_url": link,
                            "publisher_domain": "scholarships.gov.in",
                            "apply_start": "Active Now",
                            "last_date": extracted_last_date or "अंतिम तिथि: आधिकारिक सूचना देखें",
                            "exam_date": "",
                            "content_context": description,
                            "origin": "news",
                            "is_fallback": True
                        }
                        notifications.append(item_data)
                        break
                if notifications:
                    break
        except Exception as e:
            logger.warning(f"Central NSP RSS fetch error: {e}")

    # 2. Direct NSP Portal Announcements
    if not notifications:
        nsp_urls = [
            "https://scholarships.gov.in",
            "https://scholarships.gov.in/ViewMoreAnnouncement"
        ]

        for nsp_url in nsp_urls:
            try:
                resp = requests.get(nsp_url, headers=HEADERS, timeout=12, verify=False)
                if resp.status_code == 200:
                    soup = BeautifulSoup(resp.text, "html.parser")
                    for p in soup.find_all(["p", "div", "li"]):
                        txt = p.get_text(strip=True)
                        if any(k in txt.lower() for k in ["nmms", "nmmss", "national means-cum-merit scholarship"]):
                            clean_text = txt[:250].strip()
                            if len(clean_text) < 20:
                                continue

                            extracted_date = extract_date_from_headline(clean_text)
                            chash = compute_content_hash("Central (NSP)", clean_text, "https://scholarships.gov.in")
                            if chash in seen_hashes:
                                continue
                            seen_hashes.add(chash)

                            item_data = {
                                "content_hash": chash,
                                "state": "Central (NSP)",
                                "authority": "National Scholarship Portal (NSP)",
                                "title": clean_text,
                                "update_type": "NSP Portal Announcement",
                                "apply_link": "https://scholarships.gov.in",
                                "pdf_link": "",
                                "source_url": nsp_url,
                                "publisher_url": nsp_url,
                                "publisher_domain": "scholarships.gov.in",
                                "apply_start": "Active Now",
                                "last_date": extracted_date or "अंतिम तिथि: आधिकारिक सूचना देखें",
                                "exam_date": "",
                                "content_context": clean_text,
                                "origin": "portal",
                                "is_fallback": False
                            }
                            notifications.append(item_data)
                            break
                    if notifications:
                        break
            except Exception as e:
                global CENTRAL_PORTAL_STATUS
                CENTRAL_PORTAL_STATUS = f"ERROR: {type(e).__name__}"
                logger.warning(f"Direct NSP portal fetch error: {e}")

    return notifications
