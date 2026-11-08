import os
import requests
import json
import logging
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def send_telegram_message(text: str, apply_url: str = None, pdf_url: str = None, btn_text: str = None) -> int:
    """
    Sends message to the Telegram channel/group using Telegram Bot API.
    Supports smart dynamic contextual button labels (PDFs, Images, and Web Portals).
    Returns message_id on success, 0 on failure.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    if not token or not channel_id or token == "YOUR_BOT_TOKEN_HERE":
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID is not configured yet. Skipping message send.")
        try:
            print(f"[SIMULATED POST TO TELEGRAM]:\n{text}\n")
        except UnicodeEncodeError:
            print(f"[SIMULATED POST TO TELEGRAM (emojis masked for Windows terminal)]:\n{text.encode('ascii', 'replace').decode('ascii')}\n")
        return 0

    api_url = f"https://api.telegram.org/bot{token}/sendMessage"

    payload = {
        "chat_id": channel_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }

    # Smart contextual action buttons
    inline_keyboard = []
    clean_pdf = (pdf_url or "").strip()
    clean_apply = (apply_url or "").strip()

    buttons = []
    if clean_pdf and clean_pdf.startswith("http"):
        is_image = any(clean_pdf.lower().endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"])
        default_doc_label = "🖼️ View Notice Image" if is_image else "📄 View / Download PDF"
        doc_label = btn_text if btn_text else default_doc_label
        buttons.append({"text": doc_label, "url": clean_pdf})

    if clean_apply and clean_apply.startswith("http") and clean_apply != clean_pdf:
        portal_label = btn_text if (btn_text and not clean_pdf) else "🌐 Official Portal"
        buttons.append({"text": portal_label, "url": clean_apply})

    for b in buttons:
        inline_keyboard.append([b])

    if inline_keyboard:
        payload["reply_markup"] = json.dumps({"inline_keyboard": inline_keyboard})

    try:
        response = requests.post(api_url, data=payload, timeout=15)
        res_data = response.json()
        if res_data.get("ok"):
            msg_id = res_data.get("result", {}).get("message_id", 1)
            logger.info(f"Successfully posted to Telegram channel. Message ID: {msg_id}")
            return msg_id
        else:
            logger.error(f"Telegram API Error: {res_data}")
            return 0
    except Exception as e:
        logger.error(f"Failed to post to Telegram: {e}")
        return 0

def send_telegram_document(doc_url: str, caption: str = "") -> int:
    """
    Sends the official notice (PDF or Image) directly to the Telegram group/channel.
    Supports BOTH web URLs (http/https) and local file paths on disk.
    Subscribers get the actual official circular directly in Telegram.
    Returns message_id on success, 0 on failure.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    if not token or not channel_id or not doc_url:
        return 0

    try:
        content = None
        raw_name = "Official_NMMS_Notice.pdf"

        # Support both local files and remote URLs
        if os.path.exists(doc_url):
            with open(doc_url, "rb") as f:
                content = f.read()
            raw_name = os.path.basename(doc_url)
        elif doc_url.startswith("http"):
            resp = requests.get(doc_url, headers=HEADERS, timeout=25, verify=False)
            if resp.status_code == 200 and len(resp.content) >= 500:
                content = resp.content
                parsed_path = urlsplit(doc_url).path
                raw_name = os.path.basename(parsed_path) or "Official_NMMS_Notice.pdf"

        if not content or len(content) < 500:
            return 0

        # Don't upload massive files (> 25MB)
        if len(content) > 25 * 1024 * 1024:
            return 0

        if not raw_name.lower().endswith((".pdf", ".jpg", ".jpeg", ".png")):
            raw_name += ".pdf"

        api_url = f"https://api.telegram.org/bot{token}/sendDocument"
        mime_type = "application/pdf" if raw_name.lower().endswith(".pdf") else "image/jpeg"
        files = {
            "document": (raw_name, content, mime_type)
        }
        data = {
            "chat_id": channel_id,
            "caption": caption[:1000] if caption else "",
            "parse_mode": "HTML"
        }
        r = requests.post(api_url, data=data, files=files, timeout=35)
        res_data = r.json()
        if res_data.get("ok"):
            msg_id = res_data.get("result", {}).get("message_id", 0)
            logger.info(f"Direct official document uploaded to Telegram. Message ID: {msg_id}")
            return msg_id
        else:
            logger.warning(f"sendDocument error: {res_data}")
            return 0
    except Exception as e:
        logger.warning(f"Failed uploading document to Telegram: {e}")
        return 0

def delete_telegram_message(message_id: int) -> bool:
    """
    Deletes a message from the Telegram channel using Telegram Bot API.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    if not token or not channel_id or not message_id:
        return False

    api_url = f"https://api.telegram.org/bot{token}/deleteMessage"
    try:
        resp = requests.post(api_url, json={"chat_id": channel_id, "message_id": message_id}, timeout=10)
        res_data = resp.json()
        if res_data.get("ok"):
            logger.info(f"Successfully deleted Telegram message ID: {message_id}")
            return True
        else:
            logger.debug(f"Could not delete message ID {message_id}: {res_data}")
            return False
    except Exception as e:
        logger.warning(f"Error deleting message {message_id}: {e}")
        return False
