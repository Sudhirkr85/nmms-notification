def format_nmms_notification(
    state: str,
    authority: str,
    update_type: str,
    title: str,
    apply_start: str = "Announced",
    last_date: str = "Check notice",
    exam_date: str = "To be announced",
    apply_link: str = "",
    pdf_link: str = ""
) -> str:
    """
    Super clean, short and direct notification format.
    """
    target_link = pdf_link if (pdf_link and pdf_link.startswith("http")) else apply_link
    if not target_link or not target_link.startswith("http"):
        target_link = "https://scholarships.gov.in"

    message = f"""📢 <b>NMMS NOTIFICATION</b> 🔔

📍 <b>State:</b> <b><u>{state.upper()}</u></b>
📝 <b>Notice:</b> <b>{title}</b>

━━━━━━━━━━━━━━━━━━━━━
📅 <b>DATES:</b>
🟢 <b>Start Date:</b> <a href="{target_link}"><b>{apply_start}</b></a>
🔴 <b>Last Date:</b> <a href="{target_link}"><b>⚡ {last_date} ⚡</b></a>
🟡 <b>Exam Date:</b> <a href="{target_link}"><b>{exam_date}</b></a>
━━━━━━━━━━━━━━━━━━━━━

👉 <a href="{target_link}"><b>🔗 Click Here to View Full Notification</b></a>

━━━━━━━━━━━━━━━━━━━━━
🎓 <b>Sagar Coaching Centre, Bhagwanpur</b>
▶️ <b>YouTube:</b> <a href="https://www.youtube.com/@sagarcoachingcentrebhagwanpur">Sagar Coaching Centre Bhagwanpur</a>
📞 <b>Call / WhatsApp:</b> +91 91101 13671
"""
    return message
