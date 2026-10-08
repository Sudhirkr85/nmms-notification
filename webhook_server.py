import os
import json
import time
import threading
import logging
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from dotenv import load_dotenv

load_dotenv()
from bot.payment import create_payment_link

logging.basicConfig(level=logging.INFO, format="%(asctime)s - [%(levelname)s] - %(message)s")
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
        r = requests.post(f"{API_URL}/sendMessage", json=payload, timeout=10)
        return r.json()
    except Exception as e:
        logger.error(f"Error sending reply: {e}")
        return None

def handle_user_command(message: dict):
    chat = message.get("chat", {})
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    user_name = chat.get("first_name", "Student")

    if text.startswith("/start") or text.startswith("/join") or text.startswith("/pay"):
        fee = os.getenv("SUBSCRIPTION_FEE_INR", "49")
        payment_url = create_payment_link(chat_id, user_name) or "https://rzp.io/rzp/8EXYbAq"

        welcome_text = f"""👋 <b>Namaste {user_name}!</b>

Welcome to <b>Sagar Coaching Centre NMMS Alert Service</b> 🎯

📢 <b>NMMS VIP Alert Channel Features:</b>
▪️ All 36 States Official NMMS Application Form Alerts
▪️ Admit Card, Exam Date & Center List
▪️ Result & Selected Students Merit List
▪️ Model Papers & Question Papers
▪️ Last Date Urgent Reminders

💰 <b>One-Time Access Fee:</b> <b>₹{fee} Only</b>
<i>(PhonePe / Google Pay / Paytm / UPI Supported)</i>

👇 <b>Channel me judne ke liye niche button par click karke payment karein:</b>"""

        buttons = {
            "inline_keyboard": [
                [{"text": f"💳 Pay ₹{fee} (PhonePe / GPay / Paytm)", "url": payment_url}],
                [{"text": "📞 Help / WhatsApp Support", "url": "https://wa.me/919110113671"}]
            ]
        }
        send_reply(chat_id, welcome_text, reply_markup=buttons)

def polling_worker():
    """
    Background worker that continuously listens for /start from users.
    No domain or webhook URL setup needed!
    """
    offset = None
    logger.info("Bot polling listener is active and running...")
    # Clean webhook if any so polling works flawlessly
    try:
        requests.get(f"{API_URL}/deleteWebhook", timeout=5)
    except Exception:
        pass

    while True:
        try:
            params = {"timeout": 25}
            if offset:
                params["offset"] = offset

            resp = requests.get(f"{API_URL}/getUpdates", params=params, timeout=30)
            data = resp.json()
            if data.get("ok"):
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update:
                        handle_user_command(update["message"])
        except Exception as e:
            time.sleep(2)

class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Sagar Coaching NMMS Bot is ACTIVE and RUNNING 24/7!")

def run_server(port=8080):
    # Start background bot listener
    t = threading.Thread(target=polling_worker, daemon=True)
    t.start()

    # Start healthcheck HTTP server for Render free tier
    server_address = ("", port)
    httpd = HTTPServer(server_address, HealthHandler)
    logger.info(f"Health server running on port {port}...")
    httpd.serve_forever()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    run_server(port)
