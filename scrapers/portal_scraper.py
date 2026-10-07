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

                notif_id = generate_notification_id(state, text)
                notifications.append({
                    "id": notif_id,
                    "state": state,
                    "authority": config.get("authority", "State Education Board"),
                    "title": text,
                    "update_type": "New Circular / Application Update",
                    "apply_link": apply_link,
                    "pdf_link": pdf_link,
                    "apply_start": "Active on Portal",
                    "last_date": "Check notification for last date",
                    "exam_date": "Announced in Circular"
                })
                # Max 2 notices per state to avoid noise
                if len(notifications) >= 2:
                    break

    except Exception:
        # State site might be temporarily down; proceed safely
        pass

    return notifications
