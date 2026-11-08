"""
Urgent Deadline Reminders for NMMS Bot.
Sends short reminders 3 days and 1 day before last_date strictly in Hindi.
Uses reminder_3d_sent and reminder_1d_sent flags in MongoDB to ensure each is sent only once.
"""

import html
import logging
from data.storage import (
    get_active_notices_for_reminders,
    mark_reminder_sent,
    parse_date_to_ist,
    get_ist_today
)
from bot.formatter import get_hindi_state
from bot.telegram_poster import send_telegram_message

logger = logging.getLogger(__name__)

def check_and_send_reminders():
    """
    Scans active notices in MongoDB for deadlines approaching in 3 days or 1 day.
    """
    today = get_ist_today()
    notices = get_active_notices_for_reminders()

    for item in notices:
        content_hash = item.get("content_hash")
        state = item.get("state", "")
        state_hi = get_hindi_state(state)
        last_date_str = item.get("last_date", "")
        title = item.get("title", "")
        target_link = item.get("pdf_link") or item.get("official_url") or "https://scholarships.gov.in"

        target_date = parse_date_to_ist(last_date_str)
        if not target_date:
            continue

        days_left = (target_date - today).days

        # 3 Days Left Reminder
        if days_left == 3 and not item.get("reminder_3d_sent", False):
            msg = f"""⚠️ <b>अंतिम तिथि रिमाइंडर (केवल 3 दिन शेष!)</b> ⚠️

📍 <b>राज्य:</b> <b><u>{html.escape(state_hi)}</u></b>
📋 <b>सूचना:</b> <b>{html.escape(title)}</b>

⏰ <b>महत्वपूर्ण सूचना:</b>
आवेदन करने की अंतिम तिथि <b>{html.escape(last_date_str)}</b> है।
अंतिम दिनों में सर्वर धीमा हो सकता है, इसलिए तुरंत अपना आवेदन पूरा करें!

👉 <a href="{html.escape(target_link)}"><b>🔗 आधिकारिक पोर्टल पर आवेदन करें</b></a>

━━━━━━━━━━━━━━━━━━━━━
🎓 <b>सागर कोचिंग सेंटर, भगवानपुर</b>
📞 <b>Call / WhatsApp:</b> +91 91101 13671
"""
            msg_id = send_telegram_message(msg, apply_url=target_link)
            if msg_id:
                mark_reminder_sent(content_hash, "reminder_3d_sent")
                logger.info(f"Sent 3-day reminder for {state}: '{title}'")

        # 1 Day Left Reminder
        elif days_left == 1 and not item.get("reminder_1d_sent", False):
            msg = f"""🚨 <b>अंतिम अवसर रिमाइंडर (कल अंतिम तिथि है!)</b> 🚨

📍 <b>राज्य:</b> <b><u>{html.escape(state_hi)}</u></b>
📋 <b>सूचना:</b> <b>{html.escape(title)}</b>

⏰ <b>अति आवश्यक सूचना:</b>
कल (<b>{html.escape(last_date_str)}</b>) छात्रवृत्ति आवेदन की अंतिम तिथि है!
इसके बाद पोर्टल बंद हो जाएगा। यदि आपने अभी तक फॉर्म नहीं भरा है तो आज ही भरें।

👉 <a href="{html.escape(target_link)}"><b>⚡ सीधे पोर्टल पर आवेदन करें ⚡</b></a>

━━━━━━━━━━━━━━━━━━━━━
🎓 <b>सागर कोचिंग सेंटर, भगवानपुर</b>
📞 <b>Call / WhatsApp:</b> +91 91101 13671
"""
            msg_id = send_telegram_message(msg, apply_url=target_link)
            if msg_id:
                mark_reminder_sent(content_hash, "reminder_1d_sent")
                logger.info(f"Sent 1-day reminder for {state}: '{title}'")
