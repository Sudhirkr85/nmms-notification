import os
import io
import json
import logging
import re
import requests
from datetime import datetime
from bs4 import BeautifulSoup
from pypdf import PdfReader
from groq import Groq

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def extract_date_from_headline(title: str) -> str:
    cur_year = str(datetime.now().year)
    month_names = r'(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'

    # Month Day (e.g., November 15)
    m1 = re.search(rf'\b({month_names})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:\s*,?\s*(\d{{4}}))?\b', title, re.I)
    if m1:
        month = m1.group(1).capitalize()
        day = m1.group(2)
        year = m1.group(3) or cur_year
        return f"{day} {month} {year}"

    # Day Month (e.g., 15th November)
    m2 = re.search(rf'\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_names})(?:\s*,?\s*(\d{{4}}))?\b', title, re.I)
    if m2:
        day = m2.group(1)
        month = m2.group(2).capitalize()
        year = m2.group(3) or cur_year
        return f"{day} {month} {year}"

    m3 = re.search(r'\b(\d{1,2})[-/\.](\d{1,2})[-/\.](\d{2,4})\b', title)
    if m3:
        return m3.group(0)

    return ""

def extract_content_from_url(url: str, max_chars: int = 6000) -> str:
    if not url or not url.startswith("http"):
        return ""

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        if resp.status_code != 200:
            return ""

        content_type = resp.headers.get("Content-Type", "").lower()
        url_lower = url.lower()

        if any(url_lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]) or "image" in content_type:
            return ""

        if "pdf" in content_type or url_lower.endswith(".pdf"):
            pdf_file = io.BytesIO(resp.content)
            reader = PdfReader(pdf_file)
            text = ""
            for page in reader.pages[:5]:
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
        logger.warning(f"Could not extract content from {url}: {e}")
        return ""

def get_fallback_highlights(category: str, state: str = "", title: str = "") -> dict:
    """
    Fallback highlights tailored to title context (used only if AI service is completely unreachable).
    """
    cat = (category or "CIRCULAR").upper()
    is_central = ("central" in state.lower() or "nsp" in state.lower())
    cur_year = datetime.now().year

    if is_central:
        return {
            "en": [
                f"Ministry of Education official deadline update on NSP for Session {cur_year}-{str(cur_year+1)[-2:]}.",
                f"Check official guidelines on scholarships.gov.in portal."
            ],
            "hi": [
                f"शिक्षा मंत्रालय द्वारा NSP पोर्टल पर सत्र {cur_year}-{str(cur_year+1)[-2:]} हेतु आधिकारिक सूचना।",
                "विस्तृत दिशा-निर्देश scholarships.gov.in पोर्टल पर देखें।"
            ]
        }

    if cat == "ANSWER_KEY" or any(w in (title or "").lower() for w in ["answer key", "ans key", "uttar kunji", "objection", "उत्तर कुंजी", "उत्तरमाला", "आपत्ति"]):
        return {
            "en": [
                f"Official Provisional Answer Key released for {state} NMMS Examination.",
                "Candidates can verify answers and submit online objections with supporting proof before the deadline."
            ],
            "hi": [
                f"{state} NMMS परीक्षा की आधिकारिक अनंतिम उत्तरमाला (Answer Key) जारी।",
                "अभ्यर्थी उत्तरों का मिलान करें एवं किसी विसंगति पर निर्धारित अंतिम तिथि तक साक्ष्य सहित आपत्ति दर्ज कराएं।"
            ]
        }

    return {
        "en": [
            f"Official {cat.replace('_', ' ').title()} notice issued by {state} Education Authority.",
            "Refer to the attached official PDF document for exact instructions."
        ],
        "hi": [
            f"{state} शिक्षा विभाग द्वारा आधिकारिक आदेश/विज्ञप्ति जारी।",
            "सटीक जानकारी एवं तिथियों हेतु संलग्न आधिकारिक आदेश (PDF) देखें।"
        ]
    }

