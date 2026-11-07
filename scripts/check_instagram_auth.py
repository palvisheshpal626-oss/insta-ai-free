import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

def check_instagram():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="instagram.com")
    
    print(f"Navigating to Instagram (current url: {page.url})...")
    if "instagram.com" not in page.url:
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45000)
    
    time.sleep(5)
    print(f"Page URL: {page.url}")
    print(f"Page Title: {page.title()}")

    # Check if logged in
    is_login_page = "accounts/login" in page.url or "login" in page.url
    print(f"Is Login Page: {is_login_page}")

    # Check for login buttons or profile icons
    profile_elems = page.query_selector_all('a[href*="/direct/"], svg[aria-label="New post"], svg[aria-label="Create"], svg[aria-label="Direct"], svg[aria-label="Activity Feed"], a[href^="/"][role="link"]')
    print(f"Navigation/UI elements count: {len(profile_elems)}")

    # Extract account name if visible
    username_info = page.evaluate("""() => {
        // Look for profile link in sidebar
        const links = Array.from(document.querySelectorAll('a[href]'));
        const userLinks = links.filter(a => {
            const h = a.getAttribute('href');
            return h && h.length > 2 && h.startsWith('/') && !['/explore/', '/reels/', '/direct/', '/stories/', '/your_activity/'].some(x => h.startsWith(x));
        }).map(a => a.getAttribute('href'));
        return {
            title: document.title,
            bodySnippet: document.body.innerText.slice(0, 300),
            userLinks: userLinks.slice(0, 5)
        };
    }""")
    print("User / Page Info:", username_info)

    bm.close()

if __name__ == "__main__":
    check_instagram()
