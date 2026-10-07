import os
import requests
import razorpay
import logging
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

RAZORPAY_KEY = os.getenv("RAZORPAY_KEY_ID")
RAZORPAY_SECRET = os.getenv("RAZORPAY_KEY_SECRET")
FEE_INR = int(os.getenv("SUBSCRIPTION_FEE_INR", "49"))

client = None
if RAZORPAY_KEY and RAZORPAY_SECRET and RAZORPAY_KEY.startswith("rzp_"):
    client = razorpay.Client(auth=(RAZORPAY_KEY, RAZORPAY_SECRET))

def create_payment_link(user_id: int, user_name: str = "Student") -> str:
    """
    Creates a Razorpay Payment Link for Rs 1/49.
    Upon successful payment, Razorpay automatically redirects student into Telegram channel!
    """
    if not client:
        raise Exception("Razorpay is not configured")

    # Generate fresh 1-time channel invite link for this paying student
    invite_link = create_single_use_invite_link() or f"https://t.me/+HygnvMiBpgVkMmE9"

    payload = {
        "amount": FEE_INR * 100,  # in paise
        "currency": "INR",
        "accept_partial": False,
        "description": f"NMMS Premium Alert Channel Access - {user_name}",
        "notes": {
            "telegram_user_id": str(user_id),
            "service": "NMMS_TELEGRAM_ALERTS"
        },
        "callback_url": invite_link,
        "callback_method": "get"
    }

    try:
        payment_link = client.payment_link.create(payload)
        return payment_link.get("short_url")
    except Exception as e:
        logger.error(f"Error creating Razorpay link: {e}")
        return None

def create_single_use_invite_link() -> str:
    """
    Creates a 1-time single-use invite link for the private Telegram channel.
    Once used by the paying student, nobody else can use it.
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    channel_id = os.getenv("TELEGRAM_CHANNEL_ID")

    url = f"https://api.telegram.org/bot{token}/createChatInviteLink"
    payload = {
        "chat_id": channel_id,
        "member_limit": 1,  # Strict 1-time use only
        "name": "Paid Student 1-Time Access"
    }

    try:
        resp = requests.post(url, json=payload, timeout=10)
        data = resp.json()
        if data.get("ok"):
            return data["result"]["invite_link"]
    except Exception as e:
        logger.error(f"Failed to generate Telegram invite link: {e}")
    return None
