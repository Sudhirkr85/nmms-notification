import os
import io
import json
import logging
import requests
from bs4 import BeautifulSoup
from pypdf import PdfReader
from groq import Groq

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

def extract_content_from_url(url: str, max_chars: int = 4000) -> str:
    """
    Extracts text whether the URL points to a PDF or an HTML webpage.
    """
    if not url or not url.startswith("http"):
        return ""

    try:
        resp = requests.get(url, headers=HEADERS, timeout=12, verify=False)
        if resp.status_code != 200:
            return ""

        content_type = resp.headers.get("Content-Type", "").lower()

        # Handle PDF Circulars
        if "pdf" in content_type or url.lower().endswith(".pdf"):
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

def get_fallback_highlights(category: str) -> dict:
    """
    High-value, factual category-tailored bullet points in English & Hindi.
    """
    cat = (category or "CIRCULAR").upper()
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
                "Official admit cards/hall tickets are now available for download.",
                "Candidates must check exam center, roll number, and exam timing carefully.",
                "Carry a printed admit card along with school ID card to the exam center."
            ],
            "hi": [
                "NMMS परीक्षा हेतु प्रवेश पत्र (Admit Card) आधिकारिक वेबसाइट से डाउनलोड करें।",
                "छात्र अपने एडमिट कार्ड पर परीक्षा केंद्र, रोल नंबर और समय की जांच अवश्य करें।",
                "परीक्षा के दिन प्रिंटेड एडमिट कार्ड व स्कूल पहचान पत्र साथ ले जाना अनिवार्य है।"
            ]
        }
    elif "APPLICATION" in cat or "APPLY" in cat:
        return {
            "en": [
                "Eligible for regular Class 8 students studying in Govt & Govt-aided schools.",
                "Annual family income of parents must not exceed ₹3,50,000/- from all sources.",
                "Selected scholars receive ₹12,000/year scholarship directly into bank account via DBT."
            ],
            "hi": [
                "सरकारी एवं अनुदानित विद्यालयों में कक्षा 8वीं में अध्ययनरत नियमित छात्र पात्र हैं।",
                "अभिभावक की वार्षिक आय सभी स्रोतों से ₹3,50,000 से अधिक नहीं होनी चाहिए।",
                "चयनित छात्रों को प्रति वर्ष ₹12,000 छात्रवृत्ति सीधे बैंक खाते में (DBT द्वारा) मिलती है।"
            ]
        }
    elif "ANSWER" in cat:
        return {
            "en": [
                "Provisional answer key released for MAT (Mental Ability) and SAT (Scholastic Ability).",
                "Students can cross-check their responses and calculate estimated scores.",
                "Submit objections/challenges online before the specified last date."
            ],
            "hi": [
                "मैट (MAT) एवं सैट (SAT) की आधिकारिक प्रोविजनल उत्तर कुंजी (Answer Key) जारी।",
                "छात्र अपने उत्तरों का मिलान कर संभावित प्राप्तांक का आकलन कर सकते हैं।",
                "किसी उत्तर पर आपत्ति होने पर निर्धारित अंतिम तिथि से पूर्व ऑनलाइन आपत्ति दर्ज करें।"
            ]
        }
    elif "EXTEN" in cat:
        return {
            "en": [
                "NMMS scholarship online application deadline has been officially extended.",
                "Great opportunity for eligible students who could not complete registration earlier.",
                "Complete online registration and submit documents to school before the extended date."
            ],
            "hi": [
                "NMMS छात्रवृत्ति ऑनलाइन आवेदन की अंतिम तिथि आगे बढ़ा दी गई है।",
                "जो छात्र पहले आवेदन नहीं कर पाए थे, उनके लिए फॉर्म भरने का यह सुनहरा मौका है।",
                "अंतिम तिथि से पहले ऑनलाइन आवेदन पूरा कर आवश्यक दस्तावेज स्कूल में जमा करें।"
            ]
        }
    elif "QUESTION" in cat:
        return {
            "en": [
                "Official NMMS sample question papers and previous year papers available.",
                "Exam format: MAT (90 Marks) and SAT (90 Marks) - Total 180 Marks.",
                "Practice these model papers to understand question pattern and time management."
            ],
            "hi": [
                "NMMS परीक्षा हेतु आधिकारिक मॉडल प्रश्न पत्र व अभ्यास सेट उपलब्ध कराए गए हैं।",
                "परीक्षा में दो भाग होंगे: मानसिक योग्यता (MAT - 90 अंक) व शैक्षिक योग्यता (SAT - 90 अंक)।",
                "छात्र परीक्षा पैटर्न और समय प्रबंधन समझने हेतु इन प्रश्न पत्रों का अभ्यास अवश्य करें।"
            ]
        }
    else:
        return {
            "en": [
                "Official notification issued by the State Examination Board / SCERT.",
                "All concerned students, teachers, and school heads should review the instructions.",
                "Check the official portal link below for complete circular details."
            ],
            "hi": [
                "राज्य शिक्षा बोर्ड / SCERT द्वारा आधिकारिक सूचना एवं दिशा-निर्देश जारी।",
                "संबंधित सभी छात्र, शिक्षक एवं विद्यालय प्रधान निर्देशों का अध्ययन अवश्य करें।",
                "विस्तृत जानकारी हेतु नीचे दिए गए लिंक से आधिकारिक नोटिस डाउनलोड करें।"
            ]
        }

