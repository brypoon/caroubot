import os
import time
import random
import subprocess
import requests
from dotenv import load_dotenv
from seleniumbase import Driver
from selenium.webdriver.common.by import By

# --- CONFIGURATION ---
URL = os.getenv("URL")
CHECK_INTERVAL_RANGE = (20, 40) 

def notify_mac(title, text):
    cmd = f'''display notification "{text}" with title "{title}"'''
    subprocess.call(['osascript', '-e', cmd])

# --- TELEGRAM CONFIG ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

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
    except Exception as e:
        print(f"[!] Telegram error: {e}")

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
            except:
                continue
        
        return valid_links
    except Exception as e:
        print(f"\n[!] Error during scan: {e}")
        return []

def monitor():
    print("🚀 Initializing Ghost Monitor (Headless Mode)...")
    
    # ✅ HEADLESS ENABLED HERE
    driver = Driver(
        uc=True,
        incognito=True,
        headless2=True  # <-- key change
    )
    
    try:
        print("🔍 Syncing existing listings...")
        initial_results = get_real_listings(driver)
        
        seen_listings = set(initial_results)
        
        if seen_listings:
            print(f"✅ Synced. Tracking {len(seen_listings)} items.")
        else:
            print("⚠️ No items found initially.")

        while True:
            wait_time = random.uniform(*CHECK_INTERVAL_RANGE)
            time.sleep(wait_time)
            
            current_results = get_real_listings(driver)
            if not current_results:
                continue
            
            latest_one = current_results[0]
            
            if latest_one not in seen_listings:
                print(f"\n[{time.strftime('%H:%M:%S')}] ✨ NEW: {latest_one}")
                notify_mac("Carousell: HB710 Found!", "New listing detected.")
                notify_telegram(
                    f"🔥 <b>HB710 Found</b>\n"
                    f"<a href='{latest_one}'>View Listing</a>"
                )
                seen_listings.add(latest_one)
            else:
                print(".", end="", flush=True)

    except KeyboardInterrupt:
        print("\nStopping monitor...")
    finally:
        driver.quit()

if __name__ == "__main__":
    monitor()