"""
Fail-Closed AI Gatekeeper for NMMS Telegram Bot.
Two-Stage Pipeline with Groq:
- Stage 1: Fast instruct model for relevance filtering (Default: openai/gpt-oss-20b)
- Stage 2: High-accuracy instruct model for extraction & verification (Default: openai/gpt-oss-120b)

Rate Limit & Evidence Verification:
- Configurable models & fallbacks via GROQ_MODEL_STAGE1, GROQ_MODEL_STAGE2, and fallback lists.
- Exponential backoff on 429 & 5xx/timeouts; immediate fallback/abort on 404/model_not_found.
- Shared threading.Semaphore(2) for max 2 concurrent Groq calls across threads.
- Normalized evidence quote matching (NFKC, zero-width removal, Devanagari digits to ASCII, collapsed whitespace).
- Tracks and logs evidence mismatch rejections.
"""

import os
import sys
import io
import json
import logging
import re
import time
import requests
import unicodedata
import threading
from typing import Dict, Any, List, Optional
from bs4 import BeautifulSoup
from pypdf import PdfReader
from data.storage import get_ist_now, get_ist_today

logger = logging.getLogger(__name__)

# Shared limiter: max 1 concurrent Groq call across threads to stay well under TPM limits
_groq_semaphore = threading.Semaphore(1)
_last_groq_call_time = 0.0
_groq_throttle_lock = threading.Lock()

def _throttle_groq_call(min_interval: float = 1.5):
    """Token-per-minute throttle shared across threads."""
    global _last_groq_call_time
    with _groq_throttle_lock:
        now = time.time()
        elapsed = now - _last_groq_call_time
        if elapsed < min_interval:
            time.sleep(min_interval - elapsed)
        _last_groq_call_time = time.time()

# Counter for evidence mismatch rejections
_evidence_mismatch_lock = threading.Lock()
_evidence_mismatch_count = 0

def reset_evidence_mismatch_count():
    global _evidence_mismatch_count
    with _evidence_mismatch_lock:
        _evidence_mismatch_count = 0

def get_evidence_mismatch_count() -> int:
    with _evidence_mismatch_lock:
        return _evidence_mismatch_count

def increment_evidence_mismatch_count():
    global _evidence_mismatch_count
    with _evidence_mismatch_lock:
        _evidence_mismatch_count += 1

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

VALID_EVENT_TYPES = {
    "FORM_START",
    "LAST_DATE",
    "EXTENSION",
    "CORRECTION",
    "EXAM_DATE",
    "ADMIT_CARD",
    "ANSWER_KEY",
    "RESULT",
    "NSP_APPLY",
    "NSP_OTHER"
}

DEVANAGARI_DIGITS = {
    '०': '0', '१': '1', '२': '2', '३': '3', '४': '4',
    '५': '5', '६': '6', '७': '7', '८': '8', '९': '9'
}

def normalize_text_for_evidence_matching(text: str) -> str:
    """
    Normalizes text for robust verbatim evidence quote matching:
    1. Unicode NFKC normalization
    2. Remove zero-width characters (ZWSP, ZWNJ, ZWJ, BOM, non-breaking space)
    3. Convert Devanagari digits to ASCII digits
    4. Collapse all whitespace into single spaces
    5. Lowercase
    """
    if not text:
        return ""
    # Unicode NFKC
    norm = unicodedata.normalize("NFKC", str(text))
    # Remove zero-width & non-breaking spaces
    norm = re.sub(r"[\u200B-\u200D\uFEFF\u00A0]", " ", norm)
    # Convert Devanagari digits
    for d_char, a_char in DEVANAGARI_DIGITS.items():
        norm = norm.replace(d_char, a_char)
    # Collapse whitespace and lowercase
    return re.sub(r"\s+", " ", norm).strip().lower()

