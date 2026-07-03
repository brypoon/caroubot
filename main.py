import os
import time
import random
import requests
import logging
import traceback
import gc
from collections import deque
from html import escape
from logging.handlers import RotatingFileHandler
from urllib.parse import urljoin
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
load_dotenv()
_url = os.getenv("URL")
if not _url:
    raise ValueError("URL environment variable is required but not set. Please check your .env file.")
URL: str = _url  # Type narrowed: guaranteed to be str after validation
CHECK_INTERVAL_RANGE = (5, 20)  # seconds
SCAN_FAILURE_THRESHOLD = 10
MAX_SEEN_ITEMS = 1000
GC_INTERVAL = 20
MAX_FAILURES = 10

scan_failure_count = 0

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SEARCH_KEYWORD = os.getenv("SEARCH_KEYWORD", "").lower()

# --- LOGGING ---
LOG_FILE = "monitor.log"
logger = logging.getLogger("monitor")
logger.setLevel(logging.INFO)

formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
file_handler.setFormatter(formatter)

console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)

# --- TELEGRAM COOLDOWN ---
last_alert = 0
ALERT_COOLDOWN = 300  # seconds
ERROR_DURATION_THRESHOLD = 300  # 5 minutes
last_error_time = None


def notify_telegram(text: str) -> None:
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)

        if r.status_code != 200:
            logger.error(f"Telegram failed: {r.text}")

    except Exception:
        logger.exception("Telegram error")


def safe_notify(msg: str) -> None:
    global last_alert
    if time.time() - last_alert > ALERT_COOLDOWN:
        notify_telegram(msg)
        last_alert = time.time()


def should_alert_error() -> bool:
    global last_error_time
    now = time.time()

    if last_error_time is None:
        last_error_time = now
        return False

    error_duration = now - last_error_time
    if error_duration >= ERROR_DURATION_THRESHOLD:
        last_error_time = None
        return True

    return False


def reset_error_timer() -> None:
    global last_error_time
    last_error_time = None



def safe_close(resource) -> None:
    try:
        resource.close()
    except Exception:
        pass


def clean_url(url: str) -> str | None:
    return url.split('?')[0] if url else None


def shutdown_browser(browser, context, page) -> None:
    safe_close(page)
    safe_close(context)
    safe_close(browser)
    gc.collect()


