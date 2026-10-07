import re
from datetime import datetime, date
from data.storage import get_active_notifications, is_reminder_sent, record_reminder_sent
from bot.telegram_poster import send_telegram_message

def parse_date(date_str: str):
    """
    Tries to parse typical Indian date strings like '05 December 2026', '05/12/2026', etc.
    """
    if not date_str:
        return None
    
    # Common format attempts
    formats = [
        "%d %B %Y",
        "%d %b %Y",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%Y-%m-%d"
    ]
    for fmt in formats:
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None

def check_and_send_reminders():
    """
    Checks active notifications and sends an urgent reminder if deadline is close.
    """
    today = date.today()
    notifications = get_active_notifications()

    for notif_id, item in notifications.items():
        state = item.get("state", "")
        last_date_str = item.get("last_date", "")
        title = item.get("title", "")
        target_link = item.get("pdf_link") or item.get("apply_link") or "https://scholarships.gov.in"

        target_date = parse_date(last_date_str)
        if not target_date:
            continue

        days_left = (target_date - today).days

        # Trigger for 3 days left or today
        if days_left in [3, 1, 0]:
            reminder_key = f"{notif_id}_{days_left}d"
            if is_reminder_sent(reminder_key):
                continue

            if days_left == 0:
                urgency_badge = "🔴 <b>TODAY IS THE LAST DATE!</b> 🔴"
                time_note = "Today is your final chance to apply!"
            elif days_left == 1:
                urgency_badge = "🚨 <b>ONLY 1 DAY LEFT!</b> 🚨"
                time_note = "Application portal closes tomorrow!"
            else:
                urgency_badge = "⚠️ <b>ONLY 3 DAYS LEFT!</b> ⚠️"
                time_note = f"Application closes on {last_date_str}!"

            msg = f"""{urgency_badge}

📍 <b>State:</b> <b><u>{state.upper()}</u></b>
📝 <b>Notice:</b> <b>{title}</b>

⏰ <b>URGENT REMINDER:</b>
{time_note}
Please apply immediately before servers slow down!

👉 <a href="{target_link}"><b>🔗 Click Here to Apply / View Notice</b></a>

━━━━━━━━━━━━━━━━━━━━━
🎓 <b>Sagar Coaching Centre, Bhagwanpur</b>
▶️ <b>YouTube:</b> <a href="https://www.youtube.com/@sagarcoachingcentrebhagwanpur">Sagar Coaching Centre Bhagwanpur</a>
📞 <b>Call / WhatsApp:</b> +91 91101 13671
"""
            send_telegram_message(msg, apply_url=target_link)
            record_reminder_sent(reminder_key)
