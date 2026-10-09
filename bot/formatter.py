import re
import html

def detect_notification_category(title: str, update_type: str = ""):
    """
    Reads and analyzes the notice text and AI category to detect its exact type.
    """
    combined = f"{title} {update_type}".lower()

    if any(k in combined for k in ["admit card", "hall ticket", "admit-card", "roll no", "admit_card"]):
        return {
            "type": "ADMIT_CARD",
            "badge": "🎫 <b>NMMS ADMIT CARD RELEASED</b>",
            "action_btn": "🎫 Download Admit Card",
            "summary": "Admit Cards are now available for download. Download before the exam date!"
        }

    if any(k in combined for k in ["result", "merit list", "selected list", "selection list", "marks"]):
        return {
            "type": "RESULT",
            "badge": "🏆 <b>NMMS RESULT / MERIT LIST DECLARED</b>",
            "action_btn": "🏆 Check Result / Merit List",
            "summary": "NMMS Examination Result & Selected Candidate List has been published!"
        }

    if any(k in combined for k in ["answer key", "ans key", "objection", "model key", "answer_key"]):
        return {
            "type": "ANSWER_KEY",
            "badge": "📝 <b>NMMS OFFICIAL ANSWER KEY RELEASED</b>",
            "action_btn": "📝 Check Official Answer Key",
            "summary": "Official Provisional Answer Key released. Check answers and file objections if any."
        }

    if any(k in combined for k in ["extended", "extension", "last date extend", "date badha", "date_extension"]):
        return {
            "type": "DATE_EXTENSION",
            "badge": "⏰ <b>NMMS LAST DATE EXTENDED</b>",
            "action_btn": "🌐 Apply Extended Form",
            "summary": "Application deadline has been extended! Students who missed earlier can now apply."
        }

    if any(k in combined for k in ["question paper", "model paper", "previous year", "sample paper", "practice paper", "question_paper"]):
        return {
            "type": "QUESTION_PAPER",
            "badge": "📚 <b>NMMS QUESTION / MODEL PAPER OUT</b>",
            "action_btn": "📚 Download Question Paper",
            "summary": "Official NMMS practice question paper uploaded for students."
        }

    if any(k in combined for k in ["exam date", "schedule", "time table", "pariksha tithi", "exam_date"]):
        return {
            "type": "EXAM_DATE",
            "badge": "📅 <b>NMMS EXAM DATE ANNOUNCED</b>",
            "action_btn": "📅 View Exam Schedule",
            "summary": "Official NMMS Examination date and time table announced by the department."
        }

    if any(k in combined for k in ["apply", "registration", "online form", "application", "aavedan", "application_form"]):
        return {
            "type": "APPLICATION_FORM",
            "badge": "🟢 <b>NMMS NEW APPLICATION FORM LIVE</b>",
            "action_btn": "🌐 Apply Online Form",
            "summary": "NMMS Scholarship Online Application Form is now open for Class 8 students."
        }

    # Default general notice
    return {
        "type": "CIRCULAR",
        "badge": "📄 <b>NMMS OFFICIAL CIRCULAR / UPDATE</b>",
        "action_btn": "📄 View Official Notice",
        "summary": "New official circular / update issued by the State Education Department."
    }

def format_nmms_notification(
    state: str,
    authority: str,
    update_type: str,
    title: str,
    apply_start: str = "",
    last_date: str = "",
    exam_date: str = "",
    apply_link: str = "",
    pdf_link: str = "",
    highlights_en: list = None,
    highlights_hi: list = None,
    summary_en: str = "",
    summary_hi: str = ""
) -> str:
    """
    Smart contextual notification with English & Hindi bilingual AI bullet points.
    """
    category = detect_notification_category(title, update_type)
    target_link = pdf_link if (pdf_link and pdf_link.startswith("http")) else apply_link
    if not target_link or not target_link.startswith("http"):
        target_link = "https://scholarships.gov.in"

    safe_title = html.escape(title.strip())
    safe_state = html.escape(state.strip().upper())
    safe_authority = html.escape(authority.strip())

    # Build Highlights Block (Bilingual English + Hindi)
    en_points = highlights_en or ([summary_en] if summary_en else [])
    hi_points = highlights_hi or ([summary_hi] if summary_hi else [])

    summary_block = ""
    if en_points or hi_points:
        summary_block = "━━━━━━━━━━━━━━━━━━━━━\n📌 <b>KEY HIGHLIGHTS / मुख्य बिंदु:</b>\n"
        if en_points:
            summary_block += "\n🇬🇧 <b>English:</b>\n"
            for pt in en_points:
                clean_pt = html.escape(str(pt).strip().lstrip("•- "))
                summary_block += f"• {clean_pt}\n"
        if hi_points:
            summary_block += "\n🇮🇳 <b>हिंदी:</b>\n"
            for pt in hi_points:
                clean_pt = html.escape(str(pt).strip().lstrip("•- "))
                summary_block += f"• {clean_pt}\n"

    # Contextual dates content based on category or present dates
    has_dates = bool(apply_start or last_date or exam_date)
    dates_content = ""
    if category["type"] in ["APPLICATION_FORM", "DATE_EXTENSION", "EXAM_DATE"] or has_dates:
        dates_content = f"""━━━━━━━━━━━━━━━━━━━━━
📅 <b>IMPORTANT DATES:</b>
🟢 <b>Start Date :</b> <b>{html.escape(apply_start or 'Active Now')}</b>
🔴 <b>Last Date   :</b> <b>⚡ {html.escape(last_date or 'Check Circular')} ⚡</b>
🟡 <b>Exam Date   :</b> <b>{html.escape(exam_date or 'To be notified')}</b>
"""

    message = f"""{category['badge']}

📍 <b>State:</b> <b><u>{safe_state}</u></b>
🏢 <b>Authority:</b> {safe_authority}
📝 <b>Notice:</b> <b>{safe_title}</b>

{summary_block}{dates_content}━━━━━━━━━━━━━━━━━━━━━
👉 <a href="{target_link}"><b>🔗 Click Here to View / Download Notice</b></a>

━━━━━━━━━━━━━━━━━━━━━
🎓 <b>Sagar Coaching Centre, Bhagwanpur</b>
▶️ <b>YouTube:</b> <a href="https://www.youtube.com/@sagarcoachingcentrebhagwanpur">Sagar Coaching Centre Bhagwanpur</a>
📞 <b>Call / WhatsApp:</b> +91 91101 13671
"""
    return message
