import sys
import time
from pathlib import Path
import json

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

def test_scoped_send():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="chatgpt.com")
    
    # Target composer specifically
    composer_input = page.wait_for_selector('form[data-chatgpt-composer] div.ProseMirror, div[aria-label="Ask ChatGPT"]', timeout=10000)
    print("Found composer input:", composer_input)
    composer_input.click()
    time.sleep(0.5)

    initial_count = len(page.query_selector_all('[class*="MarkdownRoot"]'))
    print("Initial assistant message count:", initial_count)

    test_msg = 'Test Shararat Reel Script: Please reply strictly with valid JSON: {"song": "Shararat", "status": "verified", "dance": "hook step"}'
    
    # Focus and insert text
    page.keyboard.insert_text(test_msg)
    time.sleep(1)

    # Check button inside composer
    send_btn = page.query_selector('form[data-chatgpt-composer] button[data-testid="send-button"], form[data-chatgpt-composer] button[aria-label*="Send"]')
    print("Send button in composer:", send_btn)
    if send_btn:
        print("  aria-label:", send_btn.get_attribute("aria-label"))
        print("  disabled:", send_btn.is_disabled())
        send_btn.click()
    else:
        print("Pressing Enter")
        page.keyboard.press("Enter")

    print("Sent! Waiting up to 30s for new response...")
    for i in range(30):
        time.sleep(1)
        cur = page.query_selector_all('[class*="MarkdownRoot"]')
        if len(cur) > initial_count:
            print(f"Success! Response received in {i+1}s:")
            print(cur[-1].inner_text())
            break
    else:
        print("No response within 30s.")

    bm.close()

if __name__ == "__main__":
    test_scoped_send()
