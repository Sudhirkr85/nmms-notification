import re

def detect_notification_category(title: str, text: str = ""):
    """
    Reads and analyzes the notice text to detect its exact type.
    """
    combined = f"{title} {text}".lower()

    if any(k in combined for k in ["admit card", "hall ticket", "admit-card", "roll no"]):
        return {
            "type": "ADMIT_CARD",
            "badge": "🎫 <b>ADMIT CARD RELEASED</b>",
            "action_btn": "🎫 Download Admit Card",
            "summary": "Admit Cards are now available for download. Download before the exam date!"
        }

    if any(k in combined for k in ["result", "merit list", "selected list", "selection list", "marks"]):
        return {
            "type": "RESULT",
            "badge": "🏆 <b>RESULT / MERIT LIST DECLARED</b>",
            "action_btn": "🏆 Check Result / Merit List",
            "summary": "NMMS Examination Result & Selected Candidate List has been published!"
        }

    if any(k in combined for k in ["answer key", "ans key", "objection", "model key"]):
        return {
            "type": "ANSWER_KEY",
            "badge": "📝 <b>OFFICIAL ANSWER KEY RELEASED</b>",
            "action_btn": "📝 Check Official Answer Key",
            "summary": "Official Provisional Answer Key released. Check answers and file objections if any."
        }

    if any(k in combined for k in ["extended", "extension", "last date extend", "date badha"]):
        return {
            "type": "DATE_EXTENSION",
            "badge": "⏰ <b>APPLICATION LAST DATE EXTENDED</b>",
            "action_btn": "🌐 Apply Extended Form",
            "summary": "Application deadline has been extended! Students who missed earlier can now apply."
        }

    if any(k in combined for k in ["question paper", "model paper", "previous year", "sample paper", "practice paper"]):
        return {
            "type": "QUESTION_PAPER",
            "badge": "📚 <b>QUESTION PAPER / MODEL PAPER OUT</b>",
            "action_btn": "📚 Download Question Paper",
            "summary": "Official NMMS practice question paper uploaded for students."
        }

    if any(k in combined for k in ["exam date", "schedule", "time table", "pariksha tithi"]):
        return {
            "type": "EXAM_DATE",
            "badge": "📅 <b>EXAM DATE ANNOUNCED</b>",
            "action_btn": "📅 View Exam Schedule",
            "summary": "Official NMMS Examination date and time table announced by the department."
        }

    if any(k in combined for k in ["apply", "registration", "online form", "application", "aavedan"]):
        return {
            "type": "APPLICATION_FORM",
            "badge": "🟢 <b>NEW APPLICATION FORM LIVE</b>",
            "action_btn": "🌐 Apply Online Form",
            "summary": "NMMS Scholarship Online Application Form is now open for Class 8 students."
        }

    # Default general notice
    return {
        "type": "CIRCULAR",
        "badge": "📄 <b>OFFICIAL CIRCULAR / NOTIFICATION</b>",
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
    pdf_link: str = ""
) -> str:
    """
    Smart contextual notification: reads the notice and customizes message accordingly.
    """
    category = detect_notification_category(title)
    target_link = pdf_link if (pdf_link and pdf_link.startswith("http")) else apply_link
    if not target_link or not target_link.startswith("http"):
        target_link = "https://scholarships.gov.in"

    # Contextual body content based on category
    if category["type"] in ["APPLICATION_FORM", "DATE_EXTENSION"]:
        # Only show dates if actual dates are present
        dates_content = f"""━━━━━━━━━━━━━━━━━━━━━
📅 <b>IMPORTANT DATES:</b>
🟢 <b>Start Date :</b> <a href="{target_link}"><b>{apply_start or 'Active Now'}</b></a>
🔴 <b>Last Date   :</b> <a href="{target_link}"><b>⚡ {last_date or 'Check Circular'} ⚡</b></a>
🟡 <b>Exam Date   :</b> <a href="{target_link}"><b>{exam_date or 'To be notified'}</b></a>
━━━━━━━━━━━━━━━━━━━━━"""
    else:
        # Result, Question paper, Admit card etc.
        dates_content = f"""━━━━━━━━━━━━━━━━━━━━━
ℹ️ <b>UPDATE INFO:</b>
{category['summary']}
━━━━━━━━━━━━━━━━━━━━━"""

    message = f"""{category['badge']}

📍 <b>State:</b> <b><u>{state.upper()}</u></b>
🏢 <b>Authority:</b> {authority}
📝 <b>Notice:</b> <b>{title}</b>

{dates_content}

👉 <a href="{target_link}"><b>🔗 Click Here to View / Download Notice</b></a>

━━━━━━━━━━━━━━━━━━━━━
🎓 <b>Sagar Coaching Centre, Bhagwanpur</b>
▶️ <b>YouTube:</b> <a href="https://www.youtube.com/@sagarcoachingcentrebhagwanpur">Sagar Coaching Centre Bhagwanpur</a>
📞 <b>Call / WhatsApp:</b> +91 91101 13671
"""
    return message