def extract_content_from_source(url_or_path: str, max_chars: int = 6000) -> str:
    """Extracts text from local PDF, remote PDF, or HTML webpage up to max_chars."""
    if not url_or_path:
        return ""

    if os.path.exists(url_or_path):
        try:
            if url_or_path.lower().endswith(".pdf"):
                reader = PdfReader(url_or_path)
                text = ""
                for page in reader.pages[:8]:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
                return text[:max_chars].strip()
        except Exception as e:
            logger.warning(f"Error reading local file {url_or_path}: {e}")
            return ""

    if not url_or_path.startswith("http"):
        return ""

    try:
        resp = requests.get(url_or_path, headers=HEADERS, timeout=15, verify=False)
        if resp.status_code != 200:
            return ""

        content_type = resp.headers.get("Content-Type", "").lower()
        url_lower = url_or_path.lower()

        if any(url_lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]) or "image" in content_type:
            return ""

        if "pdf" in content_type or url_lower.endswith(".pdf"):
            pdf_file = io.BytesIO(resp.content)
            reader = PdfReader(pdf_file)
            text = ""
            for page in reader.pages[:8]:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            return text[:max_chars].strip()

        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        clean_text = " ".join(soup.stripped_strings)
        return clean_text[:max_chars].strip()

    except Exception as e:
        logger.warning(f"Could not extract content from {url_or_path}: {e}")
        return ""

def _get_groq_client():
    """Initializes Groq client wrapped in try/except. Returns None on failure."""
    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from groq import Groq
        return Groq(api_key=api_key)
    except Exception as e:
        logger.error(f"[AI_ERROR] Groq client initialization failed: {e}")
        return None

# Configurable model identifiers & fallbacks
DEFAULT_STAGE1_MODEL = "openai/gpt-oss-20b"
DEFAULT_STAGE2_MODEL = "openai/gpt-oss-120b"
DEFAULT_STAGE1_FALLBACKS = ["qwen/qwen3.8-27b"]
DEFAULT_STAGE2_FALLBACKS = ["openai/gpt-oss-20b", "qwen/qwen3.8-27b"]

def get_stage1_models() -> List[str]:
    primary = os.getenv("GROQ_MODEL_STAGE1", "").strip() or DEFAULT_STAGE1_MODEL
    fallbacks_env = os.getenv("GROQ_MODEL_STAGE1_FALLBACKS", "").strip()
    fallbacks = [f.strip() for f in fallbacks_env.split(",") if f.strip()] if fallbacks_env else DEFAULT_STAGE1_FALLBACKS
    models = [primary]
    for fb in fallbacks:
        if fb not in models:
            models.append(fb)
    return models

def get_stage2_models() -> List[str]:
    primary = os.getenv("GROQ_MODEL_STAGE2", "").strip() or DEFAULT_STAGE2_MODEL
    fallbacks_env = os.getenv("GROQ_MODEL_STAGE2_FALLBACKS", "").strip()
    fallbacks = [f.strip() for f in fallbacks_env.split(",") if f.strip()] if fallbacks_env else DEFAULT_STAGE2_FALLBACKS
    models = [primary]
    for fb in fallbacks:
        if fb not in models:
            models.append(fb)
    return models

def _is_404_error(err: Exception) -> bool:
    if hasattr(err, "status_code") and err.status_code == 404:
        return True
    err_str = str(err).lower()
    return "404" in err_str or "model_not_found" in err_str or "does not exist" in err_str

def _is_non_retryable_client_error(err: Exception) -> bool:
    if _is_404_error(err):
        return True
    if hasattr(err, "status_code") and err.status_code in [400, 401, 403]:
        return True
    err_str = str(err).lower()
    return any(c in err_str for c in ["400", "401", "403", "unauthorized", "invalid_api_key", "permission_denied"])

def _is_retryable_server_error(err: Exception) -> bool:
    if hasattr(err, "status_code"):
        if err.status_code == 429 or err.status_code >= 500:
            return True
    err_str = str(err).lower()
    return any(k in err_str for k in ["429", "rate_limit", "too many requests", "500", "502", "503", "504", "timeout", "timed out", "connection"])