def analyze_notice_with_groq(state: str, title: str, notice_url: str = "") -> dict:
    """
    Uses Groq AI (qwen/qwen3.8-27b) to deeply understand the notice and extract exact dates & category.
    Guarantees robust bilingual highlights even on partial or missing responses.
    """
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        return {}

    extracted_text = ""
    if notice_url and notice_url.startswith("http"):
        extracted_text = extract_content_from_url(notice_url)

    combined_input = f"""State: {state}
Headline/Notice Title: {title}
Notice Document/Webpage Content:
{extracted_text if extracted_text else 'No additional document text available. Analyze from headline.'}"""

    system_prompt = """You are an expert Indian education scholarship analyst for the National Means-cum-Merit Scholarship (NMMS).
Analyze the given notice text carefully.
Identify the exact category:
1. RESULT: Selected candidates list, district cutoff, next steps for scholarship DBT via NSP.
2. ADMIT_CARD: Hall ticket download, exam day reporting, guidelines.
3. APPLICATION_FORM: Class 8 eligibility, Rs 12,000/yr scholarship benefit, school verification.
4. ANSWER_KEY: Provisional key, objection window, marks calculation.
5. QUESTION_PAPER: Model paper, exam pattern practice.
6. DATE_EXTENSION: Revised deadline, reasons, final warning.
7. CIRCULAR: General administrative guidelines.

Extract exact dates if present (or null if not an application form).
Provide 2-3 specific, actionable, fact-filled bullet points in both English and Hindi tailored directly to this notice type.

Return ONLY valid JSON with this exact structure:
{
  "category": "APPLICATION_FORM" | "ADMIT_CARD" | "RESULT" | "ANSWER_KEY" | "QUESTION_PAPER" | "DATE_EXTENSION" | "CIRCULAR",
  "clean_title": "Clear concise 1-line title in English",
  "start_date": "Exact start date e.g. 15 Oct 2026 or null",
  "last_date": "Exact last date e.g. 30 Nov 2026 or null",
  "exam_date": "Exact exam date e.g. 17 Jan 2027 or null",
  "highlights_en": [
    "Point 1 with exact facts/instructions",
    "Point 2 with exact facts/instructions",
    "Point 3 with exact facts/instructions"
  ],
  "highlights_hi": [
    "बिंदु 1 सटीक तथ्य एवं निर्देश",
    "बिंदु 2 सटीक तथ्य एवं निर्देश",
    "बिंदु 3 सटीक तथ्य एवं निर्देश"
  ]
}
Important: Output ONLY the JSON object, no markdown code fence, no text outside JSON."""

    try:
        client = Groq(api_key=api_key)
        chat_completion = client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": combined_input}
            ],
            model="qwen/qwen3.8-27b",
            temperature=0.1,
            response_format={"type": "json_object"}
        )
        response_text = chat_completion.choices[0].message.content
        data = json.loads(response_text)
        
        # Verify and supplement highlights if empty
        category = data.get("category", "CIRCULAR")
        fallback = get_fallback_highlights(category)
        if not data.get("highlights_en") or not isinstance(data.get("highlights_en"), list) or len(data.get("highlights_en")) == 0:
            data["highlights_en"] = fallback["en"]
        if not data.get("highlights_hi") or not isinstance(data.get("highlights_hi"), list) or len(data.get("highlights_hi")) == 0:
            data["highlights_hi"] = fallback["hi"]

        return data
    except Exception as e:
        logger.error(f"Groq AI analysis error: {e}")
        return {}
