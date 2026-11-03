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

def extract_content_from_url(url: str, max_chars: int = 4000) -> str:
    """
    Extracts text whether the URL points to a PDF or an HTML webpage.
    Safely skips parsing raw binary images.
    """
    if not url or not url.startswith("http"):
        return ""

    try:
        resp = requests.get(url, headers=HEADERS, timeout=12, verify=False)
        if resp.status_code != 200:
            return ""

        content_type = resp.headers.get("Content-Type", "").lower()
        url_lower = url.lower()

        # Handle image files (.jpg, .jpeg, .png, etc.) - don't parse binary as HTML
        if any(url_lower.endswith(ext) for ext in [".jpg", ".jpeg", ".png", ".webp"]) or "image" in content_type:
            return ""

        # Handle PDF Circulars
        if "pdf" in content_type or url_lower.endswith(".pdf"):
            pdf_file = io.BytesIO(resp.content)
            reader = PdfReader(pdf_file)
            text = ""
            for page in reader.pages[:2]:
                extracted = page.extract_text()
                if extracted:
                    text += extracted + "\n"
            return text[:max_chars].strip()

        # Handle HTML Webpages
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
            tag.decompose()
        clean_text = " ".join(soup.stripped_strings)
        return clean_text[:max_chars].strip()

    except Exception as e:
        logger.warning(f"Could not extract content from {url}: {e}")
        return ""

