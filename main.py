"""
NMMS Auto Scraper & Telegram Poster
Main pipeline executing:
1. Environment secret verification at startup (names only, never values)
2. Fail-closed MongoDB Atlas connection & ping (exits non-zero if unavailable in production)
3. Central (NSP) check
4. State SCERT portals check with ThreadPoolExecutor(max_workers=4)
5. Deadline reminders check
6. Strict fail-closed AI gatekeeper (llama-3.1-8b + llama-3.3-70b) with semaphore limit (max 2 concurrent)
7. Normalized verbatim evidence quote verification
8. DRY_RUN=1 mode support (full scrapers/Groq, no Telegram send, no Mongo write, summary report)
9. One-line logging format: state | event_type | decision | reason | IST time
"""

import os
import sys
import re
import html
import logging
import threading
from datetime import date
from typing import Optional, Dict, List
from collections import defaultdict
from urllib.parse import urlsplit
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

from config.states import STATE_CONFIG, OFFICIAL_EXTRA_DOMAINS, TARGET_STATES_AND_CENTRAL
from data.storage import (
    init_mongo_storage,
    compute_content_hash,
    compute_event_key,
    parse_date_to_ist,
    get_ist_today,
    is_extension_valid,
    is_content_hash_seen,
    find_recent,
    try_insert,
    mark_posted,
    mark_failed,
    mark_rejected,
    get_ist_now,
    is_dry_run,
    is_test_mode
)
from scrapers.portal_scraper import (
    scrape_state_website,
    is_junk_notice,
    is_outdated_archive,
    is_bare_scheme_name,
    get_portal_status_map,
    get_portal_diagnostics
)
from scrapers.central_scraper import scrape_central_nsp, get_central_portal_status
from scrapers.ai_reader import (
    analyze_notice_with_groq_pipeline,
    reset_evidence_mismatch_count,
    get_evidence_mismatch_count,
    preflight_check_groq_models,
    get_stage1_models,
    get_stage2_models,
    extract_content_from_source
)
from bot.formatter import format_hindi_nmms_notification
from bot.telegram_poster import send_telegram_message, send_telegram_document
from bot.reminder import check_and_send_reminders

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - [%(levelname)s] - %(message)s"
)
logger = logging.getLogger(__name__)

# Execution metrics tracker
_stats_lock = threading.Lock()
pipeline_stats = {
    "fetched": 0,
    "accepted": 0,
    "rejected": {},
    "skipped_duplicate": 0,
    "ai_errors": 0
}

# Coverage Tracking strictly across target states (10 states + CENTRAL)
ALL_STATES_IN_ORDER = list(TARGET_STATES_AND_CENTRAL)

_coverage_lock = threading.Lock()
coverage_data: Dict[str, Dict[str, any]] = {
    st: {
        "portal_status": "OK",
        "portal_items": 0,
        "news_items": 0,
        "dropped_pollution": 0,
        "dropped_keyword": 0,
        "dropped_freshness": 0,
        "dropped_link": 0,
        "dropped_ai": 0,
        "accepted": 0
    }
    for st in ALL_STATES_IN_ORDER
}

def record_coverage(state: str, field: str, count: int = 1):
    safe_st = state if state in coverage_data else "CENTRAL"
    with _coverage_lock:
        if field in coverage_data[safe_st]:
            coverage_data[safe_st][field] += count

# News candidates buffer for multi-publisher corroboration
_news_candidates_lock = threading.Lock()
_news_candidates_by_event = defaultdict(list)

def record_stat(category: str, detail: str = ""):
    with _stats_lock:
        if category in ["fetched", "accepted", "skipped_duplicate", "ai_errors"]:
            pipeline_stats[category] += 1
        elif category == "rejected":
            reason_key = detail or "Unspecified"
            pipeline_stats["rejected"][reason_key] = pipeline_stats["rejected"].get(reason_key, 0) + 1

def log_notice_decision(state: str, event_type: str, decision: str, reason: str):
    """
    Standardized one-line log per notice:
    state | event_type | decision | reason | IST time
    Never prints secrets.
    """
    ist_time = get_ist_now().strftime("%Y-%m-%d %H:%M:%S IST")
    safe_state = (state or "UNKNOWN").replace("|", "/")
    safe_event = (event_type or "N/A").replace("|", "/")
    safe_decision = (decision or "UNKNOWN").replace("|", "/")
    safe_reason = (reason or "").replace("|", "/")
    logger.info(f"{safe_state} | {safe_event} | {safe_decision} | {safe_reason} | {ist_time}")

