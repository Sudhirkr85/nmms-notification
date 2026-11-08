"""
State Portal Scraper for NMMS.
Scrapes official state education portals and verifies announcements.
Enforces Google News rules:
- 7-day filter
- Post an item ONLY if an official link (.gov.in / nic.in / nsp.gov.in) is found or verified.
"""

import requests
from bs4 import BeautifulSoup
import re
import urllib3
import logging
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit, urlunsplit, quote
from data.storage import compute_content_hash, is_content_hash_seen, parse_date_to_ist, get_ist_today

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Upgrade-Insecure-Requests": "1"
}

# Strict blacklist of junk / administrative materials
JUNK_KEYWORDS = [
    "question paper", "question_paper", "questionpaper", "sample paper", "model paper",
    "practice paper", "pyq", "previous year", "omr sheet",
    "letter to deo", "letter to deos", "letter to principal", "letter to center",
    "instructions to superintendent", "superintendent", "centre superintendent",
    "center superintendent", "nodal officer", "letter to all deos",
    "attendance sheet", "attn sheet", "attn. sheet", "seat matrix", "centre list",
    "center list", "room allotment", "duty list", "seating plan", "allotment list",
    "tender", "quotation", "auction", "procurement", "bid", "e-tender", "rfp",
    "meeting", "minutes of meeting", "proceeding", "samiksha", "baithak",
    "transfer", "deputation", "staff", "clerk", "voucher"
]

PORTAL_STATUS_MAP: Dict[str, str] = {}
PORTAL_DIAGNOSTICS: Dict[str, Dict[str, Any]] = {}

def get_portal_status_map() -> Dict[str, str]:
    return dict(PORTAL_STATUS_MAP)

def get_portal_diagnostics() -> Dict[str, Dict[str, Any]]:
    return dict(PORTAL_DIAGNOSTICS)

def fetch_rendered_html_with_playwright(url: str, wait_seconds: int = 8) -> tuple[str, str, List[Dict[str, str]]]:
    """
    Renders JavaScript-heavy or Cloudflare-protected page using Playwright Chromium in stealth mode.
    Returns (html_content, page_title, links_list).
    """
    try:
        from playwright.sync_api import sync_playwright
        import time
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-setuid-sandbox',
                    '--disable-dev-shm-usage'
                ]
            )
            context = browser.new_context(
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
                viewport={'width': 1280, 'height': 800}
            )
            page = context.new_page()
            page.add_init_script('delete Object.getPrototypeOf(navigator).webdriver')
            page.goto(url, timeout=35000, wait_until='domcontentloaded')
            time.sleep(wait_seconds)

            title = page.title()
            # If Cloudflare challenge page ("Just a moment..."), wait for challenge solving
            if "just a moment" in title.lower():
                logger.info(f"Cloudflare challenge detected on {url}. Waiting for verification to complete...")
                for _ in range(6):
                    time.sleep(2)
                    title = page.title()
                    if "just a moment" not in title.lower():
                        break

            html = page.content()
            extracted_links = []
            for a in page.query_selector_all('a'):
                href = a.get_attribute('href') or ""
                text = a.inner_text().strip()
                if not text:
                    text = a.get_attribute('title') or a.get_attribute('aria-label') or ""
                if href or text:
                    extracted_links.append({"href": href, "text": text})
            browser.close()
            return html, title, extracted_links
    except Exception as e:
        logger.warning(f"Playwright rendering failed for {url}: {e}")
        return "", "", []

def resolve_news_link(url: str, timeout: int = 8) -> tuple[str, str]:
    """
    Resolves news.google.com/rss/articles/... link to real publisher URL and publisher domain.
    1. First tries googlenewsdecoder.gnewsdecoder
    2. Fallback to requests following redirects
    Returns (resolved_url, publisher_domain)
    """
    if not url:
        return "", ""
    if "news.google.com" not in url:
        domain = urlsplit(url).netloc.lower().split(":")[0].strip()
        return url, domain

    # 1. Try googlenewsdecoder
    try:
        from googlenewsdecoder import gnewsdecoder
        res = gnewsdecoder(url)
        if isinstance(res, dict) and (res.get("status") or res.get("success")):
            resolved = res.get("decoded_url") or url
            domain = urlsplit(resolved).netloc.lower().split(":")[0].strip()
            return resolved, domain
    except Exception as e:
        logger.debug(f"googlenewsdecoder error for {url[:50]}: {e}")

    # 2. Fallback to requests following redirects
    try:
        resp = requests.get(url, allow_redirects=True, timeout=timeout, headers=HEADERS)
        resolved = resp.url
        domain = urlsplit(resolved).netloc.lower().split(":")[0].strip()
        return resolved, domain
    except Exception as e:
        logger.debug(f"HTTP redirect resolution failed for {url[:50]}: {e}")

    domain = urlsplit(url).netloc.lower().split(":")[0].strip()
    return url, domain

