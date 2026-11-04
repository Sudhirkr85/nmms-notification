import os
import time
import logging
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from config.states import STATE_CONFIG
from data.storage import is_already_posted, record_posted, get_recent_notices_for_state, DATA_FILE
from scrapers.portal_scraper import scrape_state_website, is_junk_notice, is_outdated_archive, is_bare_scheme_name
from scrapers.central_scraper import scrape_central_nsp, extract_date_from_headline
from scrapers.ai_reader import analyze_notice_with_groq
from bot.formatter import format_nmms_notification, detect_notification_category
from bot.telegram_poster import send_telegram_message, send_telegram_document
from bot.reminder import check_and_send_reminders
from bot.cleaner import purge_bad_messages

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)

def process_and_post_notice(notice: dict) -> int:
    """
    Takes a candidate notice dictionary:
    1. Runs fast rule-based duplicate check
    2. Runs Groq LLaMA-3.3-70B AI Gatekeeper (checks student relevance & semantic deduplication against recent posts)
    3. If approved, formats bilingual message and posts to Telegram
    4. Automatically uploads the actual official PDF document directly to Telegram
    Returns message_id on success, 0 on skip/failure.
    """
    notif_id = notice["id"]
    if is_already_posted(notif_id, notice):
        logger.info(f"   -> SKIPPING DUPLICATE (Hash/ID match): '{notice.get('title')}' ({notice.get('state')})")
        return 0

    state = notice["state"]
    logger.info(f"   -> CANDIDATE NOTICE FOUND: '{notice['title']}' ({state})")

    # Fast preliminary gate
    target_url = notice.get("pdf_link") or notice.get("apply_link") or ""
    if is_junk_notice(notice["title"], target_url):
        logger.info(f"   -> [RULE REJECT] Junk / administrative keyword in candidate: '{notice['title']}' ({state})")
        return 0

    if is_outdated_archive(notice["title"], target_url):
        logger.info(f"   -> [RULE REJECT] Outdated archive candidate: '{notice['title']}' ({state})")
        return 0

    if not notice.get("pdf_link") and is_bare_scheme_name(notice["title"]):
        logger.info(f"   -> [RULE REJECT] Bare navigation button: '{notice['title']}' ({state})")
        return 0

    # Retrieve recent announcements for this state to feed into AI Semantic Deduplicator
    recent_posts = get_recent_notices_for_state(state, limit=5)

    # 100% Groq LLaMA-3.3-70B AI Quality Gatekeeper & Semantic Deduplicator
    ai_data = analyze_notice_with_groq(state, notice["title"], target_url, recent_posts=recent_posts)

    # GATE 1: AI Student-Actionable Check (Rejects DEO letters, question papers, attendance sheets)
    if not ai_data.get("is_student_actionable", True):
        logger.info(f"   -> [AI GATE REJECT] Not student-actionable: {ai_data.get('rejection_reason')} ('{notice['title']}')")
        return 0

    # GATE 2: AI Semantic Deduplication Check (Catches rephrased identical events)
    if ai_data.get("is_semantic_duplicate", False):
        logger.info(f"   -> [AI DUPLICATE REJECT] Semantic duplicate: {ai_data.get('rejection_reason')} ('{notice['title']}')")
        return 0

    final_title = ai_data.get("clean_title") or notice["title"]
    final_start = ai_data.get("start_date") or notice.get("apply_start", "")
    final_last = ai_data.get("last_date") or notice.get("last_date", "")
    final_exam = ai_data.get("exam_date") or notice.get("exam_date", "")
    final_update_type = ai_data.get("category") or notice["update_type"]

    cur_year = datetime.now().year
    if not final_last:
        final_last = extract_date_from_headline(final_title) or extract_date_from_headline(notice["title"])
    if not final_last and ("central" in state.lower() or "nsp" in state.lower()):
        final_last = f"15 November {cur_year}"

    # Category detection for action button
    category_info = detect_notification_category(final_title, final_update_type)
    cat_type = category_info.get("type", "")

    # For Central / NSP, always guarantee official portal apply link
    if "central" in state.lower() or "nsp" in state.lower():
        apply_url = "https://scholarships.gov.in"
        pdf_url = ""
    else:
        apply_url = notice.get("apply_link")
        pdf_url = notice.get("pdf_link")

    # Final safety: Vague circulars without PDF or dates are dropped
    if cat_type == "CIRCULAR" and not pdf_url and not final_last and not final_exam:
        logger.info(f"   -> [GATE REJECT] Empty circular with no dates or document: '{final_title}' ({state})")
        return 0

    # Double-check storage duplicate after AI title/date refinement
    enriched_notice = {
        **notice,
        "title": final_title,
        "last_date": final_last,
        "pdf_link": pdf_url or "",
        "apply_link": apply_url or ""
    }
    if is_already_posted(notif_id, enriched_notice):
        logger.info(f"   -> SKIPPING DUPLICATE (Storage verified): '{final_title}' ({state})")
        return 0

    # Format clean Telegram message with Bilingual AI highlights (Notice-Specific Facts)
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
        ai_summary_point = ""
        if ai_data.get("highlights_hi"):
            ai_summary_point = str(ai_data["highlights_hi"][0]).strip()
        elif ai_data.get("clean_title"):
            ai_summary_point = str(ai_data["clean_title"]).strip()

        record_posted(
            notification_id=notif_id,
            state=notice["state"],
            title=notice["title"],
            apply_link=apply_url or "",
            pdf_link=pdf_url or "",
            last_date=final_last or notice.get("last_date", ""),
            message_id=msg_id,
            ai_summary=ai_summary_point,
            category=final_update_type
        )
        logger.info(f"   -> [POSTED SUCCESS] Message ID {msg_id} sent for {state}: '{final_title}'")

        # Exclusive Paid Group Feature: Attach the actual official PDF document file right in Telegram
        if pdf_url and pdf_url.startswith("http"):
            doc_caption = f"📄 <b>Official Circular PDF:</b> <i>{final_title}</i> ({state})"
            send_telegram_document(pdf_url, caption=doc_caption)

        return msg_id
    return 0

def run_nmms_pipeline():
    # 0. Automatically purge any previously posted bad / duplicate messages from Telegram channel
    try:
        purge_bad_messages(DATA_FILE)
    except Exception as e:
        logger.warning(f"Purge error: {e}")

    logger.info("Checking urgent last-date reminders...")
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

        time.sleep(2)

    logger.info(f"Scan completed. Total new notifications posted: {new_posts}")

if __name__ == "__main__":
    run_nmms_pipeline()
