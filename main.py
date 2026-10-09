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

            # Deep AI Analysis with Groq (handles PDF & HTML reading)
            from scrapers.ai_reader import analyze_notice_with_groq
            target_url = notice.get("pdf_link") or notice.get("apply_link") or ""
            ai_data = analyze_notice_with_groq(state, notice["title"], target_url)

            final_title = ai_data.get("clean_title") or notice["title"]
            final_start = ai_data.get("start_date") or notice.get("apply_start", "")
            final_last = ai_data.get("last_date") or notice.get("last_date", "")
            final_exam = ai_data.get("exam_date") or notice.get("exam_date", "")
            final_update_type = ai_data.get("category") or notice["update_type"]
            ai_summary = ai_data.get("summary", "")

            # Format clean short Telegram message with Bilingual AI highlights
            message_text = format_nmms_notification(
                state=notice["state"],
                authority=notice["authority"],
                update_type=final_update_type,
                title=final_title,
                apply_start=final_start,
                last_date=final_last,
                exam_date=final_exam,
                apply_link=notice.get("apply_link", ""),
                pdf_link=notice.get("pdf_link", ""),
                highlights_en=ai_data.get("highlights_en", []),
                highlights_hi=ai_data.get("highlights_hi", []),
                summary_en=ai_data.get("summary_en", ""),
                summary_hi=ai_data.get("summary_hi", "")
            )

            # Category detection for smart button
            from bot.formatter import detect_notification_category
            category_info = detect_notification_category(final_title, final_update_type)

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