def clean_and_normalize_url(base_url: str, raw_href: str, raw_onclick: str = "") -> str:
    if raw_onclick and not raw_href:
        m = re.search(r'''(?:window\.open|location\.href)\s*=\s*['"]([^'"]+)['"]''', raw_onclick)
        if m:
            raw_href = m.group(1)

    if not raw_href:
        return ""

    joined = urljoin(base_url, raw_href.strip())
    parts = list(urlsplit(joined))
    parts[2] = quote(parts[2], safe="/%:@&?=")
    parts[3] = quote(parts[3], safe="/%:@&=?+")
    return urlunsplit(parts)

def is_official_domain(url: str, text: str = "") -> bool:
    """
    Verifies that an official domain (.gov.in / .nic.in / .ac.in / scholarships.gov.in) is present.
    Strictly excludes non-official domains such as entdata.co.in.
    """
    if not url:
        return False
    try:
        parts = urlsplit(url)
        netloc = parts.netloc.lower().split(":")[0].strip()
        if not netloc:
            return False
        if netloc == "scholarships.gov.in":
            return True
        if netloc.endswith(".gov.in") or netloc.endswith(".nic.in") or netloc.endswith(".ac.in"):
            return True
        return False
    except Exception:
        return False

def is_junk_notice(title: str, url: str = "") -> bool:
    combined = f"{title} {url}".lower()
    actionable_whitelist = [
        "answer key", "answerkey", "ans key", "uttar kunji", "uttar mala", "उत्तर कुंजी", "उत्तरमाला",
        "objection", "आपत्ति",
        "admit card", "admitcard", "hall ticket", "pravesh patra", "प्रवेश पत्र",
        "result", "merit list", "selected list", "selection list", "parinam", "परिणाम", "cutoff",
        "extend", "extended", "extension", "last date", "deadline", "date badha",
        "apply", "registration", "online form", "aavedan", "आवेदन",
        "exam date", "schedule", "pariksha tithi"
    ]
    if any(k in combined for k in actionable_whitelist):
        return False
    return any(k in combined for k in JUNK_KEYWORDS)

def is_outdated_archive(title: str, url: str = "") -> bool:
    combined = f"{title} {url}".lower()
    cur_year = datetime.now().year
    past_sessions = [
        f"{cur_year-4}-{str(cur_year-3)[-2:]}",
        f"{cur_year-3}-{str(cur_year-2)[-2:]}",
        f"{cur_year-2}-{str(cur_year-1)[-2:]}",
        str(cur_year-4), str(cur_year-3), str(cur_year-2)
    ]
    return any(f"nmms {ps}" in combined or f"nmmss {ps}" in combined for ps in past_sessions)

def is_bare_scheme_name(title: str) -> bool:
    t = re.sub(r"[^\w\s]", "", title).strip().lower()
    bare_patterns = [
        r"^nmms$", r"^nmmss$", r"^nmmse$",
        r"^nmms\s*\d{4}[-\s]?\d{2,4}$",
        r"^nmmss\s*\d{4}[-\s]?\d{2,4}$"
    ]
    return any(re.match(p, t) for p in bare_patterns)

