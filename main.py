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
from seleniumbase import Driver
from selenium.webdriver.common.by import By

# --- CONFIGURATION ---
load_dotenv()
URL = os.getenv("URL")
CHECK_INTERVAL_RANGE = (20, 40)

# --- TELEGRAM CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# --- LOGGING SETUP ---
LOG_FILE = "monitor.log"

logger = logging.getLogger("monitor")
logger.setLevel(logging.INFO)

formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(message)s"
)

# File handler (rotates at 5MB, keeps 3 backups)
file_handler = RotatingFileHandler(LOG_FILE, maxBytes=5*1024*1024, backupCount=3)
file_handler.setFormatter(formatter)

# Console handler (optional, remove if running as service)
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)

logger.addHandler(file_handler)
logger.addHandler(console_handler)


def notify_telegram(text):
    """Send Telegram message"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }
        requests.post(url, json=payload, timeout=10)
        logger.info("Telegram notification sent")
    except Exception as e:
        logger.exception("Telegram error")


def notify_mac(title, text):
    try:
        cmd = f'''display notification "{text}" with title "{title}"'''
        subprocess.call(['osascript', '-e', cmd])
        logger.info("Mac notification sent")
    except Exception:
        logger.exception("Mac notification error")


def clean_url(url):
    if not url:
        return None
    return url.split('?')[0]


def get_real_listings(driver):
    try:
        driver.uc_open(URL)
        time.sleep(7)

        cards = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid^="listing-card"]')

        valid_links = []
        for card in cards:
            if "Promoted" in card.text:
                continue

            try:
                link_element = card.find_element(By.CSS_SELECTOR, 'a[href*="/p/"]')
                raw_link = link_element.get_attribute('href')
                final_link = clean_url(raw_link)

                if final_link and ("hb710" in final_link.lower() or "hb710" in card.text.lower()):
                    valid_links.append(final_link)
            except Exception:
                continue

        logger.info(f"Found {len(valid_links)} valid listings")
        return valid_links

    except Exception:
        logger.exception("Error during scan")
        return []


def monitor():
    logger.info("🚀 Initializing Ghost Monitor (Headless Mode)...")

    driver = Driver(
        uc=True,
        incognito=True,
        headless2=True
    )

    try:
        logger.info("🔍 Syncing existing listings...")
        initial_results = get_real_listings(driver)

        seen_listings = set(initial_results)

        if seen_listings:
            logger.info(f"✅ Synced. Tracking {len(seen_listings)} items.")
        else:
            logger.warning("⚠️ No items found initially.")

        while True:
            wait_time = random.uniform(*CHECK_INTERVAL_RANGE)
            logger.info(f"Sleeping for {round(wait_time, 2)} seconds")
            time.sleep(wait_time)

            current_results = get_real_listings(driver)
            if not current_results:
                logger.warning("No results returned")
                continue

            latest_one = current_results[0]

            if latest_one not in seen_listings:
                logger.info(f"✨ NEW LISTING: {latest_one}")

                notify_mac("Carousell: HB710 Found!", "New listing detected.")
                notify_telegram(
                    f"🔥 <b>HB710 Found</b>\n"
                    f"<a href='{latest_one}'>View Listing</a>"
                )

                seen_listings.add(latest_one)
            else:
                logger.info("No new listings")

    except KeyboardInterrupt:
        logger.info("Stopping monitor...")
    except Exception:
        logger.exception("Unexpected crash in monitor()")
    finally:
        driver.quit()
        logger.info("Driver closed")


if __name__ == "__main__":
    try:
        monitor()
    except Exception as e:
        error_msg = f"❌ <b>Monitor Crashed</b>\n<pre>{traceback.format_exc()}</pre>"
        notify_telegram(error_msg)
        logger.exception("Fatal crash")
        sys.exit(1)