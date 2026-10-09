import os
import requests
import json
import logging

logger = logging.getLogger(__name__)

def send_telegram_message(text: str, apply_url: str = None, pdf_url: str = None, btn_text: str = None) -> bool:
    """
    Sends message to the Telegram channel using Telegram Bot API.
    Supports smart dynamic contextual button labels.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    if not token or not channel_id or token == "YOUR_BOT_TOKEN_HERE":
        logger.warning("TELEGRAM_BOT_TOKEN or TELEGRAM_CHANNEL_ID is not configured yet. Skipping message send.")
        try:
            print(f"[SIMULATED POST TO TELEGRAM]:\n{text}\n")
        except UnicodeEncodeError:
            print(f"[SIMULATED POST TO TELEGRAM (emojis masked for Windows terminal)]:\n{text.encode('ascii', 'replace').decode('ascii')}\n")
        return False

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
        doc_label = btn_text if btn_text else "📄 View / Download PDF"
        buttons.append({"text": doc_label, "url": clean_pdf})

    if clean_apply and clean_apply.startswith("http") and clean_apply != clean_pdf:
        portal_label = "🌐 Official Portal" if clean_pdf else (btn_text if btn_text else "🌐 View Official Portal")
        buttons.append({"text": portal_label, "url": clean_apply})

    for b in buttons:
        inline_keyboard.append([b])

    if inline_keyboard:
        payload["reply_markup"] = json.dumps({"inline_keyboard": inline_keyboard})

    try:
        response = requests.post(api_url, data=payload, timeout=15)
        res_data = response.json()
        if res_data.get("ok"):
            logger.info("Successfully posted to Telegram channel.")
            return True
        else:
            logger.error(f"Telegram API Error: {res_data}")
            return False
    except Exception as e:
        logger.error(f"Failed to post to Telegram: {e}")
        return False
