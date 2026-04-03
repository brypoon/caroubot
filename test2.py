import os
import time
import random
import requests
import logging
import sys
import traceback
from logging.handlers import RotatingFileHandler
from dotenv import load_dotenv
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
load_dotenv()
URL = os.getenv("URL")
CHECK_INTERVAL_RANGE = (20, 40)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

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


def notify_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        r = requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)

        if r.status_code != 200:
            logger.error(f"Telegram failed: {r.text}")
        else:
            logger.info("Telegram sent")

    except Exception:
        logger.exception("Telegram error")


def safe_notify(msg):
    global last_alert
    if time.time() - last_alert > ALERT_COOLDOWN:
        notify_telegram(msg)
        last_alert = time.time()



def clean_url(url):
    return url.split('?')[0] if url else None


# --- BROWSER FACTORY ---
def create_browser():
    p = sync_playwright().start()

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
            "--disable-dev-shm-usage"
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

    # stealth tweak
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
    """)

    page = context.new_page()
    return p, browser, context, page


# --- SCRAPER ---
def get_real_listings(page):
    try:
        page.goto(URL, timeout=30000)

        # human-like delay
        page.mouse.move(random.randint(100, 500), random.randint(100, 500))
        page.wait_for_timeout(random.randint(500, 1500))

        content = page.content().lower()

        if "carousell" not in content:
            raise Exception("Page not loaded properly")

        page.wait_for_selector('div[data-testid^="listing-card"]', timeout=15000)

        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(2000)

        cards = page.query_selector_all('div[data-testid^="listing-card"]')

        valid_links = []

        for card in cards:
            try:
                text = card.inner_text()

                if "Promoted" in text:
                    continue

                link = card.query_selector('a[href*="/p/"]')
                if not link:
                    continue

                raw = link.get_attribute("href")
                final = clean_url(raw)

                if final and ("hb710" in final.lower() or "hb710" in text.lower()):
                    valid_links.append(final)

            except Exception:
                continue

        logger.info(f"[PW] Found {len(valid_links)} listings")
        return valid_links

    except Exception:
        err = traceback.format_exc()
        logger.exception("Playwright scan error")

        safe_notify(f"⚠️ <b>Scan Error</b>\n<pre>{err[:1000]}</pre>")
        return []


# --- RETRY WRAPPER ---
def get_real_listings_with_retry(page, retries=3):
    for attempt in range(retries):
        try:
            results = get_real_listings(page)

            if results:
                return results

            logger.warning(f"Empty result (attempt {attempt+1})")

        except Exception:
            logger.exception(f"Attempt {attempt+1} failed")

        sleep_time = 2 ** attempt + random.uniform(1, 3)
        logger.info(f"Retrying in {round(sleep_time,2)}s")
        time.sleep(sleep_time)

    return []


# --- MAIN LOOP ---
def monitor():
    logger.info("🚀 Starting Playwright monitor")

    p, browser, context, page = create_browser()

    loop_count = 0
    failure_count = 0
    MAX_FAILURES = 5

    try:
        initial = get_real_listings_with_retry(page)
        seen = set(initial)

        logger.info(f"Tracking {len(seen)} items")

        while True:
            try:
                loop_count += 1

                sleep_time = random.uniform(*CHECK_INTERVAL_RANGE)
                logger.info(f"Sleep {round(sleep_time,2)}s")
                time.sleep(sleep_time)

                results = get_real_listings_with_retry(page)

                # --- FAILURE HANDLING ---
                if not results:
                    failure_count += 1
                    logger.warning(f"⚠️ Empty results ({failure_count})")

                    safe_notify(f"⚠️ No listings ({failure_count})")

                    if failure_count >= MAX_FAILURES:
                        logger.warning("🔥 FULL RESET")

                        safe_notify("🔥 Resetting browser (failures)")

                        browser.close()
                        p.stop()

                        time.sleep(random.uniform(5, 10))
                        p, browser, context, page = create_browser()

                        failure_count = 0

                    continue
                else:
                    failure_count = 0

                # --- NEW LISTING DETECTION ---
                latest = results[0]

                if latest not in seen:
                    logger.info(f"✨ NEW: {latest}")

                    notify_telegram(
                        f"🔥 <b>HB710 Found</b>\n<a href='{latest}'>View</a>"
                    )

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

                if loop_count % 100 == 0:
                    logger.info("♻️ Restarting browser")

                    browser.close()
                    p.stop()

                    time.sleep(2)
                    p, browser, context, page = create_browser()

            except Exception:
                err = traceback.format_exc()
                logger.exception("Browser error — restarting")

                safe_notify(f"❌ <b>Browser Error</b>\n<pre>{err[:1000]}</pre>")

                try:
                    browser.close()
                    p.stop()
                except:
                    pass

                time.sleep(5)
                p, browser, context, page = create_browser()

    finally:
        try:
            browser.close()
            p.stop()
        except:
            pass


# --- ENTRYPOINT ---
if __name__ == "__main__":
    try:
        monitor()
    except Exception:
        msg = f"❌ <b>Crash</b>\n<pre>{traceback.format_exc()}</pre>"
        notify_telegram(msg)
        logger.exception("Fatal crash")
        sys.exit(1)