def scrape_state_news_rss(state: str, config: dict) -> List[Dict]:
    """
    Google News RSS fallback for states.
    Strictly follows:
    1. 7-day filter (when:7d).
    2. Post an item ONLY if an official link (.gov.in / nic.in / nsp.gov.in / verified state portal) is found or verified.
    """
    notifications = []
    seen_hashes = set()
    alias = config.get("alias", "")
    hindi_name = config.get("hindi_name", "")

    state_query = f'"{state}" OR "{alias}"' if alias else f'"{state}"'
    if hindi_name:
        state_query = f'({state_query} OR "{hindi_name}")'

    queries = [
        f"https://news.google.com/rss/search?q=(%22NMMS%22+OR+%22NMMSS%22)+AND+{state_query}+when:7d&hl=en-IN&gl=IN&ceid=IN:en",
        f"https://news.google.com/rss/search?q=(%22NMMS%22+OR+%22मेधा+छात्रवृत्ति%22)+AND+{state_query}+when:7d&hl=hi&gl=IN&ceid=IN:hi"
    ]

    for rss_url in queries:
        try:
            resp = requests.get(rss_url, headers=HEADERS, timeout=12)
            if resp.status_code != 200:
                continue

            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                raw_title = item.findtext("title") or ""
                link = item.findtext("link") or ""
                description = item.findtext("description") or ""
                raw_pubdate = item.findtext("pubDate") or ""

                clean_title = re.sub(r"\s*-\s*[^-]+$", "", raw_title).strip()
                if len(clean_title) < 15:
                    continue

                t_lower = clean_title.lower()
                if not any(k in t_lower for k in ["nmms", "nmmss", "national means", "मेधा छात्रवृत्ति"]):
                    continue

                if is_junk_notice(clean_title, link):
                    continue
                if is_outdated_archive(clean_title, link):
                    continue

                chash = compute_content_hash(state, clean_title, link)
                if chash in seen_hashes or is_content_hash_seen(chash):
                    continue
                seen_hashes.add(chash)

                resolved_url, pub_domain = resolve_news_link(link)
                # Fetch real article text with timeout
                article_text = ""
                meta_pubdate_str = ""
                if resolved_url:
                    try:
                        art_resp = requests.get(resolved_url, headers=HEADERS, timeout=8, verify=False)
                        if art_resp.status_code == 200:
                            art_soup = BeautifulSoup(art_resp.text, "html.parser")
                            # Check publication date in meta tags
                            for meta_prop in ["article:published_time", "pubdate", "publish-date", "datePublished", "date"]:
                                m_tag = art_soup.find("meta", attrs={"property": meta_prop}) or art_soup.find("meta", attrs={"name": meta_prop})
                                if m_tag and m_tag.get("content"):
                                    meta_pubdate_str = m_tag["content"].strip()
                                    break

                            for tag in art_soup(["script", "style", "nav", "footer", "header", "noscript"]):
                                tag.decompose()
                            article_text = " ".join(art_soup.stripped_strings)[:4000]
                    except Exception as ae:
                        logger.debug(f"Article text fetch error for {resolved_url}: {ae}")

                # Parse publish date to verify 7-day rule
                pub_date_obj = None
                if raw_pubdate:
                    try:
                        dt = parsedate_to_datetime(raw_pubdate)
                        if dt:
                            pub_date_obj = dt.astimezone(IST).date()
                    except Exception:
                        pass

                if not pub_date_obj and meta_pubdate_str:
                    pub_date_obj = parse_date_to_ist(meta_pubdate_str)

                # STALE DATE RULE: News items require verifiable publish date within last 7 days
                today = get_ist_today()
                if not pub_date_obj:
                    logger.info(f"Skipping news item '{clean_title[:45]}': missing verifiable publish date")
                    continue

                days_diff = (today - pub_date_obj).days
                if days_diff < 0 or days_diff > 7:
                    logger.info(f"Skipping stale news item '{clean_title[:45]}': published on {pub_date_obj} ({days_diff} days old > 7 days)")
                    continue

                # News items NEVER carry official apply_link or pdf_link from news body
                item_data = {
                    "content_hash": chash,
                    "state": state,
                    "authority": config.get("authority", "State Education Board"),
                    "title": clean_title,
                    "update_type": "Official Update",
                    "apply_link": "",
                    "pdf_link": "",
                    "source_url": link,
                    "publisher_url": resolved_url,
                    "publisher_domain": pub_domain,
                    "pub_date": pub_date_obj.isoformat(),
                    "pub_date_obj": pub_date_obj,
                    "pub_date_year": pub_date_obj.year,
                    "content_context": f"{clean_title}. {article_text if article_text else description}",
                    "is_fallback": True,
                    "origin": "news"
                }
                notifications.append(item_data)
                if len(notifications) >= 2:
                    break

            if notifications:
                break
        except Exception as e:
            logger.warning(f"Error in state news RSS for {state}: {e}")

    return notifications