def verify_startup_configuration():
    """
    Verifies presence of required environment variables and model preflight at startup.
    Logs names only (NEVER values). Exits with code 1 if any is missing in production.
    """
    dry_run = is_dry_run()
    test_mode = is_test_mode()

    groq_key = os.getenv("GROQ_API_KEY", "").strip()
    bot_token = os.getenv("BOT_TOKEN", "").strip() or os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.getenv("CHAT_ID", "").strip() or os.getenv("TELEGRAM_CHANNEL_ID", "").strip()
    mongo_uri = os.getenv("MONGO_URI", "").strip()

    stage1_models = get_stage1_models()
    stage2_models = get_stage2_models()

    logger.info("--------------------------------------------------")
    logger.info("STARTUP ENVIRONMENT CONFIGURATION CHECK:")
    logger.info(f"   GROQ_API_KEY                    : {'[PRESENT]' if groq_key else '[MISSING]'}")
    logger.info(f"   GROQ_MODEL_STAGE1               : {stage1_models[0]} (Fallbacks: {stage1_models[1:] or 'None'})")
    logger.info(f"   GROQ_MODEL_STAGE2               : {stage2_models[0]} (Fallbacks: {stage2_models[1:] or 'None'})")
    logger.info(f"   BOT_TOKEN / TELEGRAM_BOT_TOKEN  : {'[PRESENT]' if bot_token else '[MISSING]'}")
    logger.info(f"   CHAT_ID / TELEGRAM_CHANNEL_ID   : {'[PRESENT]' if chat_id else '[MISSING]'}")
    logger.info(f"   MONGO_URI                       : {'[PRESENT]' if mongo_uri else '[MISSING]'}")
    logger.info(f"   DRY_RUN MODE                    : {'[ACTIVE]' if dry_run else '[INACTIVE]'}")
    logger.info(f"   TEST MODE                       : {'[ACTIVE]' if test_mode else '[INACTIVE]'}")
    logger.info("--------------------------------------------------")

    if not test_mode:
        if not groq_key:
            logger.error("[STARTUP_CONFIG_ERROR] GROQ_API_KEY is missing. Exiting.")
            sys.exit(1)
        # Cheap preflight check on configured models (both in production and DRY_RUN)
        preflight_check_groq_models()

    if not dry_run and not test_mode:
        missing = []
        if not bot_token:
            missing.append("BOT_TOKEN (or TELEGRAM_BOT_TOKEN)")
        if not chat_id:
            missing.append("CHAT_ID (or TELEGRAM_CHANNEL_ID)")
        if not mongo_uri:
            missing.append("MONGO_URI")

        if missing:
            logger.error(f"[STARTUP_CONFIG_ERROR] Missing required secrets: {', '.join(missing)}. Exiting.")
            sys.exit(1)

def is_strictly_official_domain(url: str) -> bool:
    """
    Checks if a URL belongs strictly to an official domain:
    Ends with .gov.in, .nic.in, or .ac.in, is scholarships.gov.in,
    or matches a domain in OFFICIAL_EXTRA_DOMAINS whitelist.
    Reject otherwise (e.g. entdata.co.in must NOT pass unless added to config).
    """
    if not url:
        return False
    try:
        parts = urlsplit(url)
        netloc = parts.netloc.lower().split(":")[0].strip()
        if not netloc:
            return False
        if netloc == "scholarships.gov.in":
            return True
        if netloc.endswith(".gov.in") or netloc.endswith(".nic.in") or netloc.endswith(".ac.in"):
            return True
        for extra in OFFICIAL_EXTRA_DOMAINS:
            if netloc == extra or netloc.endswith("." + extra):
                return True
        return False
    except Exception:
        return False

def extract_official_link(notice: dict, target_url: str, raw_content: str) -> Optional[str]:
    """
    Extracts a verified official link from notice links or page content.
    Does NOT guess from state config if not present in the notice text/page.
    """
    candidates = []
    # 1. Target URL if scraped directly from an official portal
    if target_url and is_strictly_official_domain(target_url):
        candidates.append(target_url)
    # 2. apply_link
    apply_link = notice.get("apply_link", "")
    if apply_link and is_strictly_official_domain(apply_link):
        candidates.append(apply_link)
    # 3. pdf_link
    pdf_link = notice.get("pdf_link", "")
    if pdf_link and pdf_link.startswith("http") and is_strictly_official_domain(pdf_link):
        candidates.append(pdf_link)
    # 4. Links found in document content
    text_corpus = f"{target_url} {raw_content}"
    for l in re.findall(r'https?://[^\s"\'<>)]+', text_corpus):
        if is_strictly_official_domain(l):
            candidates.append(l)

    # 5. Mention of scholarships.gov.in in notice text or title
    if "scholarships.gov.in" in text_corpus.lower() or "scholarships.gov.in" in (notice.get("title") or "").lower():
        candidates.append("https://scholarships.gov.in")

    return candidates[0] if candidates else None

