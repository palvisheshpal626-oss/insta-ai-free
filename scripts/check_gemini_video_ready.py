import sys
from pathlib import Path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

cfg = ConfigurationManager().config
bm = BrowserManager(cfg)
ctx = bm.ensure_context()
p = bm.get_page_for_url('gemini.google.com')
if p:
    print("Gemini URL:", p.url)
    videos = p.query_selector_all('video')
    print(f"Video tags found: {len(videos)}")
    for i, v in enumerate(videos):
        src = v.get_attribute("src")
        print(f"  Video [{i}] src: {src[:100] if src else 'No src'}")

    download_btns = p.query_selector_all('button[aria-label*="Download"], a[aria-label*="Download"], [data-test-id="video-download"]')
    print(f"Download buttons found: {len(download_btns)}")
    for i, btn in enumerate(download_btns):
        print(f"  Btn [{i}]: aria-label='{btn.get_attribute('aria-label')}', visible={btn.is_visible()}")

    responses = p.query_selector_all('.response-container, model-response, .message-content')
    if responses:
        print("Latest response text:")
        print(responses[-1].inner_text())

bm.close()
