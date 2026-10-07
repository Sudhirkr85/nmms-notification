import os
import time
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from config.states import STATE_CONFIG
from database.db import init_db, is_already_posted, record_posted, get_all_posted_count
from scrapers.portal_scraper import scrape_state_website
from bot.formatter import format_nmms_notification
from bot.telegram_poster import send_telegram_message

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)

def run_nmms_pipeline():
    logger.info("Initializing Database...")
    init_db()

    total_states = len(STATE_CONFIG)
    logger.info(f"Starting NMMS notification check across {total_states} state portals...")

    new_posts = 0

    for idx, (state, config) in enumerate(STATE_CONFIG.items(), start=1):
        logger.info(f"[{idx}/{total_states}] Checking: {state} ({config['authority']})...")
        
        found_notices = scrape_state_website(state, config)

        for notice in found_notices:
            notif_id = notice["id"]

            if is_already_posted(notif_id):
                logger.info(f"   -> Already posted earlier: '{notice['title'][:40]}...'")
                continue

            # New notification found!
            logger.info(f"   -> NEW NOTIFICATION FOUND: '{notice['title']}'")

            # Format the Telegram message
            message_text = format_nmms_notification(
                state=notice["state"],
                authority=notice["authority"],
                update_type=notice["update_type"],
                title=notice["title"],
                apply_start=notice.get("apply_start", "Active"),
                last_date=notice.get("last_date", "Refer official circular"),
                exam_date=notice.get("exam_date", "Refer official circular"),
                apply_link=notice.get("apply_link", ""),
                pdf_link=notice.get("pdf_link", "")
            )

            # Post to Telegram Channel
            posted = send_telegram_message(
                text=message_text,
                apply_url=notice.get("apply_link"),
                pdf_url=notice.get("pdf_link")
            )

            # Mark as posted in database so we never duplicate
            record_posted(
                notification_id=notif_id,
                state=notice["state"],
                title=notice["title"],
                apply_link=notice.get("apply_link", ""),
                pdf_link=notice.get("pdf_link", ""),
                last_date=notice.get("last_date", "")
            )
            new_posts += 1

        # Gentle delay between state site checks
        time.sleep(2)

    logger.info(f"Scan completed. Total new notifications posted: {new_posts}")
    logger.info(f"Total history records in database: {get_all_posted_count()}")

if __name__ == "__main__":
    run_nmms_pipeline()
