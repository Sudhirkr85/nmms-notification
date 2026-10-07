import os

def format_nmms_notification(
    state: str,
    authority: str,
    update_type: str,
    title: str,
    apply_start: str = "Announced / Open",
    last_date: str = "Check official portal",
    exam_date: str = "To be notified",
    apply_link: str = "",
    pdf_link: str = ""
) -> str:
    """
    Format a clean HTML/Markdown notification for Telegram channel
    with clickable links and Sagar Coaching Centre branding.
    """
    coaching_name = os.getenv("COACHING_NAME", "Sagar Coaching Centre, Bhagwanpur")
    coaching_phone = os.getenv("COACHING_PHONE", "+91 91101 13671")
    coaching_yt = os.getenv("COACHING_YOUTUBE", "Sagar Coaching Centre Bhagwanpur")
    coaching_tg = os.getenv("COACHING_TELEGRAM", "https://t.me/ShrvanKumarSagar")

    # Sagar Coaching Priority: Home State Check
    is_bihar = "bihar" in state.lower()
    if is_bihar:
        header_banner = "🌟 <b>[BIHAR STATE SPECIAL ALERT]</b> 🌟\n🎯 <b>SAGAR COACHING CENTRE HOME STATE</b>"
    else:
        header_banner = "📢 <b>NMMS SCHOLARSHIP ALERT</b> 🔔"

    # Clean direct notice link (PDF or Web link)
    active_notice_link = pdf_link if (pdf_link and pdf_link.startswith("http")) else apply_link
    if not active_notice_link or not active_notice_link.startswith("http"):
        active_notice_link = "https://scholarships.gov.in"

    # Vibrant Date Styling: Colored link text renders in vivid blue/accent color in Telegram
    date_section = f"""📅 <b>IMPORTANT DATES:</b>
<blockquote>🟢 <b>Application Start :</b> <a href="{active_notice_link}"><b>{apply_start}</b></a>
🔴 <b>Last Date to Apply :</b> <a href="{active_notice_link}"><b>⚡ {last_date} ⚡</b></a>
🟡 <b>NMMS Exam Date     :</b> <a href="{active_notice_link}"><b>{exam_date}</b></a></blockquote>"""

    message = f"""{header_banner}

📍 <b>STATE:</b> <b><u>{state.upper()}</u></b>
🏛️ <b>AUTHORITY:</b> {authority}
📋 <b>STATUS:</b> <b>{update_type}</b>

━━━━━━━━━━━━━━━━━━━━━
📢 <b>NOTIFICATION DETAILS:</b>
<b>{title}</b>
━━━━━━━━━━━━━━━━━━━━━

{date_section}

━━━━━━━━━━━━━━━━━━━━━
🔗 <b>OFFICIAL NOTICE / APPLY LINK:</b>
👉 <a href=\"{active_notice_link}\">Click Here to View / Download Official Notification</a>
━━━━━━━━━━━━━━━━━━━━━

💡 <b>Guidance By: {coaching_name}</b>
📍 Bhagwanpur, Supaul, Bihar
📞 <b>Call / WhatsApp:</b> {coaching_phone}
▶️ <b>YouTube:</b> {coaching_yt}
💬 <b>Telegram:</b> <a href=\"{coaching_tg}\">Join Official Group</a>

#{state.replace(' ', '_')} #NMMS #Scholarship #SagarCoaching
"""
    return message
