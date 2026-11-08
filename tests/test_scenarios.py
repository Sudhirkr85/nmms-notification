"""
Verification Script for NMMS Scraper 3 Scenarios:
(a) Expired-date notice is rejected
(b) Same event twice results in one post
(c) With GROQ key removed, nothing is posted
"""

import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Explicitly declare test mode for storage isolation
os.environ["NMMS_TEST_MODE"] = "1"
os.environ["MONGO_URI"] = ""
os.environ["GROQ_API_KEY"] = "mock_key_for_test"

from unittest.mock import patch

import main

# Mock external network extraction to prevent real HTTP delays during unit tests
patch("main.extract_content_from_source", return_value="NMMS scholarship test context").start()

print("=================================================================")
print("RUNNING 9 TEST SCENARIOS AS REQUIRED")
print("=================================================================\n")

# ----------------- Scenario (a): Expired-date notice is rejected ----------------- #
print("--- SCENARIO (a): Expired-Date Notice is Rejected ---")
expired_notice = {
    "state": "Bihar",
    "title": "Bihar NMMS Scholarship Online Application Form 2026",
    "update_type": "APPLICATION_FORM",
    "apply_link": "https://scert.bihar.gov.in",
    "pdf_link": "",
    "apply_start": "01 October 2026",
    "last_date": "15 October 2026", # Expired in IST relative to today (08 Nov 2026)
    "content_context": "Last date to apply was 15 October 2026."
}

# Mock AI accepting it to prove code-level check overrides AI:
mock_ai_accept = {
    "is_error": False,
    "decision": "ACCEPT",
    "event_type": "FORM_START",
    "dates": [{"label": "Last Date", "value": "15 October 2026", "evidence_quote": "15 October 2026"}],
    "summary_hi": "बिहार NMMS आवेदन अंतिम तिथि 15 अक्टूबर 2026 थी।",
    "summary_en": "Bihar NMMS application deadline was 15 October 2026.",
    "confidence": "high",
    "reason": "AI accepted notice mistakenly"
}

with patch("main.analyze_notice_with_groq_pipeline", return_value=mock_ai_accept), \
     patch("main.send_telegram_message") as mock_send:
    result_a = main.process_and_post_notice(expired_notice)
    print(f"Result (Msg ID): {result_a}")
    print(f"Telegram send called: {mock_send.called}")
    assert result_a == 0
    assert not mock_send.called
    print("-> PASS: Expired-date notice was rejected at code level before posting!\n")

# ----------------- Scenario (b): Same event twice results in one post ----------------- #
print("--- SCENARIO (b): Same Event Twice Results in Only One Post ---")
valid_event = {
    "state": "Uttar Pradesh",
    "title": "UP NMMS 2027-28 Provisional Answer Key Out",
    "update_type": "ANSWER_KEY",
    "apply_link": "https://scert.up.gov.in",
    "pdf_link": "https://scert.up.gov.in/Answer_Key.pdf",
    "apply_start": "Active Now",
    "last_date": "13 November 2026",
    "exam_date": "01 November 2026",
    "content_context": "UP NMMS provisional answer key released on 13 November 2026."
}

mock_ai_key = {
    "is_error": False,
    "decision": "ACCEPT",
    "event_type": "ANSWER_KEY",
    "dates": [{"label": "Objection Date", "value": "13 November 2026", "evidence_quote": "13 November 2026"}],
    "summary_hi": "उत्तर प्रदेश NMMS परीक्षा की उत्तर कुंजी जारी।",
    "summary_en": "UP NMMS Answer Key released.",
    "confidence": "high",
    "reason": "Official answer key"
}