def is_central_event(state: str, title: str, text: str, url: str, ai_result: dict = None) -> bool:
    """
    Determines if a notice is about the national NMMSS scholarship / NSP.
    If yes, state must be set to 'CENTRAL' regardless of which state's search found it.
    """
    combined = f"{state} {title} {text} {url}".lower()
    if ai_result:
        ai_state = (ai_result.get("state") or "").lower()
        if "central" in ai_state or "nsp" in ai_state:
            return True

    if "scholarships.gov.in" in combined:
        return True
    if "ministry of education" in combined or "education ministry" in combined or "शिक्षा मंत्रालय" in combined:
        return True
    if "national means" in combined and any(k in combined for k in ["central", "nsp", "all india", "national level"]):
        return True
    return False

def is_state_pollution(target_state: str, title: str, text: str, url: str, is_fallback: bool = False) -> tuple[bool, str]:
    """
    Filters search fallback notices for other states in code before AI call.
    Title/text must mention target state or be CENTRAL.
    Only applies to search fallbacks, not direct official portal items.
    """
    if not is_fallback:
        return False, ""

    if target_state.upper() == "CENTRAL" or is_central_event(target_state, title, text, url):
        return False, ""

    cfg = STATE_CONFIG.get(target_state, {})
    target_lower = target_state.lower()
    keywords = [target_lower]
    if cfg.get("hindi_name"):
        keywords.append(cfg["hindi_name"].lower())
    if cfg.get("alias"):
        keywords.append(cfg["alias"].lower())

    combined = f"{title} {text}".lower()
    mentions_target = any(k in combined for k in keywords if k)
    if mentions_target:
        return False, ""

    # Check if other states are explicitly mentioned in title or text
    other_states = [
        "telangana", "kerala", "andhra", "tamil nadu", "karnataka",
        "maharashtra", "gujarat", "odisha", "west bengal", "assam",
        "punjab", "bihar", "rajasthan", "haryana", "delhi", "jharkhand",
        "chhattisgarh", "himachal", "uttarakhand", "uttar pradesh"
    ]
    for os_name in other_states:
        if os_name != target_lower and os_name in combined:
            return True, f"State pollution: Notice is for {os_name.title()}, not {target_state}"

    return True, f"State pollution: Target state {target_state} not mentioned in notice"

def verify_notice_freshness(
    notice: dict,
    ai_result: dict,
    event_type: str,
    parsed_dates_list: List[date]
) -> tuple[bool, str]:
    """
    Code-level freshness verification (after AI, before posting):
    1. Reject notices whose session/year in title, URL or text is older than current cycle (e.g. 2024-25, 2025-26)
       unless the notice clearly states a future 2026-27 date with evidence_quote.
    2. Reject if any extracted deadline/event date is before today (IST).
    3. For news items, require a verifiable publish date within the last 7 days.
    4. For ANSWER_KEY, RESULT, ADMIT_CARD: require verifiable date within last 14 days or future.
    5. For deadline/schedule events: require at least one verified date with full year.
    """
    today = get_ist_today()
    title = (notice.get("title") or "").lower()
    url = (notice.get("source_url") or notice.get("publisher_url") or notice.get("pdf_link") or notice.get("apply_link") or "").lower()
    combined_text = f"{title} {url} {notice.get('content_context', '')}".lower()
    is_news = bool(notice.get("is_fallback") or notice.get("origin") == "news")

    # 1. News items require a verifiable publish date within the last 7 days
    if is_news:
        pub_dt = notice.get("pub_date_obj")
        if not pub_dt and notice.get("pub_date"):
            pub_dt = parse_date_to_ist(notice.get("pub_date"))
        if not pub_dt:
            return False, "News publish date is missing (cannot verify freshness)"
        days_diff = (today - pub_dt).days
        if days_diff < 0 or days_diff > 7:
            return False, f"News publish date ({pub_dt}) is older than 7 days ({days_diff} days old)"

    # 2. Reject if any extracted deadline/event date is before today (IST)
    for dt in parsed_dates_list:
        if dt < today:
            return False, f"Extracted event date ({dt.strftime('%d %B %Y')}) is before today (IST)"

    # 3. Reject notices whose session/year in title, URL or text is older than current cycle
    old_cycle_match = re.search(r'\b(202[0-5]|2025-26|2024-25|2023-24|2022-23|2021-22)\b', combined_text)
    if old_cycle_match:
        has_future_cycle_date = any(
            dt >= today and dt.year >= 2026 for dt in parsed_dates_list
        ) and ("2026-27" in combined_text or "2026" in combined_text)
        if not has_future_cycle_date:
            return False, f"Outdated academic cycle / past session ({old_cycle_match.group(1)}) detected without future 2026-27 date"

    # 4. For ANSWER_KEY, RESULT, ADMIT_CARD: require verifiable date within last 14 days or future
    if event_type in ["ANSWER_KEY", "RESULT", "ADMIT_CARD"]:
        verifiable_dates = list(parsed_dates_list)
        if notice.get("pub_date_obj"):
            verifiable_dates.append(notice["pub_date_obj"])
        fresh_date_found = any(0 <= (today - dt).days <= 14 or dt >= today for dt in verifiable_dates)
        if not fresh_date_found:
            return False, "no verifiable fresh date"

    # 5. For deadline/schedule events: require at least one verified date with full year
    if event_type in ["FORM_START", "LAST_DATE", "EXTENSION", "EXAM_DATE"]:
        if not parsed_dates_list:
            return False, "No verifiable event date with year found in notice or publish date"

    return True, ""

