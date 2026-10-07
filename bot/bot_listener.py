import os
import requests
import time
import json
import logging
from dotenv import load_dotenv

load_dotenv()
from bot.payment import create_payment_link, create_single_use_invite_link

logger = logging.getLogger(__name__)

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
API_URL = f"https://api.telegram.org/bot{TOKEN}"

def send_reply(chat_id: int, text: str, reply_markup: dict = None):
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML"
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    try:
        requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
    except Exception as e:
        logger.error(f"Error sending reply: {e}")

def handle_user_message(message: dict):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    user_name = chat.get("first_name", "Student")

    if text.startswith("/start") or text.startswith("/join") or text.startswith("/pay"):
        fee = os.getenv("SUBSCRIPTION_FEE_INR", "49")
        payment_url = create_payment_link(chat_id, user_name)

        welcome_text = f"""👋 <b>Namaste {user_name}!</b>

Welcome to <b>Sagar Coaching Centre NMMS Alert Service</b> 🎯

📢 <b>NMMS VIP Alert Channel Features:</b>
▪️ All 36 States Official NMMS Application Form Alerts
▪️ Admit Card, Result, Merit List & Model Papers
▪️ Last Date Urgent Reminders (Never miss ₹48,000 scholarship!)
▪️ Sagar Sir's YouTube NMMS Preparation Support

💰 <b>Access Fee:</b> <b>₹{fee} Only</b>
<i>(UPI, PhonePe, Google Pay, Paytm, Cards supported)</i>

👇 <b>Channel me judne ke liye niche button par click karke payment karein:</b>"""

        buttons = {
            "inline_keyboard": [
                [{"text": f"💳 Pay ₹{fee} (PhonePe / GPay / Paytm)", "url": payment_url}],
                [{"text": "📞 Help / WhatsApp Support", "url": "https://wa.me/919110113671"}]
            ]
        }
        send_reply(chat_id, welcome_text, reply_markup=buttons)

def poll_bot():
    """
    Lightweight polling loop to answer user /start or /join messages
    """
    offset = None
    logger.info("Bot user payment listener started...")
    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset

            resp = requests.get(f"{API_URL}/getUpdates", params=params, timeout=35)
            data = resp.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update:
                        handle_user_message(update["message"])
        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    poll_bot()