with patch("main.analyze_notice_with_groq_pipeline", return_value=mock_ai_key), \
     patch("main.send_telegram_message", return_value=101) as mock_send_b, \
     patch("main.send_telegram_document", return_value=102):
    
    # 1st run: Should post
    first_post_id = main.process_and_post_notice(valid_event)
    print(f"1st Occurrence - Result (Msg ID): {first_post_id} (Post Count: {mock_send_b.call_count})")
    
    # 2nd run: Exact same event sent again
    second_post_id = main.process_and_post_notice(valid_event)
    print(f"2nd Occurrence - Result (Msg ID): {second_post_id} (Post Count: {mock_send_b.call_count})")
    
    assert first_post_id == 101
    assert second_post_id == 0
    assert mock_send_b.call_count == 1
    print("-> PASS: Same event twice resulted in exactly ONE post!\n")

# ----------------- Scenario (c): With GROQ key removed, nothing is posted ----------------- #
print("--- SCENARIO (c): With GROQ Key Removed, Nothing is Posted ---")
os.environ["GROQ_API_KEY"] = "" # Key removed

test_notice_c = {
    "state": "Rajasthan",
    "title": "Rajasthan NMMS 2026 Online Application Form Open",
    "update_type": "APPLICATION_FORM",
    "apply_link": "https://rajshaladarpan.nic.in",
    "pdf_link": "",
    "apply_start": "Active Now",
    "last_date": "25 November 2026",
    "content_context": "Rajasthan NMMS form active."
}

with patch("main.send_telegram_message") as mock_send_c:
    result_c = main.process_and_post_notice(test_notice_c)
    print(f"Result (Msg ID): {result_c}")
    print(f"Telegram send called: {mock_send_c.called}")
    assert result_c == 0
    assert not mock_send_c.called
    print("-> PASS: Fail-closed gatekeeper prevented any post without GROQ_API_KEY!\n")

# ----------------- Scenario (d): Central Nov 15 Extension via Delhi, Jharkhand, UK ----------------- #
print("--- SCENARIO (d): Same Nov 15 Extension via 3 States Produces Exactly ONE Post ---")
os.environ["GROQ_API_KEY"] = "mock_key_for_test"

ext_delhi = {
    "state": "Delhi",
    "title": "Union Education Ministry extends NMMSS scholarship application deadline till Nov 15",
    "update_type": "EXTENSION",
    "apply_link": "https://scholarships.gov.in",
    "pdf_link": "",
    "last_date": "15 November 2026",
    "content_context": "Ministry of Education has extended the deadline to 15 November 2026 on scholarships.gov.in."
}
ext_jharkhand = {
    "state": "Jharkhand",
    "title": "NMMS Scholarship 2026-27: Last Date Extended to November 15; Fresh Applications Still Below One Lakh",
    "update_type": "EXTENSION",
    "apply_link": "https://scholarships.gov.in",
    "pdf_link": "",
    "last_date": "15 November 2026",
    "content_context": "Ministry of Education extends deadline to 15 November 2026 on scholarships.gov.in."
}
ext_uk = {
    "state": "Uttarakhand",
    "title": "NMMSS 2026-27: Ministry of Education extends scholarship application deadline to November 15",
    "update_type": "EXTENSION",
    "apply_link": "https://scholarships.gov.in",
    "pdf_link": "",
    "last_date": "15 November 2026",
    "content_context": "Ministry of Education extends NMMSS scholarship application to November 15, 2026."
}

mock_ai_ext = {
    "is_error": False,
    "decision": "ACCEPT",
    "event_type": "EXTENSION",
    "dates": [{"label": "Extended Last Date", "value": "15 November 2026", "evidence_quote": "15 November 2026"}],
    "summary_hi": "NMMSS आवेदन की अंतिम तिथि 15 नवंबर 2026 तक बढ़ाई गई।",
    "summary_en": "NMMSS application deadline extended to 15 November 2026.",
    "confidence": "high",
    "reason": "National extension notice"
}

with patch("main.analyze_notice_with_groq_pipeline", return_value=mock_ai_ext), \
     patch("main.send_telegram_message", return_value=201) as mock_send_d:
    res_delhi = main.process_and_post_notice(ext_delhi)
    res_jharkhand = main.process_and_post_notice(ext_jharkhand)
    res_uk = main.process_and_post_notice(ext_uk)
    
    print(f"Delhi result: {res_delhi}")
    print(f"Jharkhand result: {res_jharkhand}")
    print(f"Uttarakhand result: {res_uk}")
    print(f"Total Telegram posts: {mock_send_d.call_count}")
    
    assert res_delhi == 201
    assert res_jharkhand == 0
    assert res_uk == 0
    assert mock_send_d.call_count == 1
    print("-> PASS: Same Nov 15 extension across 3 states produced exactly ONE post!\n")