def process_and_post_notice(notice: dict) -> int:
    """
    Processes a candidate notice through the fail-closed pipeline:
    1. Content hash duplicate check
    2. Rule filters (junk, archive, bare button, state pollution)
    3. AI Two-Stage Gatekeeper (fail-closed, max 1 concurrent call, throttle)
    4. Code-level date safety check (IST today, freshness, session)
    5. Official link enforcement (.gov.in/.nic.in/.ac.in or scholarships.gov.in)
    6. Event-based deduplication key (CENTRAL unified key)
    7. MongoDB PENDING insertion -> Telegram send -> POSTED mark
    Returns telegram message_id on success, 0 on skip/failure.
    """
    record_stat("fetched")
    state = notice.get("state", "Unknown")
    title = notice.get("title", "").strip()
    target_url = notice.get("pdf_link") or notice.get("apply_link") or notice.get("source_url") or ""
    content_hash = notice.get("content_hash") or compute_content_hash(state, title, target_url)

    # Track item origin for coverage
    origin = notice.get("origin")
    if not origin:
        origin = "news" if (notice.get("is_fallback") or "news.google" in target_url) else "portal"

    if origin == "portal":
        record_coverage(state, "portal_items")
    else:
        record_coverage(state, "news_items")

    # 1. Check if already processed (POSTED or REJECTED)
    if is_content_hash_seen(content_hash):
        record_stat("skipped_duplicate")
        log_notice_decision(state, "N/A", "SKIP", f"Already processed: '{title[:40]}'")
        return 0

    # 2. Fast Rule Filters
    if is_junk_notice(title, target_url):
        mark_rejected(content_hash, state, title, "Junk/administrative keyword detected", "JUNK")
        record_stat("rejected", "Junk/administrative keyword detected")
        record_coverage(state, "dropped_pollution")
        log_notice_decision(state, "JUNK", "REJECT", "Junk/administrative keyword detected")
        return 0

    if is_outdated_archive(title, target_url):
        mark_rejected(content_hash, state, title, "Outdated archive announcement", "ARCHIVE")
        record_stat("rejected", "Outdated archive announcement")
        record_coverage(state, "dropped_freshness")
        log_notice_decision(state, "ARCHIVE", "REJECT", "Outdated archive announcement")
        return 0

    if not notice.get("pdf_link") and is_bare_scheme_name(title):
        mark_rejected(content_hash, state, title, "Bare navigation button without content", "BARE")
        record_stat("rejected", "Bare navigation button without content")
        record_coverage(state, "dropped_pollution")
        log_notice_decision(state, "BARE", "REJECT", "Bare navigation button without content")
        return 0

    # 2b. State Pollution Filter (before Groq call)
    raw_content = (notice.get("content_context") or "").strip()
    fetch_url = notice.get("publisher_url") or target_url

    # Follow Bare Portal Links: If content is short/empty, fetch linked page or PDF first
    if (not raw_content or len(raw_content) < 80) and fetch_url:
        fetched_text = extract_content_from_source(fetch_url, max_chars=4000)
        if fetched_text:
            raw_content = fetched_text
            notice["content_context"] = fetched_text

    if not raw_content and not title:
        empty_reason = "Bare portal link with no readable content on linked page or PDF"
        mark_rejected(content_hash, state, title, empty_reason, "EMPTY")
        record_stat("rejected", empty_reason)
        record_coverage(state, "dropped_link")
        log_notice_decision(state, "EMPTY", "REJECT", empty_reason)
        return 0

    is_fallback = bool(notice.get("is_fallback", False))
    polluted, poll_reason = is_state_pollution(state, title, raw_content, target_url, is_fallback=is_fallback)
    if polluted:
        mark_rejected(content_hash, state, title, poll_reason, "POLLUTION")
        record_stat("rejected", poll_reason)
        record_coverage(state, "dropped_pollution")
        log_notice_decision(state, "N/A", "REJECT", poll_reason)
        return 0

    # 3. Retrieve recent history for this state (max 15 entries / last 30 days)
    recent_history = find_recent(state, max_entries=15, max_days=30)

    # 4. Fail-Closed AI Gatekeeper
    ai_result = analyze_notice_with_groq_pipeline(
        state=state,
        title=title,
        notice_url=target_url,
        raw_content=raw_content,
        history_entries=recent_history
    )

    if ai_result.get("is_error"):
        record_stat("ai_errors")
        record_coverage(state, "dropped_ai")
        log_notice_decision(state, "N/A", "ERROR", f"AI fail-closed: {ai_result.get('reason')}")
        return 0

    event_type = ai_result.get("event_type", "LAST_DATE")
    decision = ai_result.get("decision", "REJECT")
    reason = ai_result.get("reason", "")

    if decision != "ACCEPT":
        mark_rejected(content_hash, state, title, reason, event_type)
        record_stat("rejected", reason)
        if "Code pre-filter" in reason:
            record_coverage(state, "dropped_keyword")
        else:
            record_coverage(state, "dropped_ai")
        log_notice_decision(state, event_type, "REJECT", reason)
        return 0

    # 5. Extract and parse dates with full year enforcement
    dates = ai_result.get("dates", [])
    notice_pub_year = notice.get("pub_date_year")
    if not notice_pub_year and notice.get("pub_date_obj"):
        notice_pub_year = notice["pub_date_obj"].year

    parsed_dates_list: List[date] = []
    normalized_dates: List[Dict[str, str]] = []

    for d in dates:
        lbl = str(d.get("label", "Date")).strip()
        val = str(d.get("value", "")).strip()
        quote = str(d.get("evidence_quote", "")).strip()

        # Parse with fallback_year ONLY if year is absent in val/quote
        dt_obj = parse_date_to_ist(val, fallback_year=notice_pub_year)
        if not dt_obj and quote:
            dt_obj = parse_date_to_ist(quote, fallback_year=notice_pub_year)

        if dt_obj:
            parsed_dates_list.append(dt_obj)
            normalized_dates.append({
                "label": lbl,
                "value": dt_obj.strftime("%d %B %Y"),  # Format with full year: e.g. 15 November 2026
                "evidence_quote": quote
            })

    # The single canonical parsed date object used for dedup key, expiry check, and message
    canonical_date_obj: Optional[date] = parsed_dates_list[0] if parsed_dates_list else None
    canonical_iso_date = canonical_date_obj.strftime("%Y-%m-%d") if canonical_date_obj else ""

    # 6. Central Event Normalization
    if is_central_event(state, title, raw_content, target_url, ai_result):
        state = "CENTRAL"

    # 7. Code-level Freshness & Cycle Verification
    is_fresh, fresh_reason = verify_notice_freshness(notice, ai_result, event_type, parsed_dates_list)
    if not is_fresh:
        mark_rejected(content_hash, state, title, fresh_reason, event_type)
        record_stat("rejected", fresh_reason)
        record_coverage(state, "dropped_freshness")
        log_notice_decision(state, event_type, "REJECT", fresh_reason)
        return 0

    # 8. Extension check (using canonical date)
    if event_type == "EXTENSION" and canonical_date_obj:
        if not is_extension_valid(state, canonical_iso_date):
            mark_rejected(content_hash, state, title, f"Extension date ({canonical_iso_date}) not later than previous", event_type)
            record_stat("rejected", "Extension date not later than previous deadline")
            record_coverage(state, "dropped_freshness")
            log_notice_decision(state, "EXTENSION", "REJECT", "Extension date not later than previous deadline")
            return 0

    # 9. News-Only Rule Tightening vs Official Link Enforcement
    is_news = bool(notice.get("is_fallback") or origin == "news")
    if is_news:
        # Every post whose source is news must go through 2-different-publisher corroboration
        event_key = compute_event_key(state, event_type, canonical_iso_date)
        candidate_item = {
            "notice": notice,
            "ai_result": ai_result,
            "state": state,
            "event_type": event_type,
            "title": title,
            "canonical_date_obj": canonical_date_obj,
            "canonical_iso_date": canonical_iso_date,
            "dates": normalized_dates,
            "content_hash": content_hash,
            "target_url": target_url,
            "publisher_url": notice.get("publisher_url") or target_url,
            "publisher_domain": notice.get("publisher_domain") or urlsplit(target_url).netloc.lower().split(":")[0].strip()
        }
        with _news_candidates_lock:
            _news_candidates_by_event[event_key].append(candidate_item)
        logger.info(f"Buffered news-only notice for corroboration: '{title[:45]}' (Domain: {candidate_item['publisher_domain']})")
        return 0

    # 10. Official Link Enforcement for Direct Portal Items
    official_link = extract_official_link(notice, target_url, raw_content)
    if not official_link:
        link_reject_reason = f"Missing official .gov.in/.nic.in/.ac.in link (found: {target_url[:60]})"
        mark_rejected(content_hash, state, title, link_reject_reason, event_type)
        record_stat("rejected", link_reject_reason)
        record_coverage(state, "dropped_link")
        log_notice_decision(state, event_type, "REJECT", link_reject_reason)
        return 0

    # 11. PDF Link Strict Validation (Never attach non-official or self-generated PDFs)
    pdf_url = notice.get("pdf_link", "")
    if pdf_url:
        if not pdf_url.startswith("http") or not is_strictly_official_domain(pdf_url):
            pdf_url = ""

    # 12. Event-based Deduplication Key (Unified CENTRAL key for national events)
    event_key = compute_event_key(state, event_type, canonical_iso_date)

    # 13. Insert candidate into MongoDB with status PENDING
    candidate_doc = {
        "key": event_key,
        "content_hash": content_hash,
        "state": state,
        "event_type": event_type,
        "title": title,
        "summary_hi": ai_result.get("summary_hi", ""),
        "summary_en": ai_result.get("summary_en", ""),
        "last_date": canonical_iso_date,
        "event_date": canonical_iso_date,
        "dates": normalized_dates,
        "source_url": target_url,
        "official_url": official_link
    }

    inserted = try_insert(candidate_doc)
    if not inserted:
        record_stat("skipped_duplicate")
        log_notice_decision(state, event_type, "SKIP", "Duplicate event key or already in progress")
        return 0

    # 14. Format Hindi message (AI concise title, HTML formatter)
    title_hi = ai_result.get("title_hi", "")
    msg_text = format_hindi_nmms_notification(
        state=state,
        event_type=event_type,
        title=title,
        summary_hi=ai_result.get("summary_hi", ""),
        dates=normalized_dates,
        last_date=canonical_iso_date,
        exam_date=canonical_iso_date,
        official_url=official_link,
        pdf_url=pdf_url,
        title_hi=title_hi,
        is_news_corroborated=False
    )

    # 15. Post to Telegram (Simulated in DRY_RUN)
    msg_id = send_telegram_message(
        text=msg_text,
        apply_url=official_link,
        pdf_url=pdf_url
    )

    if msg_id:
        mark_posted(event_key, content_hash, msg_id)
        record_stat("accepted")
        record_coverage(state, "accepted")
        log_notice_decision(state, event_type, "ACCEPT", f"Posted to Telegram (Msg ID: {msg_id})")

        if pdf_url and is_strictly_official_domain(pdf_url):
            doc_caption = f"📄 <b>आधिकारिक सूचना (PDF):</b> <i>{html.escape(title)}</i> ({html.escape(state)})"
            send_telegram_document(pdf_url, caption=doc_caption)

        return msg_id
    else:
        mark_failed(event_key, content_hash, "Telegram API post failed")
        log_notice_decision(state, event_type, "FAILED", "Telegram message send failed")
        return 0

