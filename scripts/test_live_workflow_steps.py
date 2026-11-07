import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager
from app.gemini_client import GeminiClient
from app.chatgpt_client import ChatGPTClient

def test_live_workflow():
    print("=" * 60)
    print(" LIVE INDIAN FASHION WORKFLOW VERIFICATION ")
    print("=" * 60)

    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)

    if not bm.is_cdp_available():
        print("CDP port 9222 is not available. Please ensure the authentication browser is running.")
        return

    print("\n[1/3] Attaching to Chrome CDP session...")
    ctx = bm.ensure_context()
    print("  ✓ CDP context attached.")

    print("\n[2/3] Checking Gemini tab status...")
    gemini_page = bm.new_page(prefer_existing_url="gemini.google.com")
    print(f"  Gemini page URL: {gemini_page.url}")
    print(f"  Gemini page Title: {gemini_page.title()}")
    gem_client = GeminiClient(bm, cfg.gemini_url)
    
    # Check if Gemini input field is ready
    input_elem = gemini_page.query_selector(
        'rich-textarea, div[contenteditable="true"], textarea[placeholder*="Ask Gemini"], div.ql-editor'
    )
    if input_elem and input_elem.is_visible():
        print("  ✓ Gemini input box is VISIBLE and ready for prompt.")
    else:
        print("  ⚠ Gemini input box not currently visible (might need navigation or chat initialization).")

    print("\n[3/3] Checking ChatGPT tab status...")
    chat_client = ChatGPTClient(bm, cfg.chatgpt_conversation_url)
    gpt_page = bm.new_page(prefer_existing_url="chatgpt.com")
    print(f"  ChatGPT page URL: {gpt_page.url}")
    print(f"  ChatGPT page Title: {gpt_page.title()}")

    gpt_ready, gpt_msg = chat_client.open_dedicated_conversation(gpt_page)
    print(f"  ChatGPT conversation ready status: {gpt_ready} ({gpt_msg})")

    bm.close()
    print("\n" + "=" * 60)
    print(" LIVE CHECK FINISHED")
    print("=" * 60)

if __name__ == "__main__":
    test_live_workflow()
