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

def analyze_notice_with_groq(state: str, title: str, notice_url: str = "") -> dict:
    """
    Uses Groq AI (qwen/qwen3.8-27b) to deeply understand the notice and extract exact dates & category.
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
Extract the exact information and return ONLY valid JSON with this exact structure:
{
  "category": "APPLICATION_FORM" | "ADMIT_CARD" | "RESULT" | "ANSWER_KEY" | "QUESTION_PAPER" | "DATE_EXTENSION" | "CIRCULAR",
  "clean_title": "Clear concise 1-line title in English",
  "start_date": "Exact start date e.g. 15 Oct 2026 or null if not applicable",
  "last_date": "Exact last date e.g. 30 Nov 2026 or null if not applicable",
  "exam_date": "Exact exam date e.g. 17 Jan 2027 or null if not applicable",
  "summary_en": "1 short crisp sentence in English explaining what this notice is about",
  "summary_hi": "1 short simple sentence in Hindi (देवनागरी लिपि) explaining what this notice is about"
}
Important:
- If this is a question paper, syllabus, or result, set start_date, last_date to null.
- Extract actual dates from the document text if present.
- Output ONLY the JSON block, no markdown, no explanation."""

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
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Groq AI analysis error: {e}")
        return {}
