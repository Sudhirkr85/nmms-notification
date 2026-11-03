import os
import time
import logging
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from config.states import STATE_CONFIG
from data.storage import is_already_posted, record_posted
from scrapers.portal_scraper import scrape_state_website
from scrapers.central_scraper import scrape_central_nsp, extract_date_from_headline
from scrapers.ai_reader import analyze_notice_with_groq
from bot.formatter import format_nmms_notification, detect_notification_category
from bot.telegram_poster import send_telegram_message
from bot.reminder import check_and_send_reminders

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)

def process_and_post_notice(notice: dict) -> int:
    """
    Takes a notice dictionary, analyzes with AI, formats message, and sends to Telegram.
    Returns message_id on success, 0 on skip/failure.
    """
    notif_id = notice["id"]
    if is_already_posted(notif_id, notice):
        logger.info(f"   -> SKIPPING DUPLICATE: '{notice.get('title')}' ({notice.get('state')})")
        return 0

    state = notice["state"]
    logger.info(f"   -> NEW NOTIFICATION FOUND: '{notice['title']}' ({state})")

    # Deep AI Analysis with Groq (handles PDF & HTML reading)
    target_url = notice.get("pdf_link") or notice.get("apply_link") or ""
    ai_data = analyze_notice_with_groq(state, notice["title"], target_url)

    final_title = ai_data.get("clean_title") or notice["title"]
    final_start = ai_data.get("start_date") or notice.get("apply_start", "")
    final_last = ai_data.get("last_date") or notice.get("last_date", "")
    final_exam = ai_data.get("exam_date") or notice.get("exam_date", "")
    final_update_type = ai_data.get("category") or notice["update_type"]

    # Guarantee last_date from headline if AI missed it
    if not final_last:
        final_last = extract_date_from_headline(final_title) or extract_date_from_headline(notice["title"])
    if not final_last and ("central" in state.lower() or "nsp" in state.lower()):
        final_last = "15 November 2026"

    # Category detection for smart button
    category_info = detect_notification_category(final_title, final_update_type)

    # For Central / NSP, always guarantee official portal apply link
    if "central" in state.lower() or "nsp" in state.lower():
        apply_url = "https://scholarships.gov.in"
        pdf_url = ""
    else:
        apply_url = notice.get("apply_link")
        pdf_url = notice.get("pdf_link")

    # Double-check duplicate after AI refinement (e.g. if title or date was normalized)
    enriched_notice = {
        **notice,
        "title": final_title,
        "last_date": final_last,
        "pdf_link": pdf_url or "",
        "apply_link": apply_url or ""
    }
    if is_already_posted(notif_id, enriched_notice):
        logger.info(f"   -> SKIPPING DUPLICATE (Post-AI verified): '{final_title}' ({state})")
        return 0

    # Format clean short Telegram message with Bilingual AI highlights
    message_text = format_nmms_notification(
        state=notice["state"],
        authority=notice["authority"],
        update_type=final_update_type,
        title=final_title,
        apply_start=final_start,
        last_date=final_last,
        exam_date=final_exam,
        apply_link=apply_url or "https://scholarships.gov.in",
        pdf_link=pdf_url or "",
        highlights_en=ai_data.get("highlights_en", []),
        highlights_hi=ai_data.get("highlights_hi", []),
        summary_en=ai_data.get("summary_en", ""),
        summary_hi=ai_data.get("summary_hi", "")
    )

    # Post to Telegram Channel
    msg_id = send_telegram_message(
        text=message_text,
        apply_url=apply_url,
        pdf_url=pdf_url,
        btn_text=category_info.get("action_btn")
    )

    if msg_id:
        record_posted(
            notification_id=notif_id,
            state=notice["state"],
            title=notice["title"],
            apply_link=apply_url or "",
            pdf_link=pdf_url or "",
            last_date=final_last or notice.get("last_date", ""),
            message_id=msg_id
        )
        return msg_id
    return 0

def run_nmms_pipeline():
    logger.info("Checking urgent last-date reminders first...")
    try:
        check_and_send_reminders()
    except Exception as e:
        logger.warning(f"Reminder check error: {e}")

    new_posts = 0

    # 1. Check Central / National Scholarship Portal (NSP) & Ministry of Education first
    logger.info("Checking Central / National Scholarship Portal (NSP) & Ministry updates...")
    try:
        central_notices = scrape_central_nsp()
        for c_notice in central_notices:
            msg_id = process_and_post_notice(c_notice)
            if msg_id:
                new_posts += 1
                break  # Strictly only 1 Central notification per event
    except Exception as e:
        logger.warning(f"Central NSP check error: {e}")

    # 2. Check all State SCERT portals
    total_states = len(STATE_CONFIG)
    logger.info(f"Starting NMMS notification check across {total_states} state portals...")

    for idx, (state, config) in enumerate(STATE_CONFIG.items(), start=1):
        logger.info(f"[{idx}/{total_states}] Checking: {state} ({config['authority']})...")

        found_notices = scrape_state_website(state, config)
        state_new_posts = 0

        for notice in found_notices:
            msg_id = process_and_post_notice(notice)
            if msg_id:
                new_posts += 1
                state_new_posts += 1
                if state_new_posts >= 2:
                    break

        # Polite delay between sites
        time.sleep(2)

    logger.info(f"Scan completed. Total new notifications posted: {new_posts}")

if __name__ == "__main__":
    run_nmms_pipeline()