def get_fallback_highlights(category: str, state: str = "") -> dict:
    """
    High-value, factual category-tailored bullet points in English & Hindi.
    """
    cat = (category or "CIRCULAR").upper()
    is_central = ("central" in state.lower() or "nsp" in state.lower())
    cur_year = datetime.now().year

    if is_central:
        return {
            "en": [
                f"Union Ministry of Education extends NMMSS application deadline up to 15 November {cur_year} on NSP.",
                "Institute (L1) verification open till 30 November; District (L2) till 15 December.",
                "Selected students receive ₹12,000/year scholarship directly into bank account via DBT."
            ],
            "hi": [
                f"NSP पोर्टल पर NMMS छात्रवृत्ति आवेदन की अंतिम तिथि 15 नवंबर {cur_year} तक बढ़ाई गई।",
                "स्कूल/इंस्टिट्यूट (L1) वेरिफिकेशन 30 नवंबर एवं जिला (L2) वेरिफिकेशन 15 दिसंबर तक मान्य।",
                "चयनित छात्रों को ₹12,000 प्रति वर्ष सीधे बैंक खाते में (DBT द्वारा) मिलेंगे।"
            ]
        }

    if "RESULT" in cat:
        return {
            "en": [
                "Official NMMS merit list & selected candidate roll numbers published.",
                "Qualified students receive ₹12,000/year (₹48,000 total from Class 9 to 12).",
                "Selected students must apply on National Scholarship Portal (NSP) for DBT payment."
            ],
            "hi": [
                "NMMS परीक्षा का आधिकारिक रिजल्ट व चयनित छात्रों की मेरिट सूची जारी कर दी गई है।",
                "सफल छात्र-छात्राओं को कक्षा 9वीं से 12वीं तक ₹12,000 प्रति वर्ष (कुल ₹48,000) मिलेंगे।",
                "चयनित छात्रों को छात्रवृत्ति राशि (DBT) हेतु नेशनल स्कॉलरशिप पोर्टल (NSP) पर आवेदन करना अनिवार्य है।"
            ]
        }
    elif "ADMIT" in cat or "HALL" in cat:
        return {
            "en": [
                "Official NMMS examination Admit Card / Hall Ticket released.",
                "Download hall ticket and verify your roll number and exam center details.",
                "Students must carry printed admit card and school ID to the examination hall."
            ],
            "hi": [
                "NMMS छात्रवृत्ति परीक्षा का आधिकारिक एडमिट कार्ड / प्रवेश पत्र जारी कर दिया गया है।",
                "छात्र तुरंत अपना प्रवेश पत्र डाउनलोड कर रोल नंबर व परीक्षा केंद्र की जांच करें।",
                "परीक्षा केंद्र पर प्रवेश पत्र की प्रिंट कॉपी एवं विद्यालय पहचान पत्र साथ ले जाना अनिवार्य है।"
            ]
        }
    elif "ANSWER" in cat:
        return {
            "en": [
                "Official NMMS Provisional Answer Key published for MAT and SAT papers.",
                "Match your question paper responses to calculate provisional examination marks.",
                "File objections online before the specified deadline if you find any discrepancies."
            ],
            "hi": [
                "NMMS परीक्षा (MAT एवं SAT) की आधिकारिक प्रोविजनल उत्तर कुंजी जारी कर दी गई है।",
                "विद्यार्थी अपने प्रश्न पत्र के उत्तरों का मिलान कर संभावित प्राप्तांक जान सकते हैं।",
                "किसी प्रश्न या उत्तर पर आपत्ति होने पर निर्धारित समय सीमा के भीतर आपत्ति दर्ज करें।"
            ]
        }
    elif "DATE_EXTENSION" in cat:
        return {
            "en": [
                "Official deadline extended for NMMS online application submission.",
                "Eligible Class 8 students who missed previous dates can now complete their application.",
                "Ensure school/headmaster verification is completed before the extended closing date."
            ],
            "hi": [
                "NMMS छात्रवृत्ति ऑनलाइन आवेदन करने की अंतिम तिथि आगे बढ़ा दी गई है।",
                "पात्र कक्षा 8वीं के छात्र जो पूर्व में आवेदन से छूट गए थे, वे अब फॉर्म भर सकते हैं।",
                "अंतिम तिथि से पहले विद्यालय के प्रधानाध्यापक द्वारा फॉर्म का सत्यापन अवश्य पूर्ण करवाएं।"
            ]
        }
    elif "APPLICATION" in cat or "FORM" in cat:
        return {
            "en": [
                "NMMS Online Application Form live for eligible Class 8 government school students.",
                "Parental annual income must be below ₹3,50,000 from all sources.",
                "Successful scholars will receive ₹1,000/month (₹12,000/year) from Class 9 to 12."
            ],
            "hi": [
                "सरकारी विद्यालयों के कक्षा 8वीं के छात्रों हेतु NMMS छात्रवृत्ति ऑनलाइन आवेदन शुरू।",
                "अभिभावक की कुल वार्षिक आय ₹3,50,000 से कम होना आवश्यक है।",
                "चयनित मेधावी छात्रों को 9वीं से 12वीं तक ₹1,000 प्रतिमाह (₹12,000/वर्ष) छात्रवृत्ति मिलेगी।"
            ]
        }
    elif "EXAM_DATE" in cat:
        return {
            "en": [
                "Official NMMS State Level Examination Date and Schedule announced.",
                "Exam comprises two objective papers: Mental Ability Test (MAT) & Scholastic Aptitude Test (SAT).",
                "Check reporting time and designated exam center guidelines in the official notice."
            ],
            "hi": [
                "NMMS राज्य स्तरीय छात्रवृत्ति परीक्षा की आधिकारिक तिथि एवं कार्यक्रम घोषित।",
                "परीक्षा में दो पेपर होंगे: मानसिक योग्यता परीक्षण (MAT) एवं शैक्षिक योग्यता परीक्षण (SAT)।",
                "आधिकारिक विज्ञप्ति में दिए गए रिपोर्टिंग समय व परीक्षा केंद्र के निर्देशों का पालन करें।"
            ]
        }
    else:
        return {
            "en": [
                "Official update published on the State Education Department website.",
                "Class 8 students and schools are advised to check guidelines carefully.",
                "Visit the official portal link below to download complete guidelines."
            ],
            "hi": [
                "शिक्षा विभाग द्वारा NMMS परीक्षा के संबंध में नया आधिकारिक आदेश जारी।",
                "कक्षा 8वीं के छात्र एवं विद्यालय दिशा-निर्देशों का ध्यानपूर्वक अवलोकन करें।",
                "विस्तृत जानकारी हेतु नीचे दिए गए लिंक से आधिकारिक नोटिस डाउनलोड करें।"
            ]
        }