# --- BROWSER FACTORY ---
def create_browser(p) -> tuple:
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/119 Safari/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/118 Safari/537.36"
    ]

    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-extensions"
        ]
    )

    context = browser.new_context(
        user_agent=random.choice(user_agents),
        viewport={
            "width": random.choice([1280, 1366, 1440]),
            "height": random.choice([720, 800, 900])
        },
        locale="en-US"
    )

    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """)

    page = context.new_page()
    return browser, context, page


# --- SCRAPER ---
def get_real_listings(page) -> list[str] | None:
    global scan_failure_count

    try:
        page.goto(URL, timeout=30000)

        # human-like delay
        page.mouse.move(random.randint(100, 500), random.randint(100, 500))
        page.wait_for_timeout(random.randint(500, 1500))

        content = page.content().lower()

        # Wait for Cloudflare challenge to complete if present
        if "cloudflare" in content or "security verification" in content:
            logger.info("Cloudflare challenge detected, waiting...")
            page.wait_for_timeout(5000)
            content = page.content().lower()

        if "carousell" not in content:
            raise Exception("Page not loaded properly")

        try:
            page.wait_for_selector('div[data-testid^="listing-card"]', timeout=20000)
        except Exception as e:
            page_text = page.inner_text("body")
            logger.warning(f"Selector timeout, checking page content...")
            logger.warning(f"Page snippet: {page_text[:500]}")
            no_results_phrases = ["no results", "we couldn't find", "0 results", "nothing here"]
            if any(phrase in page_text.lower() for phrase in no_results_phrases):
                logger.info("Page loaded but no listings match the filters")
                scan_failure_count = 0
                return []
            raise

        page.wait_for_timeout(1000)
        page.mouse.wheel(0, 1500)
        page.wait_for_timeout(1500)

        cards = page.query_selector_all('div[data-testid^="listing-card"]')

        valid_links = []

        for card in cards:
            link = None
            try:
                text = card.inner_text()

                if "Promoted" in text:
                    continue

                link = card.query_selector('a[href*="/p/"]')
                if not link:
                    continue

                raw = link.get_attribute("href")
                final = clean_url(raw)

                if final:
                    if not SEARCH_KEYWORD:
                        valid_links.append(final)
                    else:
                        normalized_text = text.lower().replace("-", "").replace(" ", "")
                        if (SEARCH_KEYWORD in final.lower() or
                            SEARCH_KEYWORD in normalized_text):
                            valid_links.append(final)

            except Exception:
                continue
            finally:
                try:
                    card.dispose()
                    if link:
                        link.dispose()
                except Exception:
                    pass

        # ✅ SUCCESS → reset counter
        scan_failure_count = 0

        logger.info(f"Found {len(valid_links)} listings")
        return valid_links

    except Exception:
        err = traceback.format_exc()
        scan_failure_count += 1

        logger.exception(f"Playwright scan error")

        # ✅ Only notify after threshold reached
        if scan_failure_count >= SCAN_FAILURE_THRESHOLD:
            safe_notify(
                f"⚠️ <b>Scan Error</b>\n<pre>{escape(err[:1000])}</pre>"
            )
            scan_failure_count = 0  # reset after alert

        return None


# --- RETRY WRAPPER ---
def get_real_listings_with_retry(page, retries: int = 3) -> list[str] | None:
    for attempt in range(retries):
        try:
            results = get_real_listings(page)

            # None means scraping failed; [] means page loaded but no listings
            if results is None:
                logger.warning(f"Scrape failed (attempt {attempt+1})")
            else:
                return results

        except Exception:
            logger.exception(f"Attempt {attempt+1} failed")

        sleep_time = 2 ** attempt + random.uniform(1, 3)
        logger.info(f"Retrying in {round(sleep_time,2)}s")
        time.sleep(sleep_time)

    return None


# --- MAIN LOOP ---
def monitor() -> None:
    logger.info("🚀 Starting Playwright monitor")

    with sync_playwright() as p:
        browser, context, page = create_browser(p)

        loop_count = 0
        failure_count = 0

        try:
            initial = get_real_listings_with_retry(page) or []
            seen_items = deque(initial, maxlen=MAX_SEEN_ITEMS)
            seen = set(seen_items)

            logger.info(f"Tracking {len(seen)} items")

            while True:
                try:
                    loop_count += 1

                    sleep_time = random.uniform(*CHECK_INTERVAL_RANGE)
                    logger.info(f"Sleep {round(sleep_time,2)}s")
                    time.sleep(sleep_time)

                    results = get_real_listings_with_retry(page)

                    # --- FAILURE HANDLING ---
                    if results is None:
                        failure_count += 1
                        logger.warning(f"⚠️ Scrape failed ({failure_count})")

                        if failure_count >= MAX_FAILURES:
                            logger.warning("🔥 FULL RESET")

                            safe_notify("🔥 Resetting browser (failures)")

                            shutdown_browser(browser, context, page)

                            time.sleep(random.uniform(5, 10))
                            browser, context, page = create_browser(p)

                            failure_count = 0

                        continue
                    else:
                        failure_count = 0
                        reset_error_timer()

                    if not results:
                        logger.info("No listings match current filters")
                        continue

                    # --- NEW LISTING DETECTION ---
                    latest = results[0]

                    if latest not in seen:
                        logger.info(f"✨ NEW: {latest}")

                        listing_url = urljoin("https://carousell.sg", latest)
                        notify_telegram(
                            f'🔥 <b>New listing found</b>\n<a href="{escape(listing_url, quote=True)}">View</a>'
                        )

                        if len(seen_items) >= MAX_SEEN_ITEMS:
                            old = seen_items.popleft()
                            seen.discard(old)
                        seen_items.append(latest)
                        seen.add(latest)
                    else:
                        logger.info("No new listings")

                    # --- PERIODIC MAINTENANCE ---
                    if loop_count % 20 == 0:
                        logger.info("🔄 Refreshing page")
                        page.goto(URL, timeout=30000)

                    if loop_count % 50 == 0:
                        logger.info("🧹 Clearing cookies")
                        context.clear_cookies()

                    if loop_count % GC_INTERVAL == 0:
                        logger.info("🧹 Running GC")
                        gc.collect()

                    if loop_count % 100 == 0:
                        logger.info("♻️ Restarting browser")

                        shutdown_browser(browser, context, page)

                        time.sleep(2)
                        browser, context, page = create_browser(p)

                except Exception:
                    err = traceback.format_exc()
                    logger.exception("Browser error — restarting")

                    if should_alert_error():
                        safe_notify(f"❌ <b>Browser Error (5+ min)</b>\n<pre>{escape(err[:1000])}</pre>")

                    try:
                        shutdown_browser(browser, context, page)
                    except Exception:
                        pass

                    time.sleep(5)
                    browser, context, page = create_browser(p)

        finally:
            try:
                shutdown_browser(browser, context, page)
            except Exception:
                pass


# --- ENTRYPOINT ---
if __name__ == "__main__":
    try:
        monitor()
    except Exception:
        msg = f"❌ <b>Crash</b>\n<pre>{escape(traceback.format_exc())}</pre>"
        notify_telegram(msg)
        logger.exception("Fatal crash")