def _call_groq_stage_with_backoff(
    client,
    models: List[str],
    messages: list,
    temperature: float = 0.0,
    max_retries: int = 3,
    stage_name: str = "Stage",
    max_tokens: int = 1000
) -> Optional[str]:
    """
    Calls Groq chat completion for a stage with:
    - Semaphore concurrency limit (max 1 concurrent call)
    - Shared TPM rate limit throttle
    - Fallback list: tries next model if a model returns 404/model_not_found
    - Exponential backoff ONLY on 429 and 5xx/timeouts (max 3 retries)
    - No retries on 400/401/403/404
    - If none works, aborts early with clear error and non-zero exit (os._exit(1))
    """
    with _groq_semaphore:
        last_error = None

        for model_idx, model in enumerate(models):
            for attempt in range(1, max_retries + 1):
                try:
                    _throttle_groq_call(min_interval=1.5)
                    create_kwargs = {
                        "model": model,
                        "messages": messages,
                        "temperature": temperature,
                        "response_format": {"type": "json_object"},
                        "max_tokens": max_tokens,
                    }
                    if "gpt-oss" in model.lower():
                        create_kwargs["reasoning_effort"] = "low"

                    completion = client.chat.completions.create(**create_kwargs)
                    return completion.choices[0].message.content.strip()
                except Exception as e:
                    last_error = e
                    if _is_404_error(e):
                        logger.warning(f"[AI_MODEL_404] Model '{model}' not found for {stage_name}: {e}.")
                        if model_idx + 1 < len(models):
                            logger.info(f"[AI_FALLBACK] Trying fallback model '{models[model_idx + 1]}' for {stage_name}...")
                        break

                    if _is_non_retryable_client_error(e):
                        logger.error(f"[AI_ERROR] Non-retryable error on '{model}' ({stage_name}): {e}")
                        return None

                    if _is_retryable_server_error(e) and attempt < max_retries:
                        wait_time = (2 ** attempt) * 2
                        logger.warning(f"[AI_RETRY] Retryable error on '{model}' ({stage_name}, Attempt {attempt}/{max_retries}). Sleeping {wait_time}s: {e}")
                        time.sleep(wait_time)
                        continue

                    logger.error(f"[AI_ERROR] Groq API call failed on '{model}' ({stage_name}, Attempt {attempt}/{max_retries}): {e}")
                    break

        # If none works
        logger.critical(f"[AI_FATAL] All configured models for {stage_name} failed (tried: {models}). Last error: {last_error}. Aborting run early with exit code 1.")
        os._exit(1)

def _call_groq_with_backoff(client, model: str, messages: list, temperature: float = 0.0, max_retries: int = 3) -> Optional[str]:
    """Backwards-compatible single-model wrapper."""
    return _call_groq_stage_with_backoff(client, [model], messages, temperature=temperature, max_retries=max_retries, stage_name="Groq")

def preflight_check_groq_models(client=None) -> bool:
    """
    At startup (before scraping), performs one cheap preflight call to each configured model.
    If a model is unavailable, logs it and exits non-zero (both in production and DRY_RUN).
    """
    if client is None:
        client = _get_groq_client()
        if client is None:
            logger.error("[PREFLIGHT_ERROR] Cannot initialize Groq client for preflight check.")
            sys.exit(1)

    stage1_models = get_stage1_models()
    stage2_models = get_stage2_models()

    def check_stage(stage_label: str, models: List[str]):
        primary = models[0]
        try:
            client.chat.completions.create(
                model=primary,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=5
            )
            logger.info(f"[PREFLIGHT] {stage_label} model '{primary}' preflight check PASSED.")
            return primary
        except Exception as e:
            logger.warning(f"[PREFLIGHT] {stage_label} primary model '{primary}' preflight FAILED: {e}")
            # Try fallbacks
            for fb in models[1:]:
                try:
                    client.chat.completions.create(
                        model=fb,
                        messages=[{"role": "user", "content": "ping"}],
                        max_tokens=5
                    )
                    logger.info(f"[PREFLIGHT] {stage_label} fallback model '{fb}' preflight check PASSED.")
                    return fb
                except Exception as fbe:
                    logger.warning(f"[PREFLIGHT] {stage_label} fallback model '{fb}' preflight FAILED: {fbe}")
            logger.error(f"[PREFLIGHT_ERROR] No available models for {stage_label} (tried: {models}). Exiting non-zero.")
            sys.exit(1)

    check_stage("Stage 1", stage1_models)
    check_stage("Stage 2", stage2_models)
    return True

