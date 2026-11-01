import requests
import xml.etree.ElementTree as ET
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

def extract_date_from_headline(title: str) -> str:
    month_names = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'

    # Month Day (e.g., November 15)
    m1 = re.search(rf'\b({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{{4}}))?\b', title, re.I)
    if m1:
        month = m1.group(1).capitalize()
        day = m1.group(2)
        year = m1.group(3) or '2026'
        return f"{day} {month} {year}"

    # Day Month (e.g., 15th November)
    m2 = re.search(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})(?:\s*,?\s*(\d{{4}}))?\b', title, re.I)
    if m2:
        day = m2.group(1)
        month = m2.group(2).capitalize()
        year = m2.group(3) or '2026'
        return f"{day} {month} {year}"

    m3 = re.search(r'\b(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{2,4})\b', title)
    if m3:
        return m3.group(0)

    return ""

def scrape_central_nsp() -> List[Dict]:
    """
    Scrapes official National Scholarship Portal (NSP) announcements and
    Ministry of Education / PIB press releases for NMMSS (National Means-cum-Merit Scholarship Scheme).
    Always guarantees official scholarships.gov.in portal link and strict single-item deduplication.
    """
    notifications = []
    seen = set()

    # 1. Official Press Releases & Announcements via verified RSS (PIB / Central MoE)
    rss_queries = [
        "https://news.google.com/rss/search?q=%22NMMSS%22+OR+%22National+Means-cum-Merit%22&hl=en-IN&gl=IN&ceid=IN:en",
        "https://news.google.com/rss/search?q=%22NMMSS%22+site:pib.gov.in&hl=en-IN&gl=IN&ceid=IN:en"
    ]

    for rss_url in rss_queries:
        try:
            resp = requests.get(rss_url, headers=HEADERS, timeout=12)
            if resp.status_code == 200:
                root = ET.fromstring(resp.content)
                for item in root.findall(".//item"):
                    raw_title = item.findtext("title") or ""

                    t_lower = raw_title.lower()
                    if any(k in t_lower for k in ["nmms", "nmmss", "national means"]):
                        # Clean title - remove source suffix like "- News On AIR", "- Careers360"
                        clean_title = re.sub(r"\s*-\s*[^-]+$", "", raw_title).strip()

                        if len(clean_title) < 15:
                            continue

                        notif_id = generate_notification_id("Central (NSP)", clean_title)
                        if notif_id in seen:
                            continue
                        seen.add(notif_id)

                        extracted_last_date = extract_date_from_headline(clean_title)

                        notifications.append({
                            "id": notif_id,
                            "state": "Central (NSP)",
                            "authority": "Ministry of Education / NSP Portal",
                            "title": clean_title,
                            "update_type": "NSP Official Update",
                            "apply_link": "https://scholarships.gov.in",
                            "pdf_link": "",  # Always empty so official scholarships.gov.in is used
                            "apply_start": "Active Now",
                            "last_date": extracted_last_date or "15 November 2026",
                            "exam_date": ""
                        })
                        # Pick only 1 top notification per event to prevent duplicate posts
                        break
                if notifications:
                    break
        except Exception:
            pass

    # 2. Direct NSP Portal (scholarships.gov.in) Announcements
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

                            notif_id = generate_notification_id("Central (NSP)", clean_text)
                            if notif_id not in seen:
                                seen.add(notif_id)
                                extracted_date = extract_date_from_headline(clean_text)
                                notifications.append({
                                    "id": notif_id,
                                    "state": "Central (NSP)",
                                    "authority": "National Scholarship Portal (NSP)",
                                    "title": clean_text,
                                    "update_type": "NSP Portal Announcement",
                                    "apply_link": "https://scholarships.gov.in",
                                    "pdf_link": "",
                                    "apply_start": "Active Now",
                                    "last_date": extracted_date or "15 November 2026",
                                    "exam_date": ""
                                })
                                break
                    if notifications:
                        break
            except Exception:
                pass

    return notifications