def process_corroborated_news_events() -> int:
    """
    Evaluates buffered news-only events under the Corroboration Rule:
    A news-sourced event without an official link in its text may be posted only if BOTH hold:
    (a) at least 2 DIFFERENT publisher domains report the same event_type and the same date, and
    (b) the event maps to a known official portal in config (CENTRAL -> https://scholarships.gov.in),
        used only as the button link.
    Such posts include: "यह सूचना समाचार रिपोर्टों पर आधारित है, कृपया आधिकारिक पोर्टल पर पुष्टि करें।"
    Single-source news-only events remain rejected.
    """
    accepted_count = 0
    with _news_candidates_lock:
        events_to_process = list(_news_candidates_by_event.items())
        _news_candidates_by_event.clear()

    for event_key, group in events_to_process:
        rep = group[0]
        state = rep["state"]
        event_type = rep["event_type"]
        title = rep["title"]
        ai_result = rep["ai_result"]
        dates = rep["dates"]
        canonical_iso_date = rep.get("canonical_iso_date", "")
        final_last = canonical_iso_date
        final_exam = canonical_iso_date

        # Gather distinct publisher domains
        domains = set()
        resolved_urls = []
        for c in group:
            dom = c.get("publisher_domain")
            if dom:
                domains.add(dom.lower())
            if c.get("publisher_url"):
                resolved_urls.append(c["publisher_url"])

        if len(domains) >= 2:
            # Check official portal in config
            if state == "CENTRAL":
                official_portal = "https://scholarships.gov.in"
            else:
                official_portal = STATE_CONFIG.get(state, {}).get("official_url", "")

            if official_portal and is_strictly_official_domain(official_portal):
                candidate_doc = {
                    "key": event_key,
                    "content_hash": rep["content_hash"],
                    "state": state,
                    "event_type": event_type,
                    "title": title,
                    "summary_hi": ai_result.get("summary_hi", ""),
                    "summary_en": ai_result.get("summary_en", ""),
                    "last_date": final_last,
                    "event_date": final_exam,
                    "dates": dates,
                    "source_url": rep["target_url"],
                    "official_url": official_portal,
                    "resolved_publisher_urls": resolved_urls,
                    "publisher_domains": list(domains),
                    "is_news_corroborated": True
                }

                inserted = try_insert(candidate_doc)
                if not inserted:
                    record_stat("skipped_duplicate")
                    log_notice_decision(state, event_type, "SKIP", f"Duplicate event key across {len(domains)} news publishers")
                    continue

                msg_text = format_hindi_nmms_notification(
                    state=state,
                    event_type=event_type,
                    title=title,
                    summary_hi=ai_result.get("summary_hi", ""),
                    dates=dates,
                    last_date=final_last,
                    exam_date=final_exam,
                    official_url=official_portal,
                    pdf_url="",
                    title_hi=ai_result.get("title_hi", ""),
                    is_news_corroborated=True
                )

                msg_id = send_telegram_message(
                    text=msg_text,
                    apply_url=official_portal,
                    pdf_url=""
                )

                if msg_id:
                    mark_posted(event_key, rep["content_hash"], msg_id)
                    record_stat("accepted")
                    record_coverage(state, "accepted")
                    accepted_count += 1
                    log_notice_decision(state, event_type, "ACCEPT", f"Corroborated by {len(domains)} publisher domains ({', '.join(sorted(domains))})")
                else:
                    mark_failed(event_key, rep["content_hash"], "Telegram post failed")
                    log_notice_decision(state, event_type, "FAILED", "Telegram send failed for corroborated news")
            else:
                reason = "News-only event has no valid official portal in config"
                for c in group:
                    mark_rejected(c["content_hash"], state, c["title"], reason, event_type)
                record_stat("rejected", reason)
                record_coverage(state, "dropped_link")
                log_notice_decision(state, event_type, "REJECT", reason)
        else:
            found_str = ", ".join(sorted(domains)) if domains else "none"
            reason = f"News-only event rejected: requires corroboration from at least 2 different publisher domains (found {len(domains)}: {found_str})"
            for c in group:
                mark_rejected(c["content_hash"], state, c["title"], reason, event_type)
            record_stat("rejected", reason)
            record_coverage(state, "dropped_link")
            log_notice_decision(state, event_type, "REJECT", reason)

    return accepted_count