# ----------------- Scenario (e): Bihar Outdated Result Rejected ----------------- #
print("--- SCENARIO (e): Bihar 'NMMSS_Result-2024-25' is Rejected ---")
bihar_outdated = {
    "state": "Bihar",
    "title": "NMMSS RESULT 2024-25",
    "update_type": "RESULT",
    "apply_link": "https://scert.bihar.gov.in",
    "pdf_link": "https://scert.bihar.gov.in/public/uploads/result/NMMSS_Result-2024-25_Website_Uploded.pdf",
    "content_context": "NMMSS Result 2024-25 has been uploaded on website."
}
mock_ai_bihar = {
    "is_error": False,
    "decision": "ACCEPT",
    "event_type": "RESULT",
    "dates": [{"label": "Result Date", "value": "2024-25", "evidence_quote": "2024-25"}],
    "summary_hi": "बिहार NMMSS रिजल्ट 2024-25",
    "summary_en": "Bihar NMMSS Result 2024-25",
    "confidence": "high",
    "reason": "Old result uploaded"
}
with patch("main.analyze_notice_with_groq_pipeline", return_value=mock_ai_bihar), \
     patch("main.send_telegram_message") as mock_send_e:
    res_bihar = main.process_and_post_notice(bihar_outdated)
    print(f"Bihar result: {res_bihar}")
    assert res_bihar == 0
    assert not mock_send_e.called
    print("-> PASS: Outdated Bihar 2024-25 result notice was rejected at code level!\n")

# ----------------- Scenario (f): HP Generic Blog With No Date Rejected ----------------- #
print("--- SCENARIO (f): HP Generic Blog 'राज्यवार आंसर की' with No Date Rejected ---")
hp_generic = {
    "state": "Himachal Pradesh",
    "title": "एनएमएमएस आंसर की 2026-27 (NMMS Answer Key 2026-27 in hindi) - राज्यवार आंसर की डाउनलोड करें",
    "update_type": "ANSWER_KEY",
    "apply_link": "https://himachalservices.nic.in/scert",
    "source_url": "https://genericblog.com/hp-nmms-key",
    "pdf_link": "",
    "content_context": "एनएमएमएस राज्यवार आंसर की डाउनलोड करने की जानकारी।"
}
mock_ai_hp = {
    "is_error": False,
    "decision": "ACCEPT",
    "event_type": "ANSWER_KEY",
    "dates": [], # No date
    "summary_hi": "HP NMMS Answer Key",
    "summary_en": "HP NMMS Answer Key",
    "confidence": "high",
    "reason": "Blog post"
}
with patch("main.analyze_notice_with_groq_pipeline", return_value=mock_ai_hp), \
     patch("main.send_telegram_message") as mock_send_f:
    res_hp = main.process_and_post_notice(hp_generic)
    print(f"HP result: {res_hp}")
    assert res_hp == 0
    assert not mock_send_f.called
    print("-> PASS: Generic HP blog notice with no date was rejected at code level!\n")

# ----------------- Scenario (g): Multi-Publisher Corroboration Accepted ----------------- #
print("--- SCENARIO (g): Same Nov 15 Extension from 2 Different Publishers -> Accepted Once with Disclaimer ---")
from data.storage import _memory_store, get_ist_today
from datetime import timedelta
_memory_store.clear()
today = get_ist_today()
fresh_pub_date = today - timedelta(days=2)