def scrape_state_website(state: str, config: dict) -> List[Dict]:
    """
    Scrapes official state education portal for Class 8 NMMS notices.
    Captures complete diagnostics for coverage reporting when 0 items returned.
    """
    notifications = []
    seen_hashes = set()
    url = config.get("official_url", "")
    keywords = config.get("keywords", ["NMMS"])

    diag = {
        "status": "UNKNOWN",
        "http_code": 0,
        "size_kb": 0.0,
        "total_links": 0,
        "nmms_links": 0,
        "is_blocked": False,
        "is_js_rendered": False,
        "summary": ""
    }

    # Direct Portal Scraping
    portal_found = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, verify=False)
        diag["http_code"] = resp.status_code
        diag["size_kb"] = round(len(resp.content) / 1024, 1)

        if resp.status_code == 200:
            PORTAL_STATUS_MAP[state] = "OK"
            diag["status"] = "OK"
            text_lower = resp.text.lower()

            # Check if blocked or challenged
            if any(k in text_lower for k in ["access denied", "cloudflare", "attention required", "security check", "captcha", "forbidden"]):
                diag["is_blocked"] = True

            soup = BeautifulSoup(resp.text, "html.parser")
            all_a_tags = soup.find_all("a")
            diag["total_links"] = len(all_a_tags)

            # Check if JavaScript SPA rendered (empty initial HTML shell)
            if (len(resp.text) < 2000 and any(spa in text_lower for spa in ["<div id=\"root\"", "<div id=\"app\"", "<app-root"])) or (diag["total_links"] == 0 and "<script" in text_lower):
                diag["is_js_rendered"] = True

            for a_tag in all_a_tags:
                raw_text = a_tag.get_text(strip=True)
                if not raw_text:
                    img_tag = a_tag.find("img")
                    if img_tag:
                        raw_text = img_tag.get("alt", "").strip() or img_tag.get("title", "").strip()
                    if not raw_text:
                        raw_text = a_tag.get("title", "").strip() or a_tag.get("aria-label", "").strip()

                text = re.sub(r"^\s*[\d\s]+(?:days?|weeks?|months?|hours?|minutes?)\s*ago\s*", "", raw_text, flags=re.IGNORECASE).strip()
                if not text:
                    continue

                raw_href = a_tag.get("href", "").strip()
                raw_onclick = a_tag.get("onclick", "").strip()
                if not raw_href and not raw_onclick:
                    continue

                if not any(k.lower() in text.lower() for k in keywords):
                    continue

                diag["nmms_links"] += 1
                resolved_url = clean_and_normalize_url(url, raw_href, raw_onclick)
                url_lower = resolved_url.lower()

                doc_extensions = (".pdf", ".jpg", ".jpeg", ".png")
                is_doc = any(url_lower.endswith(ext) for ext in doc_extensions)

                if is_junk_notice(text, resolved_url):
                    continue
                if is_outdated_archive(text, resolved_url):
                    continue
                if not is_doc and is_bare_scheme_name(text):
                    continue

                chash = compute_content_hash(state, text, resolved_url)
                if chash in seen_hashes or is_content_hash_seen(chash):
                    continue
                seen_hashes.add(chash)

                today = get_ist_today()
                portal_found.append({
                    "content_hash": chash,
                    "state": state,
                    "authority": config.get("authority", "State Education Board"),
                    "title": text,
                    "update_type": "Official Circular",
                    "apply_link": url,
                    "pdf_link": resolved_url if is_doc else "",
                    "source_url": resolved_url,
                    "publisher_url": resolved_url,
                    "publisher_domain": urlsplit(url).netloc.lower().split(":")[0].strip(),
                    "pub_date": today.isoformat(),
                    "pub_date_obj": today,
                    "pub_date_year": today.year,
                    "apply_start": "",
                    "last_date": "अंतिम तिथि: आधिकारिक सूचना देखें",
                    "exam_date": "",
                    "content_context": f"{text}. Official notice on {config.get('authority', 'State Board')} ({url})".strip(),
                    "is_fallback": False,
                    "origin": "portal"
                })
                if len(portal_found) >= 2:
                    break
        else:
            PORTAL_STATUS_MAP[state] = f"HTTP {resp.status_code}"
            diag["status"] = f"HTTP {resp.status_code}"
            if resp.status_code in (401, 403):
                diag["is_blocked"] = True
    except Exception as e:
        err_msg = str(e)
        if "SSLError" in err_msg:
            PORTAL_STATUS_MAP[state] = "ERROR: SSL"
            diag["status"] = "ERROR: SSL"
        elif "NameResolutionError" in err_msg or "Failed to resolve" in err_msg:
            PORTAL_STATUS_MAP[state] = "ERROR: DNS"
            diag["status"] = "ERROR: DNS"
        elif "Timeout" in err_msg or "timed out" in err_msg:
            PORTAL_STATUS_MAP[state] = "ERROR: Timeout"
            diag["status"] = "ERROR: Timeout"
        else:
            PORTAL_STATUS_MAP[state] = f"ERROR: {type(e).__name__}"
            diag["status"] = f"ERROR: {type(e).__name__}"
        diag["summary"] = err_msg[:70]
        logger.warning(f"Direct portal scrape error for {state} ({url}): {e}")

    # Playwright fallback for JS-rendered / Cloudflare-protected / blocked portals
    if not portal_found and (diag["is_js_rendered"] or diag["is_blocked"] or "entdata.co.in" in url or diag["total_links"] == 0 or diag["status"].startswith("ERROR")):
        logger.info(f"Attempting Playwright stealth rendering for {state} ({url})...")
        pw_html, pw_title, pw_links = fetch_rendered_html_with_playwright(url, wait_seconds=6)
        if pw_links:
            diag["is_js_rendered"] = False
            diag["is_blocked"] = False
            diag["status"] = "OK"
            diag["total_links"] = len(pw_links)
            PORTAL_STATUS_MAP[state] = "OK"
            today = get_ist_today()
            for item in pw_links:
                text = item.get("text", "").strip()
                raw_href = item.get("href", "").strip()
                if not text or not raw_href:
                    continue
                if not any(k.lower() in text.lower() for k in keywords):
                    continue
                diag["nmms_links"] += 1
                resolved_url = clean_and_normalize_url(url, raw_href)
                url_lower = resolved_url.lower()
                doc_extensions = (".pdf", ".jpg", ".jpeg", ".png")
                is_doc = any(url_lower.endswith(ext) for ext in doc_extensions)
                if is_junk_notice(text, resolved_url) or is_outdated_archive(text, resolved_url):
                    continue
                if not is_doc and is_bare_scheme_name(text):
                    continue
                chash = compute_content_hash(state, text, resolved_url)
                if chash in seen_hashes or is_content_hash_seen(chash):
                    continue
                seen_hashes.add(chash)
                portal_found.append({
                    "content_hash": chash,
                    "state": state,
                    "authority": config.get("authority", "State Education Board"),
                    "title": text,
                    "update_type": "Official Circular",
                    "apply_link": url,
                    "pdf_link": resolved_url if is_doc else "",
                    "source_url": resolved_url,
                    "publisher_url": resolved_url,
                    "publisher_domain": urlsplit(url).netloc.lower().split(":")[0].strip(),
                    "pub_date": today.isoformat(),
                    "pub_date_obj": today,
                    "pub_date_year": today.year,
                    "apply_start": "",
                    "last_date": "अंतिम तिथि: आधिकारिक सूचना देखें",
                    "exam_date": "",
                    "content_context": f"{text}. Official notice on {config.get('authority', 'State Board')} ({url}) {pw_title}".strip(),
                    "is_fallback": False,
                    "origin": "portal"
                })
                if len(portal_found) >= 2:
                    break

    # Set diagnostic summary if 0 items found
    if not portal_found:
        if diag["status"].startswith("ERROR"):
            pass  # summary already set
        elif diag["is_blocked"]:
            diag["summary"] = "Blocked/WAF/Captcha"
        elif diag["is_js_rendered"]:
            diag["summary"] = "JS-rendered SPA (empty initial HTML)"
        elif diag["http_code"] != 200:
            diag["summary"] = f"HTTP {diag['http_code']}"
        elif diag["total_links"] == 0:
            diag["summary"] = "0 links found on homepage"
        elif diag["nmms_links"] == 0:
            diag["summary"] = f"0 of {diag['total_links']} links matched NMMS keywords"
        else:
            diag["summary"] = f"All {diag['nmms_links']} NMMS links filtered (junk/archive/seen)"
    else:
        diag["summary"] = f"{len(portal_found)} notices extracted"

    PORTAL_DIAGNOSTICS[state] = diag
    notifications.extend(portal_found)

    # If direct portal scraping found nothing, fallback to verified Google News RSS
    if not notifications:
        news_notices = scrape_state_news_rss(state, config)
        notifications.extend(news_notices)

    return notifications
