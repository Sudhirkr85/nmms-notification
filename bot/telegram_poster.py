import os
import requests
import json
import logging

logger = logging.getLogger(__name__)

def send_telegram_message(text: str, apply_url: str = None, pdf_url: str = None) -> bool:
    """
    Sends message to the Telegram channel using Telegram Bot API.
    Supports inline action buttons for apply and PDF.
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

    # Only 1 single, clean, prominent button for viewing the notification
    inline_keyboard = []
    target_link = pdf_url if (pdf_url and pdf_url.startswith("http")) else apply_url
    if target_link and target_link.startswith("http"):
        btn_label = "📄 View / Download Notice" if target_link.lower().endswith(".pdf") else "🔗 View Official Notice"
        inline_keyboard.append([{"text": btn_label, "url": target_link}])

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