mock_ai_ext = {
    "is_error": False,
    "decision": "ACCEPT",
    "event_type": "EXTENSION",
    "dates": [{"label": "Extended Deadline", "value": "15 November 2026", "evidence_quote": "15 November 2026"}],
    "summary_hi": "NMMSS आवेदन की अंतिम तिथि 15 नवंबर 2026 तक बढ़ा दी गई है।",
    "summary_en": "NMMSS application deadline extended to 15 November 2026.",
    "confidence": "high",
    "title_hi": "NMMSS 2026: आवेदन की अंतिम तिथि 15 नवंबर तक बढ़ी",
    "reason": "Corroborated news item"
}

news_pub1 = {
    "state": "CENTRAL",
    "title": "NMMSS 2026-27 registration deadline extended to November 15",
    "update_type": "EXTENSION",
    "apply_link": "", # No official link in text
    "source_url": "https://news.google.com/rss/articles/CBMi111",
    "publisher_url": "https://www.educationtimes.com/articles/nmmss-ext",
    "publisher_domain": "www.educationtimes.com",
    "pub_date": fresh_pub_date.isoformat(),
    "pub_date_obj": fresh_pub_date,
    "pub_date_year": fresh_pub_date.year,
    "content_context": "The registration deadline for NMMSS 2026-27 has been extended to 15 November 2026.",
    "is_fallback": True,
    "origin": "news"
}

news_pub2 = {
    "state": "CENTRAL",
    "title": "National Means-cum-Merit Scholarship 2026-27 last date extended till 15 Nov",
    "update_type": "EXTENSION",
    "apply_link": "", # No official link in text
    "source_url": "https://news.google.com/rss/articles/CBMi222",
    "publisher_url": "https://www.livehindustan.com/career/nmmss-date-ext",
    "publisher_domain": "www.livehindustan.com",
    "pub_date": fresh_pub_date.isoformat(),
    "pub_date_obj": fresh_pub_date,
    "pub_date_year": fresh_pub_date.year,
    "content_context": "National Means-cum-Merit Scholarship 2026-27 last date extended to 15 November 2026.",
    "is_fallback": True,
    "origin": "news"
}

with patch("main.analyze_notice_with_groq_pipeline", return_value=mock_ai_ext), \
     patch("main.send_telegram_message", return_value=301) as mock_send_g:
    main.process_and_post_notice(news_pub1)
    main.process_and_post_notice(news_pub2)
    acc_count_g = main.process_corroborated_news_events()
    print(f"Accepted count: {acc_count_g}")
    print(f"Telegram send called: {mock_send_g.called}")
    assert acc_count_g == 1
    assert mock_send_g.call_count == 1
    sent_text = mock_send_g.call_args[1]["text"]
    assert "यह सूचना समाचार रिपोर्टों पर आधारित है, कृपया आधिकारिक पोर्टल पर पुष्टि करें।" in sent_text
    print("-> PASS: Multi-publisher corroborated notice posted once with Hindi disclaimer line!\n")

# ----------------- Scenario (h): Single Publisher News Event Rejected ----------------- #
print("--- SCENARIO (h): Same Event from Only 1 Publisher -> Rejected ---")
single_pub_notice = {
    "state": "CENTRAL",
    "title": "NMMSS exam schedule new update announced by single blog",
    "update_type": "EXAM_DATE",
    "apply_link": "",
    "source_url": "https://news.google.com/rss/articles/CBMi333",
    "publisher_url": "https://www.singleblog.com/news/1",
    "publisher_domain": "www.singleblog.com",
    "pub_date": fresh_pub_date.isoformat(),
    "pub_date_obj": fresh_pub_date,
    "pub_date_year": fresh_pub_date.year,
    "content_context": "Exam date announced as 25 November 2026 for NMMSS 2026-27.",
    "is_fallback": True,
    "origin": "news"
}
mock_ai_single = {
    "is_error": False,
    "decision": "ACCEPT",
    "event_type": "EXAM_DATE",
    "dates": [{"label": "Exam Date", "value": "25 November 2026", "evidence_quote": "25 November 2026"}],
    "summary_hi": "NMMSS परीक्षा तिथि 25 नवंबर 2026 घोषित।",
    "summary_en": "NMMSS exam date announced as 25 November 2026.",
    "confidence": "high",
    "reason": "Single news source"
}
with patch("main.analyze_notice_with_groq_pipeline", return_value=mock_ai_single), \
     patch("main.send_telegram_message") as mock_send_h:
    main.process_and_post_notice(single_pub_notice)
    acc_count_h = main.process_corroborated_news_events()
    print(f"Accepted count: {acc_count_h}")
    assert acc_count_h == 0
    assert not mock_send_h.called
    print("-> PASS: Single-publisher news-only event was rejected without corroboration!\n")

