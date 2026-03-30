import time
import random
import subprocess
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from dotenv import load_dotenv

# --- CONFIGURATION ---
URL = "https://www.carousell.sg/search/tp%20link%20hb710?sort_by=time_created%2Cdescending&tab=marketplace"
CHECK_INTERVAL_RANGE = (20, 40) 

def notify_mac(title, text):
    """Sends a native macOS system notification."""
    cmd = f'''display notification "{text}" with title "{title}"'''
    subprocess.call(['osascript', '-e', cmd])

def clean_url(url):
    """Strips tracking parameters (everything after the '?') to get the true ID."""
    if not url: return None
    return url.split('?')[0]

def get_real_listings(driver):
    """Fetches clean, non-promoted listing URLs."""
    try:
        driver.uc_open(URL)
        time.sleep(7) # Carousell is heavy; give it time to load
        
        cards = driver.find_elements(By.CSS_SELECTOR, 'div[data-testid^="listing-card"]')
        
        valid_links = []
        for card in cards:
            # Skip ads
            if "Promoted" in card.text:
                continue
                
            try:
                link_element = card.find_element(By.CSS_SELECTOR, 'a[href*="/p/"]')
                raw_link = link_element.get_attribute('href')
                
                # CLEAN THE URL HERE
                final_link = clean_url(raw_link)
                
                # Verify keyword HB710 exists
                if "hb710" in final_link.lower() or "hb710" in card.text.lower():
                    valid_links.append(final_link)
            except:
                continue
        
        return valid_links
    except Exception as e:
        print(f"\n[!] Error during scan: {e}")
        return []

def monitor():
    print("🚀 Initializing Ghost Monitor (Tracking by Product ID)...")
    driver = Driver(uc=True, incognito=True)
    
    try:
        # Move window off-screen
        driver.set_window_size(1280, 1024)
        driver.set_window_position(-2000, -2000)
        
        print("🔍 Syncing existing listings...")
        initial_results = get_real_listings(driver)
        
        # We store the cleaned URLs in a set for comparison
        seen_listings = set(initial_results)
        
        if seen_listings:
            print(f"✅ Synced. Tracking {len(seen_listings)} items. (Waiting for new ones...)")
        else:
            print("⚠️ No items found initially. Will alert on the first discovery.")

        while True:
            wait_time = random.uniform(*CHECK_INTERVAL_RANGE)
            time.sleep(wait_time)
            
            current_results = get_real_listings(driver)
            if not current_results:
                continue
            
            # Check the most recent listing found
            latest_one = current_results[0]
            
            if latest_one not in seen_listings:
                print(f"\n[{time.strftime('%H:%M:%S')}] ✨ REAL NEW LISTING: {latest_one}")
                notify_mac("Carousell: HB710 Found!", "A brand new listing was just posted.")
                
                # Add to seen to prevent repeat alerts
                seen_listings.add(latest_one)
            else:
                print(".", end="", flush=True)

    except KeyboardInterrupt:
        print("\nStopping monitor...")
    finally:
        driver.quit()

if __name__ == "__main__":
    monitor()