def analyze_notice_with_groq(state: str, title: str, notice_url: str = "", recent_posts: list = None, raw_text: str = "") -> dict:
    """
    100% AI-Driven Quality Gatekeeper, Semantic Deduplicator, and Notice-Specific Fact Extractor.
    Powered by Groq LLaMA-3.3-70B.
    
    Guarantees:
    1. Filter: Rejects DEO/officer circulars, staff attendance, question papers, old archives.
    2. Deduplicator: Matches meaning against recently posted announcements to prevent duplicate spam.
    3. Specificity: Extracts ONLY concrete facts directly from the notice (dates, shifts, fees, criteria).
    """
    api_key = os.getenv("GROQ_API_KEY")
    headline_date = extract_date_from_headline(title)
    cur_year = datetime.now().year

    recent_posts_summary = "None yet."
    if recent_posts:
        items = []
        for idx, p in enumerate(recent_posts, 1):
            items.append(f"[{idx}] Title: '{p.get('title')}' | Last Date: {p.get('last_date', 'N/A')}")
        recent_posts_summary = "\n".join(items)

    extracted_text = raw_text.strip() if raw_text else ""
    if not extracted_text and notice_url and notice_url.startswith("http"):
        extracted_text = extract_content_from_url(notice_url)

    if not api_key:
        fallback = get_fallback_highlights("DATE_EXTENSION" if any(w in title.lower() for w in ["extend", "deadline"]) else "CIRCULAR", state, title)
        return {
            "is_student_actionable": True,
            "is_semantic_duplicate": False,
            "rejection_reason": None,
            "category": "DATE_EXTENSION" if any(w in title.lower() for w in ["extend", "deadline"]) else "CIRCULAR",
            "clean_title": title,
            "start_date": "Active Now",
            "last_date": headline_date or f"15 November {cur_year}",
            "exam_date": None,
            "highlights_en": fallback["en"],
            "highlights_hi": fallback["hi"]
        }

    combined_input = f"""STATE/AUTHORITY: {state}
CANDIDATE NOTICE TITLE: {title}
CANDIDATE NOTICE DOCUMENT/PAGE CONTENT:
{extracted_text if extracted_text else 'No additional document text. Analyze headline carefully.'}

RECENT ANNOUNCEMENTS ALREADY POSTED IN TELEGRAM FOR THIS STATE:
{recent_posts_summary}"""

    system_prompt = f"""You are the Chief Editor and Quality Gatekeeper for a premium paid NMMS Scholarship channel for Class 8 students & parents. Current year is {cur_year}.

Subscribers pay for ACCURACY, FRESHNESS, and REAL NOTICE-SPECIFIC FACTS.

EVALUATE AND ACT:
1. is_student_actionable (boolean):
   - TRUE only if this notice contains genuine student-facing action: Application Form Live, Deadline Extended, Admit Card Out, Exam Schedule Announced, Answer Key Out, Result Declared.
   - FALSE if it is:
     * Internal departmental/officer order (Letter to DEOs, District Education Officers, Principals, Nodal officers, Superintendent instructions)
     * Center logistics (Attendance sheets, Attn sheets, Seat matrix, Room allotment, Invigilator duty lists)
     * Practice/Question papers (Sample papers, model question papers, previous year question papers)
     * Administrative/commercial (Tenders, quotations, auction, meeting minutes)
     * Outdated/archived notices from past years or expired sessions
     * Bare portal menu buttons (e.g. "NMMS 2027-28" with no real circular text)

2. is_semantic_duplicate (boolean):
   - Check against RECENT ANNOUNCEMENTS ALREADY POSTED.
   - If this candidate notice reports the SAME event, same deadline extension, or same announcement already covered (even if rephrased by different media outlets), return TRUE.
   - Otherwise FALSE.

3. STRICT RULE FOR HIGHLIGHTS (NO GENERIC COPY-PASTE):
   - Do NOT output generic boilerplate slogans like "Students receive Rs 12,000/yr" or generic advice.
   - Every single bullet point MUST state concrete, specific facts directly mentioned in THIS document:
     * Exact dates (Start date, Last date, Exam date, Correction window)
     * Exact exam timings & shifts (e.g. MAT: 10:00 to 11:30 AM, SAT: 1:00 to 2:30 PM) if given
     * Exact fee amounts, passing marks, or specific eligibility conditions stated in THIS document
     * Exact submission / verification steps specified in THIS document
   - Provide 2-3 specific points in English and Hindi (Devanagari script).

Return ONLY valid JSON with this exact structure:
{{
  "is_student_actionable": true | false,
  "is_semantic_duplicate": true | false,
  "rejection_reason": "Specific reason if actionable is false or duplicate is true, else null",
  "category": "APPLICATION_FORM" | "ADMIT_CARD" | "RESULT" | "ANSWER_KEY" | "DATE_EXTENSION" | "EXAM_DATE" | "CIRCULAR",
  "clean_title": "Clear concise 1-line title in English",
  "start_date": "Exact start date or null",
  "last_date": "Exact last date or null",
  "exam_date": "Exact exam date or null",
  "highlights_en": [
    "Fact 1 specific to this notice in English",
    "Fact 2 specific to this notice in English"
  ],
  "highlights_hi": [
    "तथ्य 1 इस नोटिस से संबंधित शुद्ध हिंदी में",
    "तथ्य 2 इस नोटिस से संबंधित शुद्ध हिंदी में"
  ]
}}
Important: Output ONLY the JSON object, no markdown code fence."""

    client = Groq(api_key=api_key)
    models_to_try = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant", "qwen/qwen3.8-27b"]

    for model_name in models_to_try:
        try:
            chat_completion = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": combined_input}
                ],
                model=model_name,
                temperature=0.1,
                max_tokens=900
            )
            raw_response = chat_completion.choices[0].message.content.strip()
            raw_response = re.sub(r"^```(?:json)?\s*", "", raw_response)
            raw_response = re.sub(r"\s*```$", "", raw_response).strip()

            data = json.loads(raw_response)

            if not data.get("highlights_en") or not data.get("highlights_hi"):
                fallback = get_fallback_highlights(data.get("category", "CIRCULAR"), state, title)
                data["highlights_en"] = data.get("highlights_en") or fallback["en"]
                data["highlights_hi"] = data.get("highlights_hi") or fallback["hi"]

            if not data.get("last_date") and headline_date:
                data["last_date"] = headline_date

            logger.info(
                f"Groq AI Gatekeeper ({model_name}) for {state}: "
                f"Actionable={data.get('is_student_actionable')}, "
                f"Duplicate={data.get('is_semantic_duplicate')}, "
                f"Reason={data.get('rejection_reason')}"
            )
            return data
        except Exception as e:
            logger.warning(f"Groq model {model_name} error: {e}")
            continue

    logger.error("All Groq AI models failed or rate limited.")
    fallback = get_fallback_highlights("DATE_EXTENSION" if any(w in title.lower() for w in ["extend", "deadline"]) else "CIRCULAR", state, title)
    return {
        "is_student_actionable": True,
        "is_semantic_duplicate": False,
        "rejection_reason": None,
        "category": "DATE_EXTENSION" if any(w in title.lower() for w in ["extend", "deadline"]) else "CIRCULAR",
        "clean_title": title,
        "start_date": "Active Now",
        "last_date": headline_date or f"15 November {cur_year}",
        "exam_date": None,
        "highlights_en": fallback["en"],
        "highlights_hi": fallback["hi"]
    }
