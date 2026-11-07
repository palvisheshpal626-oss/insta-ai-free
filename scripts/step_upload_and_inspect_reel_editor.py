import sys
import time
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

VIDEO_PATH = Path("E:/insta post ai/ready_to_post/2026-10-18_ishq_jalakar_karvaan_shashwat__reel.mp4").resolve()

def step_upload():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="instagram.com")
    
    print("Setting input file...")
    page.set_input_files('input[type="file"]', str(VIDEO_PATH))
    print("Waiting 10s for video to load into Instagram player...")
    time.sleep(10)

    # Check for "Video posts are now shared as reels" popup
    ok_btn = page.query_selector('button:has-text("OK"), button:has-text("Dismiss")')
    if ok_btn:
        print("Dismissing 'Video posts are now shared as reels' info popup...")
        ok_btn.click()
        time.sleep(2)

    # Inspect the state after upload
    state = page.evaluate("""() => {
        const dialog = document.querySelector('div[role="dialog"]');
        if (!dialog) return { hasDialog: false };
        const buttons = Array.from(dialog.querySelectorAll('button, div[role="button"], a[role="button"]')).map(b => ({
            text: b.innerText.trim(),
            ariaLabel: b.getAttribute('aria-label')
        }));
        const video = dialog.querySelector('video');
        return {
            hasDialog: true,
            dialogTitle: dialog.querySelector('h1, [role="heading"], ._aacl')?.innerText || '',
            dialogText: dialog.innerText.slice(0, 500),
            hasVideo: !!video,
            videoSrc: video ? (video.src || video.querySelector('source')?.src || 'blob') : null,
            buttons: buttons
        };
    }""")
    print("State after upload:")
    print(json.dumps(state, indent=2))

    bm.close()

if __name__ == "__main__":
    step_upload()