def verify_evidence_quotes(dates: list, full_text: str) -> tuple[bool, str]:
    """
    Code-level verification:
    Normalizes both source text and quotes (NFKC, zero-width chars removed,
    whitespace collapsed, Devanagari digits to ASCII, lowercase)
    and asserts quote exists in source text.
    """
    if not dates:
        return True, ""

    norm_source = normalize_text_for_evidence_matching(full_text)

    for item in dates:
        quote = item.get("evidence_quote", "").strip()
        if not quote:
            continue
        norm_quote = normalize_text_for_evidence_matching(quote)
        if norm_quote not in norm_source:
            increment_evidence_mismatch_count()
            return False, f"Evidence quote not found in source text: '{quote[:60]}...'"

    return True, ""

# Few-shot examples for Stage 2 (Using strictly fictional placeholders State X / Date Y)
FEW_SHOT_EXAMPLES = [
    {
        "role": "user",
        "content": """STATE: State Alpha
TITLE: State Alpha NMMS Exam Provisional Answer Key Out - Objections by 20 October 2099
SOURCE TEXT: शिक्षा विभाग स्टेट अल्फा द्वारा 10 अक्टूबर 2099 को आयोजित राष्ट्रीय साधन सह योग्यता छात्रवृत्ति (NMMS) परीक्षा सत्र 2099-2100 की अनंतिम उत्तरमाला portal.alpha.gov.in पर जारी कर दी गई है। किसी प्रश्न पर आपत्ति होने पर दिनांक 20 अक्टूबर 2099 सायं 05:00 बजे तक साक्ष्य सहित ईमेल पर दर्ज कराएं।"""
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "decision": "ACCEPT",
            "event_type": "ANSWER_KEY",
            "state": "State Alpha",
            "dates": [
                {
                    "label": "Objection Last Date",
                    "value": "20 October 2099",
                    "evidence_quote": "दिनांक 20 अक्टूबर 2099 सायं 05:00 बजे तक"
                },
                {
                    "label": "Exam Date",
                    "value": "10 October 2099",
                    "evidence_quote": "10 अक्टूबर 2099 को आयोजित"
                }
            ],
            "title_hi": "स्टेट अल्फा NMMS: अनंतिम उत्तर कुंजी जारी, 20 अक्टूबर तक दर्ज करें आपत्ति",
            "summary_hi": "स्टेट अल्फा NMMS परीक्षा की अनंतिम उत्तर कुंजी जारी कर दी गई है। छात्र 20 अक्टूबर 2099 तक अपनी आपत्ति साक्ष्य सहित दर्ज करा सकते हैं।",
            "summary_en": "State Alpha NMMS provisional answer key released. Candidates can submit objections until 20 October 2099.",
            "confidence": "high",
            "reason": "Official provisional answer key notice with concrete objection deadline."
        })
    },
    {
        "role": "user",
        "content": """STATE: State Beta
TITLE: State Beta NMMS Application Last Date Extended till 25 November 2099
SOURCE TEXT: एससीईआरटी स्टेट बीटा द्वारा राष्ट्रीय आय सह मेधा छात्रवृत्ति (NMMS) 2099-2100 के ऑनलाइन आवेदन की अंतिम तिथि बढ़ाकर 25 नवंबर 2099 कर दी गई है। पात्र छात्र scert.beta.gov.in पर आवेदन करें।"""
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "decision": "ACCEPT",
            "event_type": "EXTENSION",
            "state": "State Beta",
            "dates": [
                {
                    "label": "Extended Last Date",
                    "value": "25 November 2099",
                    "evidence_quote": "बढ़ाकर 25 नवंबर 2099 कर दी गई है"
                }
            ],
            "title_hi": "स्टेट बीटा NMMS: आवेदन की अंतिम तिथि 25 नवंबर तक बढ़ी",
            "summary_hi": "स्टेट बीटा NMMS छात्रवृत्ति आवेदन की अंतिम तिथि बढ़ाकर 25 नवंबर 2099 कर दी गई है।",
            "summary_en": "State Beta NMMS application deadline extended to 25 November 2099.",
            "confidence": "high",
            "reason": "Official extension of deadline to a later date."
        })
    },
    {
        "role": "user",
        "content": """STATE: State Gamma
TITLE: State Gamma NMMS Exam Date 2099 Announced for 15 December 2099
SOURCE TEXT: परीक्षा परिषद स्टेट गामा द्वारा राष्ट्रीय मीन्स कम मेरिट छात्रवृत्ति परीक्षा सत्र 2099-2100 का आयोजन 15 दिसंबर 2099 को किया जाएगा। प्रवेश पत्र परीक्षा से पूर्व जारी होंगे।"""
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "decision": "ACCEPT",
            "event_type": "EXAM_DATE",
            "state": "State Gamma",
            "dates": [
                {
                    "label": "Exam Date",
                    "value": "15 December 2099",
                    "evidence_quote": "आयोजन 15 दिसंबर 2099 को किया जाएगा"
                }
            ],
            "title_hi": "स्टेट गामा NMMS: परीक्षा तिथि 15 दिसंबर घोषित",
            "summary_hi": "स्टेट गामा NMMS परीक्षा 15 दिसंबर 2099 को आयोजित की जाएगी।",
            "summary_en": "State Gamma NMMS exam will be held on 15 December 2099.",
            "confidence": "high",
            "reason": "Official exam schedule announcement."
        })
    },
    {
        "role": "user",
        "content": """STATE: Central (NSP)
TITLE: National Scholarship Scheme for Secondary Students Circular
SOURCE TEXT: Ministry circular regarding guidelines for post-matric higher education scholarship schemes."""
    },
    {
        "role": "assistant",
        "content": json.dumps({
            "decision": "REJECT",
            "event_type": "NSP_OTHER",
            "state": "Central (NSP)",
            "dates": [],
            "title_hi": "",
            "summary_hi": "",
            "summary_en": "",
            "confidence": "high",
            "reason": "Circular is for post-matric schemes, strictly NOT Class 8 NMMS."
        })
    }
]