def print_coverage_report():
    """Prints target states + CENTRAL coverage report table with full portal diagnostics."""
    coverage_data["CENTRAL"]["portal_status"] = get_central_portal_status()
    portal_diag_map = get_portal_diagnostics()
    for st, status in get_portal_status_map().items():
        if st in coverage_data:
            coverage_data[st]["portal_status"] = status

    sep = "=" * 135
    header_sep = "-" * 135
    logger.info(sep)
    logger.info("COVERAGE REPORT (TARGET STATES + CENTRAL):")
    logger.info(header_sep)
    fmt = "{:<16} | {:<12} | {:<9} | {:<12} | {:<28} | {:<6} | {:<5} | {:<8}"
    logger.info(fmt.format("State", "Portal Status", "Size (KB)", "Links(Tot/NM)", "Portal Diagnostic Summary", "Portal", "News", "Accepted"))
    logger.info(header_sep)

    for st in ALL_STATES_IN_ORDER:
        d = coverage_data[st]
        diag = portal_diag_map.get(st, {})
        size_str = f"{diag.get('size_kb', 0.0):.1f}" if diag else "-"
        links_str = f"{diag.get('total_links', 0)}/{diag.get('nmms_links', 0)}" if diag else "-"
        diag_summary = diag.get("summary", "OK" if st == "CENTRAL" else "No diag")[:28]

        logger.info(fmt.format(
            st,
            d["portal_status"][:12],
            size_str,
            links_str,
            diag_summary,
            d["portal_items"],
            d["news_items"],
            d["accepted"]
        ))
    logger.info(sep)

    # Detailed diagnostic logging for state portals that returned 0 items
    logger.info("STATE PORTAL ZERO-ITEM DIAGNOSTICS:")
    for st in ALL_STATES_IN_ORDER:
        if st == "CENTRAL":
            continue
        d = coverage_data[st]
        if d["portal_items"] == 0:
            diag = portal_diag_map.get(st, {})
            logger.info(
                f"   * {st:<16}: HTTP={diag.get('http_code', 'N/A')}, Size={diag.get('size_kb', 0)}KB, "
                f"Blocked={diag.get('is_blocked', False)}, JS_Rendered={diag.get('is_js_rendered', False)}, "
                f"Links={diag.get('total_links', 0)} (NMMS matches={diag.get('nmms_links', 0)}) | Detail: {diag.get('summary', 'No items')}"
            )
    logger.info(sep)

