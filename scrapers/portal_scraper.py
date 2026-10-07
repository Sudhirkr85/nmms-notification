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
        for a_tag in soup.find_all("a", href=True):
            text = a_tag.get_text(strip=True)
            href = a_tag["href"].strip()

            # Match any NMMS keyword
            if any(k.lower() in text.lower() for k in keywords):
                if not href.startswith("http"):
                    href = requests.compat.urljoin(url, href)

                pdf_link = href if href.lower().endswith(".pdf") else ""
                apply_link = href if not href.lower().endswith(".pdf") else url

                # Try to extract dates from notice title/surrounding text
                dates = extract_dates_from_text(text)
                
                is_result_or_paper = any(w in text.lower() for w in ["result", "paper", "answer key", "admit card"])
                if is_result_or_paper:
                    update_type = "Result / Circular / Notice"
                    start_date = "Official Portal Notice"
                    last_date = "Refer Notice for details"
                    exam_date = "Check Circular"
                else:
                    update_type = "Online Form / Application"
                    start_date = dates[0] if len(dates) > 0 else "Active on Portal"
                    last_date = dates[1] if len(dates) > 1 else "Check Official Notice"
                    exam_date = dates[2] if len(dates) > 2 else "Check Official Notice"

                notif_id = generate_notification_id(state, text)
                notifications.append({
                    "id": notif_id,
                    "state": state,
                    "authority": config.get("authority", "State Education Board"),
                    "title": text,
                    "update_type": update_type,
                    "apply_link": apply_link,
                    "pdf_link": pdf_link,
                    "apply_start": start_date,
                    "last_date": last_date,
                    "exam_date": exam_date
                })
                if len(notifications) >= 2:
                    break

    except Exception:
        pass

    return notifications
