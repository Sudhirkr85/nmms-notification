import os
import time
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from config.states import STATE_CONFIG
from data.storage import is_already_posted, record_posted
from scrapers.portal_scraper import scrape_state_website
from bot.formatter import format_nmms_notification
from bot.telegram_poster import send_telegram_message
from bot.reminder import check_and_send_reminders

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)

def run_nmms_pipeline():
    logger.info("Checking urgent last-date reminders first...")
    try:
        check_and_send_reminders()
    except Exception as e:
        logger.warning(f"Reminder check error: {e}")

    total_states = len(STATE_CONFIG)
    logger.info(f"Starting NMMS notification check across {total_states} state portals...")

    new_posts = 0

    for idx, (state, config) in enumerate(STATE_CONFIG.items(), start=1):
        logger.info(f"[{idx}/{total_states}] Checking: {state} ({config['authority']})...")
        
        found_notices = scrape_state_website(state, config)

        for notice in found_notices:
            notif_id = notice["id"]

            if is_already_posted(notif_id):
                continue

            # New notification found!
            logger.info(f"   -> NEW NOTIFICATION FOUND: '{notice['title']}'")

            # Format clean short Telegram message
            message_text = format_nmms_notification(
                state=notice["state"],
                authority=notice["authority"],
                update_type=notice["update_type"],
                title=notice["title"],
                apply_start=notice.get("apply_start", "Active"),
                last_date=notice.get("last_date", "Refer official notice"),
                exam_date=notice.get("exam_date", "Refer official notice"),
                apply_link=notice.get("apply_link", ""),
                pdf_link=notice.get("pdf_link", "")
            )

            # Category detection for smart button
            from bot.formatter import detect_notification_category
            category_info = detect_notification_category(notice["title"])

            # Post to Telegram Channel
            posted = send_telegram_message(
                text=message_text,
                apply_url=notice.get("apply_link"),
                pdf_url=notice.get("pdf_link"),
                btn_text=category_info.get("action_btn")
            )

            # Mark as posted in JSON history
            record_posted(
                notification_id=notif_id,
                state=notice["state"],
                title=notice["title"],
                apply_link=notice.get("apply_link", ""),
                pdf_link=notice.get("pdf_link", ""),
                last_date=notice.get("last_date", "")
            )
            new_posts += 1

        # Polite delay between sites
        time.sleep(2)

    logger.info(f"Scan completed. Total new notifications posted: {new_posts}")

if __name__ == "__main__":
    run_nmms_pipeline()
