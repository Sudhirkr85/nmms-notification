import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from dotenv import load_dotenv
load_dotenv()
from bot.telegram_poster import send_telegram_message

welcome_msg = """📢 <b>WELCOME TO NMMS SCHOLARSHIP UPDATES CHANNEL</b> 🔔

Welcome to the official NMMS exam updates channel powered by <b>Sagar Coaching Centre Bhagwanpur</b>!

🎯 <b>What You Will Get Here:</b>
▪️ Real-time NMMS notification alerts for All States
▪️ Direct links to official circulars & forms
▪️ Date alerts (Start date, Last date & Exam date)
▪️ Urgent reminders before application deadlines
▪️ Free preparation classes & video solutions

━━━━━━━━━━━━━━━━━━━━━
🎓 <b>Sagar Coaching Centre, Bhagwanpur (Supaul)</b>
▶️ <b>YouTube:</b> <a href="https://www.youtube.com/@sagarcoachingcentrebhagwanpur">Sagar Coaching Centre Bhagwanpur</a>
🌐 <b>Website:</b> <a href="https://sagarcoaching.tech/">sagarcoaching.tech</a>
📲 <b>Mobile App:</b> <a href="https://play.google.com/store/apps/details?id=com.lct.pbxwdta">Download on Play Store</a>
📞 <b>Call / WhatsApp:</b> +91 91101 13671

<i>💡 Forward this channel to Class 8 students, parents, and school teachers!</i>"""

res = send_telegram_message(welcome_msg, apply_url="https://sagarcoaching.tech/")
print("WELCOME POST RESULT:", res)
