import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

def diagnose():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="chatgpt.com")
    print(f"ChatGPT URL: {page.url}")
    print(f"ChatGPT Title: {page.title()}")

    # Check input elements
    input_selectors = [
        '#prompt-textarea',
        'div[contenteditable="true"]',
        'textarea[data-id="root"]',
        'textarea'
    ]
    for s in input_selectors:
        elems = page.query_selector_all(s)
        print(f"Selector '{s}': count={len(elems)}")

    # Check send button
    send_selectors = [
        'button[data-testid="send-button"]',
        'button[aria-label*="Send prompt"]',
        'button[data-testid*="send"]',
        'button[aria-label*="Send"]'
    ]
    for s in send_selectors:
        elems = page.query_selector_all(s)
        for i, el in enumerate(elems):
            print(f"Send button '{s}' [{i}]: enabled={el.is_enabled()}, visible={el.is_visible()}")

    # Check turn/message selectors
    msg_selectors = [
        '[data-message-author-role="assistant"]',
        'article[data-testid*="conversation-turn"]',
        '.agent-turn',
        'div.markdown',
        '[data-testid*="message"]',
        'article'
    ]
    for s in msg_selectors:
        elems = page.query_selector_all(s)
        print(f"Message selector '{s}': count={len(elems)}")
        if elems and s in ['[data-message-author-role="assistant"]', 'div.markdown', 'article']:
            last_text = elems[-1].inner_text()
            print(f"  Sample text from '{s}' ({len(last_text)} chars): {last_text[:150]}...")

    bm.close()

if __name__ == "__main__":
    diagnose()