# ----------------- Scenario (i): No Hardcoded Seeded Notice Exists ----------------- #
print("--- SCENARIO (i): Verify No Hardcoded Seeded Notice Exists in Pipeline ---")
import scrapers.portal_scraper as ps
assert not hasattr(ps, "ACTIVE_VERIFIED_ANNOUNCEMENTS"), "ACTIVE_VERIFIED_ANNOUNCEMENTS must be removed!"
with open(ps.__file__, "r", encoding="utf-8") as f:
    ps_content = f.read()
assert "ACTIVE_VERIFIED_ANNOUNCEMENTS" not in ps_content, "Found ACTIVE_VERIFIED_ANNOUNCEMENTS in portal_scraper.py!"
assert "UP NMMS 2027-28 Provisional Answer Key Out" not in ps_content, "Found hardcoded UP title in portal_scraper.py!"
print("-> PASS: Verified zero hardcoded or seeded notices exist in the pipeline!\n")

# ----------------- Scenario (j): Target States List Strict Verification ----------------- #
print("--- SCENARIO (j): Target States List Strict Verification ---")
REQUIRED_TARGET_STATES = {
    "Bihar", "Uttar Pradesh", "Madhya Pradesh", "Rajasthan", "Haryana",
    "Delhi", "Jharkhand", "Chhattisgarh", "Himachal Pradesh", "Uttarakhand"
}
assert set(main.STATE_CONFIG.keys()) == REQUIRED_TARGET_STATES, f"STATE_CONFIG mismatch: {set(main.STATE_CONFIG.keys())}"
assert set(main.ALL_STATES_IN_ORDER) == REQUIRED_TARGET_STATES | {"CENTRAL"}, f"ALL_STATES_IN_ORDER mismatch: {set(main.ALL_STATES_IN_ORDER)}"
print("-> PASS: Processed state list strictly matches the 10 target states + CENTRAL!\n")

# ----------------- Scenario (k): Stale Date Bug (2024 Article Rejected vs 2026 Accepted) ----------------- #
print("--- SCENARIO (k): Stale Date Bug (2024 Article Rejected vs 2026 Accepted) ---")
from data.storage import compute_event_key, is_last_date_expired

# Case 1: 2024 article with "extended till November 15"
# It has pub_date in 2024 and 2024 in URL/title.
stale_2024_notice = {
    "state": "CENTRAL",
    "title": "Registration deadline for National Means-cum-Merit Scholarship Scheme 2024 extended till November 15",
    "update_type": "EXTENSION",
    "apply_link": "",
    "source_url": "https://www.educationtimes.com/articles/news/99719/scheme-2024-extended-till-november-15",
    "publisher_url": "https://www.educationtimes.com/articles/news/99719/scheme-2024-extended-till-november-15",
    "publisher_domain": "www.educationtimes.com",
    "pub_date": "2024-11-07",
    "pub_date_year": 2024,
    "content_context": "The registration deadline for NMMSS 2024 has been extended till 15 November 2024.",
    "is_fallback": True,
    "origin": "news"
}
mock_ai_2024 = {
    "is_error": False,
    "decision": "ACCEPT",
    "event_type": "EXTENSION",
    "dates": [{"label": "Extended Deadline", "value": "15 November 2024", "evidence_quote": "15 November 2024"}],
    "summary_hi": "NMMSS 2024 आवेदन की अंतिम तिथि 15 नवंबर 2024 तक बढ़ाई गई।",
    "summary_en": "NMMSS 2024 application deadline extended to 15 November 2024.",
    "confidence": "high",
    "title_hi": "NMMSS 2024: अंतिम तिथि 15 नवंबर तक बढ़ी",
    "reason": "AI mistakenly accepted 2024 notice"
}

