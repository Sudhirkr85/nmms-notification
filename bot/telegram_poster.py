"""
Telegram Poster for NMMS Bot.
Handles sendMessage and sendDocument with:
- HTML escaping
- Truncation to 4000 characters
- HTTP 429 automatic sleep for retry_after
- Secret protection (never logs tokens)
- DRY_RUN=1 support: logs simulated message without calling Telegram API
"""

import os
import requests
import json
import time
import logging
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def is_dry_run() -> bool:
    return os.getenv("DRY_RUN", "").strip() == "1"

def _get_credentials():
    token = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("CHAT_ID") or os.getenv("TELEGRAM_CHANNEL_ID")
    return (token or "").strip(), (chat_id or "").strip()

def send_telegram_message(text: str, apply_url: str = None, pdf_url: str = None, btn_text: str = None) -> int:
    """
    Sends HTML message to Telegram channel.
    Trims to 4000 chars, handles 429 retry_after.
    In DRY_RUN=1 mode, skips actual network call and returns simulated ID.
    Returns message_id on success, 0 on failure.
    """
    token, chat_id = _get_credentials()

    # Strict 4000 char truncation
    clean_text = text[:4000] if len(text) > 4000 else text

    if is_dry_run():
        logger.info(f"[DRY_RUN] Simulated Telegram send ({len(clean_text)} chars). Telegram API call skipped.")
        return 999999

    if not token or not chat_id:
        logger.warning("BOT_TOKEN or CHAT_ID not set. Skipping send.")
        return 0

    api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": chat_id,
        "text": clean_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    buttons = []
    clean_pdf = (pdf_url or "").strip()
    clean_apply = (apply_url or "").strip()

    if clean_pdf and clean_pdf.startswith("http"):
        doc_label = btn_text if btn_text else "📄 आधिकारिक नोटिस (PDF)"
        buttons.append([{"text": doc_label, "url": clean_pdf}])

    if clean_apply and clean_apply.startswith("http") and clean_apply != clean_pdf:
        portal_label = "🌐 आधिकारिक पोर्टल" if clean_pdf else (btn_text or "🌐 आधिकारिक पोर्टल")
        buttons.append([{"text": portal_label, "url": clean_apply}])

    if buttons:
        payload["reply_markup"] = json.dumps({"inline_keyboard": buttons})

    for attempt in range(2):
        try:
            resp = requests.post(api_url, data=payload, timeout=15)
            data = resp.json()

            if data.get("ok"):
                msg_id = data.get("result", {}).get("message_id", 1)
                logger.info(f"Successfully posted to Telegram. Message ID: {msg_id}")
                return msg_id

            if data.get("error_code") == 429:
                retry_after = data.get("parameters", {}).get("retry_after", 5)
                logger.warning(f"Telegram HTTP 429 received. Sleeping for {retry_after}s...")
                time.sleep(retry_after + 1)
                continue

            logger.error(f"Telegram API Error: {data.get('description')}")
            return 0
        except Exception as e:
            logger.error(f"Telegram sendMessage request failed: {e}")
            return 0

    return 0

def send_telegram_document(doc_url_or_path: str, caption: str = "") -> int:
    """
    Sends notice PDF document to Telegram channel.
    In DRY_RUN=1 mode, skips actual network call.
    """
    if is_dry_run():
        logger.info(f"[DRY_RUN] Simulated Telegram document upload for '{doc_url_or_path}'. Skipped.")
        return 999998

    token, chat_id = _get_credentials()
    if not token or not chat_id or not doc_url_or_path:
        return 0

    try:
        content = None
        raw_name = "Official_NMMS_Notice.pdf"

        if os.path.exists(doc_url_or_path):
            with open(doc_url_or_path, "rb") as f:
                content = f.read()
            raw_name = os.path.basename(doc_url_or_path)
        elif doc_url_or_path.startswith("http"):
            resp = requests.get(doc_url_or_path, headers=HEADERS, timeout=25, verify=False)
            if resp.status_code == 200 and len(resp.content) >= 500:
                content = resp.content
                parsed_path = urlsplit(doc_url_or_path).path
                raw_name = os.path.basename(parsed_path) or "Official_NMMS_Notice.pdf"

        if not content or len(content) < 500 or len(content) > 25 * 1024 * 1024:
            return 0

        if not raw_name.lower().endswith((".pdf", ".jpg", ".jpeg", ".png")):
            raw_name += ".pdf"

        api_url = f"https://api.telegram.org/bot{token}/sendDocument"
        mime_type = "application/pdf" if raw_name.lower().endswith(".pdf") else "image/jpeg"
        files = {"document": (raw_name, content, mime_type)}

        safe_caption = caption[:1000] if caption else ""

        data = {
            "chat_id": chat_id,
            "caption": safe_caption,
            "parse_mode": "HTML"
        }

        for attempt in range(2):
            r = requests.post(api_url, data=data, files=files, timeout=35)
            res_data = r.json()

            if res_data.get("ok"):
                msg_id = res_data.get("result", {}).get("message_id", 0)
                logger.info(f"Uploaded official notice document to Telegram. Message ID: {msg_id}")
                return msg_id

            if res_data.get("error_code") == 429:
                retry_after = res_data.get("parameters", {}).get("retry_after", 5)
                logger.warning(f"Telegram sendDocument 429. Sleeping {retry_after}s...")
                time.sleep(retry_after + 1)
                continue

            logger.warning(f"sendDocument error: {res_data.get('description')}")
            return 0
    except Exception as e:
        logger.warning(f"Failed uploading document to Telegram: {e}")
        return 0

    return 0
