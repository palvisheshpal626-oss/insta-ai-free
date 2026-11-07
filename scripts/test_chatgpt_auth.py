import os
import sys
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager
from app.chatgpt_client import ChatGPTClient

def test_chatgpt_authentication():
    print("=" * 70)
    print(" AI INSTAGRAM REEL OPERATOR — CHATGPT AUTHENTICATION & ACCESS DIAGNOSTIC ")
    print("=" * 70)

    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    chat_client = ChatGPTClient(bm, cfg.chatgpt_conversation_url)

    diag = bm.get_diagnostic_info()
    browser_exec = diag["chrome_executable_path"]
    profile_dir = Path(diag["operator_profile_dir"])
    conv_url = cfg.chatgpt_conversation_url
    target_google = cfg.target_google_account

    print("\n[DIAGNOSTIC REPORT]")
    print(f"1. Actual Browser Executable:     {browser_exec}")
    print(f"   Executable Exists on Disk:     {Path(browser_exec).exists()}")
    print(f"2. Actual Automation Profile Dir: {profile_dir}")
    print(f"   Profile Exists on Disk:        {profile_dir.exists()}")
    
    # Check persistence
    default_dir = profile_dir / "Default"
    cookie_db = default_dir / "Network" / "Cookies"
    is_persistent = profile_dir.exists() and default_dir.exists()
    print(f"3. Profile Persistence:           {'PERSISTENT (Directory & Default structure verified)' if is_persistent else 'NOT INITIALIZED'}")
    print(f"   Cookie Storage Present:        {cookie_db.exists()}")
    print(f"4. Target Google Account:         {target_google}")
    print(f"5. Dedicated ChatGPT URL:         {conv_url}")

    # Launch browser context and inspect ChatGPT
    print("\n[INSPECTING CHATGPT SESSION IN PROFILE]")
    is_authenticated = False
    is_conversation_accessible = False
    prompt_response = None
    manual_action_required = None

    try:
        # Check if already open via CDP or launch persistent context
        ctx = bm.launch_persistent_context(headless=False)
        page = ctx.new_page()

        print(f"Navigating to: {conv_url}...")
        try:
            page.goto(conv_url, wait_until="domcontentloaded", timeout=45000)
            time.sleep(5)
        except Exception as e:
            print(f"Error loading URL: {e}")

        current_url = page.url
        page_title = page.title()
        page_content = page.content().lower()
        print(f"Loaded Page Title: '{page_title}'")
        print(f"Current Page URL:   {current_url}")

        # Check authentication status
        if "login" in current_url or "auth" in current_url:
            is_authenticated = False
            manual_action_required = (
                f"ChatGPT redirected to login: '{current_url}'.\n"
                "Please sign into ChatGPT manually in the opened browser window.\n"
                "Your login session will be automatically saved in data/operator_chrome_profile."
            )
        elif "challenge" in page_content or "verify you are human" in page_content or "just a moment..." in page_content:
            is_authenticated = False
            manual_action_required = "Cloudflare security verification challenge is displayed. Please solve the challenge in the opened browser window."
        else:
            # Check for prompt area
            prompt_elem = None
            for sel in ["#prompt-textarea", "div[contenteditable='true']", "textarea[placeholder*='Message']", "textarea"]:
                try:
                    elem = page.query_selector(sel)
                    if elem and elem.is_visible():
                        prompt_elem = elem
                        break
                except Exception:
                    pass

            if prompt_elem:
                is_authenticated = True
                is_conversation_accessible = True
                print("✓ Dedicated ChatGPT conversation loaded successfully and prompt input is visible!")

                # Test prompt execution
                print("\n[TESTING CONVERSATION PROMPT INTERACTION]")
                test_prompt = "Say hello from Antigravity test in 5 words."
                try:
                    prompt_elem.click()
                    time.sleep(0.5)
                    page.keyboard.insert_text(test_prompt)
                    time.sleep(1)

                    send_btn = page.query_selector('button[data-testid="send-button"], button[aria-label*="Send prompt"]')
                    if send_btn and send_btn.is_enabled():
                        send_btn.click()
                    else:
                        page.keyboard.press("Enter")

                    print("Prompt sent. Waiting for response...")
                    # Wait up to 30 seconds
                    for _ in range(15):
                        time.sleep(2)
                        stop_btn = page.query_selector('button[aria-label="Stop generating"], button[data-testid="stop-button"]')
                        if not stop_btn:
                            break

                    messages = page.query_selector_all('[data-message-author-role="assistant"], .agent-turn, .markdown')
                    if messages:
                        prompt_response = messages[-1].inner_text()
                        print(f"✓ Received ChatGPT Response:\n'{prompt_response[:300]}'")
                except Exception as e:
                    print(f"Notice during prompt execution test: {e}")
            else:
                if "conversation not found" in page_content or "unable to load conversation" in page_content:
                    manual_action_required = f"The requested conversation URL '{conv_url}' could not be accessed. Ensure the logged-in account has access to this custom GPT / conversation."
                else:
                    manual_action_required = f"Prompt area not found on page. Page title: '{page_title}', URL: '{current_url}'."

        page.close()
        bm.close()

    except Exception as e:
        print(f"Error during diagnostic inspection: {e}")
        manual_action_required = str(e)

    print("\n" + "=" * 70)
    print("FINAL SUMMARY:")
    print(f"  • Actual Browser Executable:      {browser_exec}")
    print(f"  • Automation Profile Directory:  {profile_dir}")
    print(f"  • Profile Is Persistent:         {is_persistent}")
    print(f"  • ChatGPT Authenticated:         {is_authenticated}")
    print(f"  • Dedicated Conv Accessible:     {is_conversation_accessible}")
    print(f"  • Test Prompt Received Response: {'YES' if prompt_response else 'NO'}")
    if manual_action_required:
        print(f"\n  • REMAINING MANUAL ACTION REQUIRED:\n    {manual_action_required}")
    print("=" * 70)

    return is_authenticated and is_conversation_accessible

if __name__ == "__main__":
    test_chatgpt_authentication()