def check_single_state(state: str, config: dict) -> int:
    """Scrapes and processes notifications for a single state inside its own try/except."""
    posted_count = 0
    try:
        notices = scrape_state_website(state, config)
        for notice in notices:
            msg_id = process_and_post_notice(notice)
            if msg_id:
                posted_count += 1
                if posted_count >= 2:
                    break
    except Exception as e:
        logger.error(f"Error checking state {state}: {e}")
    return posted_count

def run_nmms_pipeline():
    """Main execution entry point."""
    reset_evidence_mismatch_count()

    # Step 1: Verify environment variables
    verify_startup_configuration()

    # Step 2: Initialize & Ping MongoDB Atlas (fail-closed in production)
    init_mongo_storage()

    logger.info("Starting NMMS Scraper & Telegram Poster pipeline...")

    # Step 3: Urgent deadline reminders
    try:
        check_and_send_reminders()
    except Exception as e:
        logger.warning(f"Reminder check error: {e}")

    # Step 4: Central / NSP Portal Check
    try:
        central_notices = scrape_central_nsp()
        for c_notice in central_notices:
            msg_id = process_and_post_notice(c_notice)
            if msg_id:
                break
    except Exception as e:
        logger.error(f"Central NSP check error: {e}")

    # Step 5: Parallel state scraping (ThreadPoolExecutor max_workers=4)
    logger.info(f"Checking {len(STATE_CONFIG)} states in parallel (max_workers=4)...")
    with ThreadPoolExecutor(max_workers=4) as executor:
        future_to_state = {
            executor.submit(check_single_state, state, config): state
            for state, config in STATE_CONFIG.items()
        }

        for future in as_completed(future_to_state):
            state = future_to_state[future]
            try:
                future.result()
            except Exception as exc:
                logger.error(f"State {state} generated an exception: {exc}")

    # Step 6: Process Corroborated News-Only Events
    process_corroborated_news_events()

    # Step 7: Print coverage report
    print_coverage_report()

    # Step 8: Print pipeline execution summary
    mismatch_count = get_evidence_mismatch_count()
    logger.info("==================================================")
    logger.info("NMMS PIPELINE EXECUTION SUMMARY:")
    logger.info(f"   Total Fetched        : {pipeline_stats['fetched']}")
    logger.info(f"   Total Accepted/Posted: {pipeline_stats['accepted']}")
    logger.info(f"   Skipped (Duplicates) : {pipeline_stats['skipped_duplicate']}")
    logger.info(f"   AI Errors (Fail-Safe): {pipeline_stats['ai_errors']}")
    logger.info(f"   Evidence Mismatches  : {mismatch_count}")
    logger.info("   Rejections by Reason :")
    if pipeline_stats["rejected"]:
        for r_reason, r_count in pipeline_stats["rejected"].items():
            logger.info(f"      - {r_reason}: {r_count}")
    else:
        logger.info("      (None)")
    logger.info("==================================================")

if __name__ == "__main__":
    run_nmms_pipeline()