NMMS_CORE_KEYWORDS = [
    "nmms", "nmmss", "nmmse", "राष्ट्रीय आय", "मेधा छात्रवृत्ति",
    "means-cum-merit", "means cum merit", "national means"
]

def has_nmms_core_keyword(text: str) -> bool:
    """Cheap code-level keyword pre-filter before calling Groq API."""
    clean = (text or "").lower()
    return any(kw in clean for kw in NMMS_CORE_KEYWORDS)

def analyze_notice_with_groq_pipeline(
    state: str,
    title: str,
    notice_url: str = "",
    raw_content: str = "",
    history_entries: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    Two-Stage Fail-Closed AI Gatekeeper:
    Returns dict with keys: is_error, decision, event_type, state, dates, summary_hi, summary_en, confidence, reason.
    """
    extracted_text = raw_content.strip() if raw_content else ""
    if not extracted_text and notice_url:
        extracted_text = extract_content_from_source(notice_url, max_chars=6000)

    full_source_text = f"TITLE: {title}\n\nCONTENT:\n{extracted_text if extracted_text else title}"

    # Code-level keyword pre-filter before Groq call
    if not has_nmms_core_keyword(full_source_text):
        return {
            "is_error": False,
            "decision": "REJECT",
            "reason": "Code pre-filter: No NMMS core keyword found in title/text",
            "event_type": "REJECTED_NON_NMMS"
        }

    client = _get_groq_client()
    if client is None:
        logger.error("[AI_GATE] GROQ_API_KEY is missing or Groq client failed. Fail-closed: notice rejected from posting.")
        return {
            "is_error": True,
            "decision": "REJECT",
            "reason": "Groq client unavailable (fail-closed safe default)"
        }

    today_ist = get_ist_now().strftime("%d %B %Y")
    cur_year = get_ist_today().year

    # STAGE 1: Relevance Only (configurable model & fallbacks)
    stage1_system = f"""You are an ultra-fast Relevance Filter for Class 8 NMMS (National Means-cum-Merit Scholarship / NMMSS / राष्ट्रीय आय एवं योग्यता आधारित छात्रवृत्ति).
Today's Date (IST): {today_ist}.
NOTE: NMMS / NMMSS is nationwide by definition the Class 8 scholarship scheme. Any official notice about NMMS / NMMSS (applications, extension, admit card, answer key, exam date, result, NSP portal) IS NMMS relevant even if the text does not explicitly repeat the words 'Class 8'.

QUESTION: Is this document/notice related to NMMS / NMMSS?

STRICT REJECTION RULES:
- Return false if the notice is for other schemes: PM-YASASVI, CSSS, Pre-Matric SC/ST, Post-Matric, NTSE, Inspire, or general non-NMMS schemes.
- Return false if it is an internal administrative letter (e.g. Letter to DEOs, attendance sheets, room seating matrix, exam center staff duty list, tenders/quotations).
- Return false if it is merely past year sample/practice question papers.

Output strictly a JSON object:
{{
  "is_nmms_relevant": true | false,
  "reason": "One short sentence explaining why"
}}"""

    stage1_messages = [
        {"role": "system", "content": stage1_system},
        {"role": "user", "content": f"STATE: {state}\n\nDOCUMENT:\n{full_source_text[:1500]}"}
    ]

    stage1_raw = _call_groq_stage_with_backoff(
        client, get_stage1_models(), stage1_messages, temperature=0.0, stage_name="Stage 1", max_tokens=150
    )
    if not stage1_raw:
        logger.error(f"[AI_ERROR] Stage 1 failed for notice '{title}' ({state}). Fail-closed.")
        return {
            "is_error": True,
            "decision": "REJECT",
            "reason": "Stage 1 Groq API error / 429 exhausted"
        }

    try:
        stage1_data = json.loads(stage1_raw)
        is_relevant = bool(stage1_data.get("is_nmms_relevant", False))
        if not is_relevant:
            reason = stage1_data.get("reason", "Not relevant to Class 8 NMMS")
            return {
                "is_error": False,
                "decision": "REJECT",
                "reason": f"Stage 1 Reject: {reason}",
                "event_type": "REJECTED_NON_NMMS"
            }
    except Exception as je:
        logger.error(f"[AI_ERROR] Stage 1 invalid JSON: {je}. Raw: {stage1_raw[:100]}")
        return {
            "is_error": True,
            "decision": "REJECT",
            "reason": "Stage 1 JSON parsing error"
        }

    # STAGE 2: Structured Fact Extraction (llama-3.3-70b-versatile)
    history_summary = "None recorded in the last 30 days."
    if history_entries:
        items = []
        for idx, h in enumerate(history_entries[:15], 1):
            items.append(f"[{idx}] {h.get('title')} | Type: {h.get('event_type')} | Dates: {h.get('last_date') or h.get('event_date')}")
        history_summary = "\n".join(items)

    stage2_system = f"""You are the Chief Quality Gatekeeper and Fact Extractor for Sagar Coaching Centre Class 8 NMMS Telegram Channel.
Today's Date (IST): {today_ist}. Current Cycle: {cur_year}-{str(cur_year+1)[-2:]}.

TASK:
1. Extract structured factual data from the notice.
2. Determine decision: ACCEPT or REJECT.
3. Reject if:
   - Expired date: Any primary deadline in notice has already passed before {today_ist}.
   - Semantic duplicate: History already contains this exact announcement with the same dates/facts.
   - Low factual confidence or no verifiable student event.
4. event_type MUST be one of: FORM_START, LAST_DATE, EXTENSION, CORRECTION, EXAM_DATE, ADMIT_CARD, ANSWER_KEY, RESULT, NSP_APPLY, NSP_OTHER.
5. In dates array, provide label, value, and evidence_quote. Every evidence_quote MUST be an EXACT VERBATIM QUOTE from the source text.
6. summary_hi and summary_en MUST contain ONLY facts from this document (no invented information).

Output strictly a JSON object:
{{
  "decision": "ACCEPT" | "REJECT",
  "event_type": "ENUM_VALUE",
  "state": "{state}",
  "title_hi": "Clean concise Hindi title max 80 chars without mid-word truncation",
  "dates": [
    {{"label": "Label", "value": "Date Value", "evidence_quote": "Verbatim quote from source text"}}
  ],
  "summary_hi": "Crisp Hindi summary (2-3 sentences)",
  "summary_en": "Crisp English summary (2-3 sentences)",
  "confidence": "high" | "medium" | "low",
  "reason": "Explanation of decision"
}}"""

    stage2_messages = [
        {"role": "system", "content": stage2_system}
    ]
    stage2_messages.extend(FEW_SHOT_EXAMPLES)
    stage2_messages.append({
        "role": "user",
        "content": f"""STATE: {state}
TITLE: {title}
RECENT POSTED HISTORY (Last 30 days):
{history_summary}

SOURCE TEXT:
{full_source_text[:4000]}"""
    })

    stage2_raw = _call_groq_stage_with_backoff(
        client, get_stage2_models(), stage2_messages, temperature=0.0, stage_name="Stage 2", max_tokens=600
    )
    if not stage2_raw:
        logger.error(f"[AI_ERROR] Stage 2 failed for notice '{title}' ({state}). Fail-closed.")
        return {
            "is_error": True,
            "decision": "REJECT",
            "reason": "Stage 2 Groq API error / 429 exhausted"
        }

    try:
        stage2_data = json.loads(stage2_raw)
    except Exception as je:
        logger.error(f"[AI_ERROR] Stage 2 invalid JSON: {je}. Raw: {stage2_raw[:150]}")
        return {
            "is_error": True,
            "decision": "REJECT",
            "reason": "Stage 2 JSON parsing error"
        }

    decision = stage2_data.get("decision", "REJECT").upper()
    confidence = str(stage2_data.get("confidence", "low")).lower()
    event_type = stage2_data.get("event_type", "").upper()
    dates = stage2_data.get("dates", [])
    reason = stage2_data.get("reason", "")

    if event_type not in VALID_EVENT_TYPES:
        event_type = "NSP_OTHER" if "nsp" in state.lower() else "LAST_DATE"

    if confidence == "low":
        return {
            "is_error": False,
            "decision": "REJECT",
            "reason": f"Low confidence: {reason}",
            "event_type": event_type
        }

    # Code-level evidence quote verification with advanced normalization
    valid_quotes, quote_err = verify_evidence_quotes(dates, full_source_text)
    if not valid_quotes:
        logger.warning(f"[EVIDENCE_QUOTE_REJECT] {quote_err} for '{title}'")
        return {
            "is_error": False,
            "decision": "REJECT",
            "reason": quote_err,
            "event_type": event_type
        }

    return {
        "is_error": False,
        "decision": decision,
        "event_type": event_type,
        "state": stage2_data.get("state") or state,
        "title_hi": stage2_data.get("title_hi", ""),
        "dates": dates,
        "summary_hi": stage2_data.get("summary_hi", ""),
        "summary_en": stage2_data.get("summary_en", ""),
        "confidence": confidence,
        "reason": reason
    }
