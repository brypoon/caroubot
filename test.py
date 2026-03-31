import os
import time
import random
import subprocess
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


def notify_telegram(text):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
        logger.info("Telegram sent")
    except Exception:
        logger.exception("Telegram error")


def notify_mac(title, text):
    try:
        cmd = f'''display notification "{text}" with title "{title}"'''
        subprocess.call(['osascript', '-e', cmd])
    except Exception:
        logger.exception("Mac notify error")


def clean_url(url):
    return url.split('?')[0] if url else None


# ✅ NEW: Playwright browser factory
def create_browser():
    p = sync_playwright().start()

    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--no-sandbox",
            "--disable-dev-shm-usage"
        ]
    )

    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        viewport={"width": 1280, "height": 800}
    )

    page = context.new_page()

    return p, browser, context, page


def get_real_listings(page):
    try:
        page.goto(URL, timeout=30000)

        # ✅ Wait properly for listings (NOT sleep)
        page.wait_for_selector('div[data-testid^="listing-card"]', timeout=15000)

        # ✅ Extra scroll to trigger lazy load
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
        logger.exception("Playwright scan error")
        return []


def monitor():
    logger.info("🚀 Starting Playwright monitor")

    p, browser, context, page = create_browser()
    loop_count = 0

    try:
        initial = get_real_listings(page)
        seen = set(initial)

        logger.info(f"Tracking {len(seen)} items")

        while True:
            try:
                loop_count += 1

                sleep_time = random.uniform(*CHECK_INTERVAL_RANGE)
                logger.info(f"Sleep {round(sleep_time,2)}s")
                time.sleep(sleep_time)

                results = get_real_listings(page)
                if not results:
                    continue

                latest = results[0]

                if latest not in seen:
                    logger.info(f"✨ NEW: {latest}")

                    notify_mac("Carousell Alert", "New HB710 listing")
                    notify_telegram(
                        f"🔥 <b>HB710 Found</b>\n<a href='{latest}'>View</a>"
                    )

                    seen.add(latest)
                else:
                    logger.info("No new listings")

                # ✅ periodic restart (Playwright is more stable but still good practice)
                if loop_count % 100 == 0:
                    logger.info("♻️ Restarting browser")

                    browser.close()
                    p.stop()

                    time.sleep(2)
                    p, browser, context, page = create_browser()

            except Exception:
                logger.exception("Browser error — restarting")

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


if __name__ == "__main__":
    try:
        monitor()
    except Exception:
        msg = f"❌ <b>Crash</b>\n<pre>{traceback.format_exc()}</pre>"
        notify_telegram(msg)
        logger.exception("Fatal crash")
        sys.exit(1)