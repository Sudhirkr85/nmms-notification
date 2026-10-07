import json
import os
from datetime import datetime

DATA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "history.json")

def _ensure_file():
    os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
    if not os.path.exists(DATA_FILE):
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            json.dump({"posted": {}, "reminders_sent": {}}, f, indent=2)

def is_already_posted(notification_id: str) -> bool:
    _ensure_file()
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return notification_id in data.get("posted", {})
    except Exception:
        return False

def record_posted(notification_id: str, state: str, title: str, apply_link: str, pdf_link: str, last_date: str = ""):
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