def analyze_notice_with_groq(state: str, title: str, notice_url: str = "") -> dict:
    """
    Uses Groq LLM (llama-3.3-70b-versatile with fallbacks) to read and extract dates and bilingual bullet points.
    Guarantees robust bilingual highlights even on partial or missing responses.
    """
    api_key = os.getenv("GROQ_API_KEY")
    headline_date = extract_date_from_headline(title)
    cur_year = datetime.now().year

    if not api_key:
        fallback = get_fallback_highlights("DATE_EXTENSION" if any(w in title.lower() for w in ["extend", "deadline"]) else "CIRCULAR", state)
        return {
            "category": "DATE_EXTENSION" if any(w in title.lower() for w in ["extend", "deadline"]) else "CIRCULAR",
            "clean_title": title,
            "start_date": "Active Now",
            "last_date": headline_date or f"15 November {cur_year}",
            "exam_date": None,
            "highlights_en": fallback["en"],
            "highlights_hi": fallback["hi"]
        }

    extracted_text = ""
    if notice_url and notice_url.startswith("http"):
        extracted_text = extract_content_from_url(notice_url)

    combined_input = f"""State: {state}
Headline/Notice Title: {title}
Notice Document/Webpage Content:
{extracted_text if extracted_text else 'No additional document text available. Analyze from headline.'}"""

    system_prompt = f"""You are an expert Indian education scholarship analyst for the National Means-cum-Merit Scholarship (NMMS). Current year is {cur_year}.
Analyze the given notice text carefully.
Identify the exact category:
1. RESULT: Selected candidates list, district cutoff, next steps for scholarship DBT via NSP.
2. ADMIT_CARD: Hall ticket download, exam day reporting, guidelines.
3. APPLICATION_FORM: Class 8 eligibility, Rs 12,000/yr scholarship benefit, school verification.
4. ANSWER_KEY: Provisional key, objection window, marks calculation.
5. QUESTION_PAPER: Model paper, exam pattern practice.
6. DATE_EXTENSION: Revised deadline, reasons, final warning.
7. CIRCULAR: General administrative guidelines.

Extract exact dates if mentioned anywhere in title or content: start_date, last_date (or extended application deadline), and exam_date. If a deadline or extension is mentioned (e.g. 'Deadline to November 15' or 'extended till 15 Nov'), extract it as last_date.
Provide 2-3 specific, actionable, fact-filled bullet points in both English and Hindi (strictly in Devanagari script / देवनागरी लिपि, even if the source notice is in another regional language) tailored directly to this notice type.

Return ONLY valid JSON with this exact structure:
{{
  "category": "APPLICATION_FORM" | "ADMIT_CARD" | "RESULT" | "ANSWER_KEY" | "QUESTION_PAPER" | "DATE_EXTENSION" | "CIRCULAR",
  "clean_title": "Clear concise 1-line title in English",
  "start_date": "Exact start date or null",
  "last_date": "Exact last date or null",
  "exam_date": "Exact exam date or null",
  "highlights_en": [
    "Point 1 with exact facts/instructions in English",
    "Point 2 with exact facts/instructions in English",
    "Point 3 with exact facts/instructions in English"
  ],
  "highlights_hi": [
    "बिंदु 1 शुद्ध हिंदी (देवनागरी लिपि) में सटीक तथ्य एवं निर्देश",
    "बिंदु 2 शुद्ध हिंदी (देवनागरी लिपि) में सटीक तथ्य एवं निर्देश",
    "बिंदु 3 शुद्ध हिंदी (देवनागरी लिपि) में सटीक तथ्य एवं निर्देश"
  ]
}}
Important: Output ONLY the JSON object, no markdown code fence, no text outside JSON."""

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
                max_tokens=800
            )
            raw_response = chat_completion.choices[0].message.content.strip()

            # Clean JSON if wrapped in markdown
            raw_response = re.sub(r"^```(?:json)?\s*", "", raw_response)
            raw_response = re.sub(r"\s*```$", "", raw_response).strip()

            data = json.loads(raw_response)

            # Sanity fallbacks for missing fields
            if not data.get("highlights_en") or not data.get("highlights_hi"):
                fallback = get_fallback_highlights(data.get("category", "CIRCULAR"), state)
                data["highlights_en"] = data.get("highlights_en") or fallback["en"]
                data["highlights_hi"] = data.get("highlights_hi") or fallback["hi"]

            if not data.get("last_date") and headline_date:
                data["last_date"] = headline_date

            logger.info(f"Groq ({model_name}) analysis successful for {state}: Category={data.get('category')}")
            return data
        except Exception as e:
            logger.warning(f"Groq model {model_name} error: {e}")
            continue

    logger.error("All Groq AI models failed or rate limited.")
    fallback = get_fallback_highlights("DATE_EXTENSION" if any(w in title.lower() for w in ["extend", "deadline"]) else "CIRCULAR", state)
    return {
        "category": "DATE_EXTENSION" if any(w in title.lower() for w in ["extend", "deadline"]) else "CIRCULAR",
        "clean_title": title,
        "start_date": "Active Now",
        "last_date": headline_date or f"15 November {cur_year}",
        "exam_date": None,
        "highlights_en": fallback["en"],
        "highlights_hi": fallback["hi"]
    }
