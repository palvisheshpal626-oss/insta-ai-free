import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

VIDEO_PATH = Path("E:/insta post ai/ready_to_post/2026-10-18_ishq_jalakar_karvaan_shashwat__reel.mp4").resolve()

def step_create_flow():
    print("=" * 60)
    print(" STEPPING THROUGH INSTAGRAM REEL CREATION FLOW ")
    print("=" * 60)

    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="instagram.com")

    if "instagram.com" not in page.url:
        page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45000)
    time.sleep(3)

    # 1. Click Create button
    print("\n[Step 1] Looking for Create button...")
    create_btn = page.query_selector('svg[aria-label="New post"], svg[aria-label="Create"], [aria-label="New post"]')
    if not create_btn:
        create_btn = page.query_selector('xpath=//span[text()="Create"]')
    if not create_btn:
        create_btn = page.query_selector('a[href="#"][role="link"]')
    if not create_btn:
        # Search by text
        elements = page.query_selector_all('span')
        for el in elements:
            if el.inner_text().strip() == "Create":
                create_btn = el
                break
    
    if not create_btn:
        print("Could not find Create button!")
        bm.close()
        return

    print("Found Create button. Clicking...")
    create_btn.click()
    time.sleep(3)

    # Check if a menu popped up (e.g. Post vs Reel)
    post_reel_menu = page.query_selector_all('span:has-text("Post"), span:has-text("Reel"), a:has-text("Post"), a:has-text("Reel")')
    print(f"Sub-menu options count: {len(post_reel_menu)}")
    for sm in post_reel_menu:
        txt = sm.inner_text().strip()
        print(f"  Menu item: '{txt}'")
        if txt == "Post" or txt == "Reel":
            print(f"  Clicking '{txt}' option...")
            sm.click()
            time.sleep(2)
            break

    # 2. Find file input
    print("\n[Step 2] Finding file input...")
    file_input = page.wait_for_selector('input[type="file"]', state="attached", timeout=15000)
    if not file_input:
        print("File input not found!")
        bm.close()
        return

    print(f"Setting input file to: {VIDEO_PATH}")
    page.set_input_files('input[type="file"]', str(VIDEO_PATH))
    print("File set. Waiting 8s for Instagram video processing/modal update...")
    time.sleep(8)

    # Inspect modal buttons and content
    modal_info = page.evaluate("""() => {
        const dialog = document.querySelector('div[role="dialog"]');
        if (!dialog) return { hasDialog: false };
        const buttons = Array.from(dialog.querySelectorAll('button, div[role="button"]')).map(b => ({
            text: b.innerText.trim(),
            ariaLabel: b.getAttribute('aria-label'),
            role: b.getAttribute('role')
        }));
        const video = dialog.querySelector('video');
        return {
            hasDialog: true,
            dialogText: dialog.innerText.slice(0, 400),
            hasVideo: !!video,
            videoSrc: video ? video.src : null,
            buttons: buttons
        };
    }""")
    print("Modal Info after upload:")
    import json
    print(json.dumps(modal_info, indent=2))

    bm.close()

if __name__ == "__main__":
    step_create_flow()
