"""
Hindi Telegram Message Formatter for NMMS Bot.
Strictly generates Hindi messages formatted as:
[event emoji + name] | State | What happened | Date | Official button/PDF

Escapes all dynamic strings using html.escape and trims text to 4000 chars.
"""

import re
import html
from typing import List, Dict, Optional

HINDI_STATE_NAMES = {
    "bihar": "बिहार",
    "uttar pradesh": "उत्तर प्रदेश",
    "rajasthan": "राजस्थान",
    "madhya pradesh": "मध्य प्रदेश",
    "haryana": "हरियाणा",
    "delhi": "दिल्ली",
    "jharkhand": "झारखंड",
    "chhattisgarh": "छत्तीसगढ़",
    "himachal pradesh": "हिमाचल प्रदेश",
    "uttarakhand": "उत्तराखंड",
    "central": "केंद्र सरकार (राष्ट्रीय स्तर)",
    "central (nsp)": "केंद्र सरकार (NSP पोर्टल)"
}

EVENT_META = {
    "FORM_START": {
        "header": "🟢 <b>नया आवेदन शुरू (Application Form Live)</b>",
        "btn": "🌐 ऑनलाइन आवेदन करें"
    },
    "LAST_DATE": {
        "header": "🔴 <b>आवेदन की अंतिम तिथि (Last Date)</b>",
        "btn": "🌐 अंतिम तिथि से पहले आवेदन करें"
    },
    "EXTENSION": {
        "header": "⏰ <b>अंतिम तिथि बढ़ाई गई (Date Extended)</b>",
        "btn": "🌐 विस्तृत तिथि पर आवेदन करें"
    },
    "CORRECTION": {
        "header": "✏️ <b>आवेदन संशोधन विंडो (Correction Window)</b>",
        "btn": "✏️ फॉर्म में सुधार / संशोधन करें"
    },
    "EXAM_DATE": {
        "header": "📅 <b>परीक्षा तिथि घोषित (Exam Date Announced)</b>",
        "btn": "📅 परीक्षा कार्यक्रम देखें"
    },
    "ADMIT_CARD": {
        "header": "🎫 <b>प्रवेश पत्र जारी (Admit Card Released)</b>",
        "btn": "🎫 एडमिट कार्ड डाउनलोड करें"
    },
    "ANSWER_KEY": {
        "header": "📝 <b>आधिकारिक उत्तर कुंजी जारी (Answer Key Released)</b>",
        "btn": "📝 उत्तर कुंजी व आपत्ति दर्ज करें"
    },
    "RESULT": {
        "header": "🏆 <b>परीक्षा परिणाम / मेरिट सूची (Result Declared)</b>",
        "btn": "🏆 रिजल्ट व मेरिट लिस्ट देखें"
    },
    "NSP_APPLY": {
        "header": "🌐 <b>NSP छात्रवृत्ति आवेदन (NSP Apply Update)</b>",
        "btn": "🌐 scholarships.gov.in पर जाएं"
    },
    "NSP_OTHER": {
        "header": "🏛️ <b>NSP आधिकारिक सूचना (NSP Update)</b>",
        "btn": "🌐 आधिकारिक पोर्टल देखें"
    }
}

def get_hindi_state(state: str) -> str:
    s_clean = (state or "").strip().lower()
    return HINDI_STATE_NAMES.get(s_clean, state)

def get_event_meta(event_type: str) -> dict:
    e_clean = (event_type or "").strip().upper()
    return EVENT_META.get(e_clean, {
        "header": "📢 <b>NMMS आधिकारिक सूचना (Official Update)</b>",
        "btn": "📄 आधिकारिक सूचना देखें"
    })

def clean_title_no_midword_truncation(text: str, max_len: int = 80) -> str:
    """Truncates title cleanly without cutting mid-word."""
    if not text or len(text) <= max_len:
        return text or ""
    sub = text[:max_len]
    last_space = sub.rfind(" ")
    if last_space > max_len // 2:
        return sub[:last_space].strip()
    return sub.strip()

def format_hindi_nmms_notification(
    state: str,
    event_type: str,
    title: str,
    summary_hi: str,
    dates: Optional[List[Dict[str, str]]] = None,
    last_date: str = "",
    exam_date: str = "",
    official_url: str = "",
    pdf_url: str = "",
    title_hi: str = "",
    is_news_corroborated: bool = False
) -> str:
    """
    Builds the Telegram message strictly in Hindi.
    Format:
    [event emoji + name]
    राज्य: {state}
    क्या हुआ: {summary_hi}
    महत्वपूर्ण तिथियां: {dates}
    आधिकारिक लिंक
    """
    meta = get_event_meta(event_type)
    state_hi = html.escape(get_hindi_state(state))
    display_title = title_hi.strip() if title_hi else clean_title_no_midword_truncation(title, 80)
    safe_title = html.escape(display_title)
    safe_summary = html.escape((summary_hi or safe_title).strip())

    # Dates block (do not print fake dates like session strings '2024-25')
    date_lines = []
    if dates:
        for d in dates:
            lbl = html.escape(str(d.get("label", "तिथि")).strip())
            val = str(d.get("value", "")).strip()
            if val and not re.match(r'^\d{4}[-/]\d{2,4}$', val):
                date_lines.append(f"• <b>{lbl}:</b> {html.escape(val)}")

    if not date_lines:
        if last_date and not re.match(r'^\d{4}[-/]\d{2,4}$', last_date):
            date_lines.append(f"• <b>अंतिम तिथि:</b> {html.escape(last_date)}")
        if exam_date and not re.match(r'^\d{4}[-/]\d{2,4}$', exam_date):
            date_lines.append(f"• <b>परीक्षा तिथि:</b> {html.escape(exam_date)}")

    dates_section = ""
    if date_lines:
        dates_section = "━━━━━━━━━━━━━━━━━━━━━\n📅 <b>महत्वपूर्ण तिथियां (Important Dates):</b>\n" + "\n".join(date_lines) + "\n"

    target_link = pdf_url if (pdf_url and pdf_url.startswith("http")) else (official_url or "https://scholarships.gov.in")
    safe_link = html.escape(target_link)
    link_text = "📄 आधिकारिक नोटिस (PDF) यहाँ देखें" if (pdf_url and pdf_url.startswith("http")) else "🌐 आधिकारिक वेबसाइट पर जाएँ"

    disclaimer_line = "⚠️ <i>यह सूचना समाचार रिपोर्टों पर आधारित है, कृपया आधिकारिक पोर्टल पर पुष्टि करें।</i>\n\n" if is_news_corroborated else ""

    raw_message = f"""{meta['header']}

📍 <b>राज्य (State):</b> <b><u>{state_hi}</u></b>
📋 <b>विषय:</b> <b>{safe_title}</b>

━━━━━━━━━━━━━━━━━━━━━
ℹ️ <b>मुख्य विवरण (What Happened):</b>
{safe_summary}

{dates_section}━━━━━━━━━━━━━━━━━━━━━
{disclaimer_line}👉 <a href="{safe_link}"><b>{link_text}</b></a>

━━━━━━━━━━━━━━━━━━━━━
🎓 <b>सागर कोचिंग सेंटर, भगवानपुर</b>
▶️ <b>YouTube:</b> <a href="https://www.youtube.com/@sagarcoachingcentrebhagwanpur">Sagar Coaching Centre Bhagwanpur</a>
📞 <b>Call / WhatsApp:</b> +91 91101 13671
"""
    # Trim to 4000 characters
    if len(raw_message) > 4000:
        raw_message = raw_message[:3990] + "\n..."

    return raw_message