with patch("main.analyze_notice_with_groq_pipeline", return_value=mock_ai_2024), \
     patch("main.send_telegram_message") as mock_send_k1:
    res_2024 = main.process_and_post_notice(stale_2024_notice)
    assert res_2024 == 0
    assert not mock_send_k1.called
    print("-> Case 1 PASS: 2024 article with 'extended till November 15' was strictly REJECTED!")

# Case 2: Same text with a fresh 2026 publish date and 2026-27 cycle
fresh_2026_notice_1 = {
    "state": "CENTRAL",
    "title": "NMMSS 2026-27 registration deadline extended to November 15",
    "update_type": "EXTENSION",
    "apply_link": "",
    "source_url": "https://www.educationtimes.com/articles/news/nmmss-2026-ext",
    "publisher_url": "https://www.educationtimes.com/articles/news/nmmss-2026-ext",
    "publisher_domain": "www.educationtimes.com",
    "pub_date": fresh_pub_date.isoformat(),
    "pub_date_obj": fresh_pub_date,
    "pub_date_year": 2026,
    "content_context": "The registration deadline for NMMSS 2026-27 has been extended till 15 November 2026.",
    "is_fallback": True,
    "origin": "news"
}
fresh_2026_notice_2 = {
    "state": "CENTRAL",
    "title": "National Means Merit Scholarship 2026-27 last date extended till 15 Nov",
    "update_type": "EXTENSION",
    "apply_link": "",
    "source_url": "https://www.livehindustan.com/career/nmmss-2026-ext",
    "publisher_url": "https://www.livehindustan.com/career/nmmss-2026-ext",
    "publisher_domain": "www.livehindustan.com",
    "pub_date": fresh_pub_date.isoformat(),
    "pub_date_obj": fresh_pub_date,
    "pub_date_year": 2026,
    "content_context": "National Means Merit Scholarship 2026-27 last date extended to 15 November 2026.",
    "is_fallback": True,
    "origin": "news"
}
mock_ai_2026 = {
    "is_error": False,
    "decision": "ACCEPT",
    "event_type": "EXTENSION",
    "dates": [{"label": "Extended Deadline", "value": "15 November 2026", "evidence_quote": "15 November 2026"}],
    "summary_hi": "NMMSS 2026-27 आवेदन की अंतिम तिथि 15 नवंबर 2026 तक बढ़ाई गई।",
    "summary_en": "NMMSS 2026-27 application deadline extended to 15 November 2026.",
    "confidence": "high",
    "title_hi": "NMMSS 2026: अंतिम तिथि 15 नवंबर तक बढ़ी",
    "reason": "Corroborated 2026 notice"
}

_memory_store.clear()
with patch("main.analyze_notice_with_groq_pipeline", return_value=mock_ai_2026), \
     patch("main.send_telegram_message", return_value=401) as mock_send_k2:
    main.process_and_post_notice(fresh_2026_notice_1)
    main.process_and_post_notice(fresh_2026_notice_2)
    acc_count_k2 = main.process_corroborated_news_events()
    assert acc_count_k2 == 1
    assert mock_send_k2.call_count == 1
    
    # Verify message date, key date and expiry check agree on the SAME parsed date
    sent_text = mock_send_k2.call_args[1]["text"]
    assert "15 November 2026" in sent_text
    expected_event_key = compute_event_key("CENTRAL", "EXTENSION", "2026-11-15")
    assert expected_event_key in _memory_store
    assert not is_last_date_expired("15 November 2026")
    print("-> Case 2 PASS: 2026 article was accepted! Message date, key date, and expiry check strictly agree on 2026-11-15!\n")

print("=================================================================")
print("ALL TEST SCENARIOS VERIFIED SUCCESSFULLY WITH 100% PASS RATE")
print("=================================================================")
