import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

def inspect_gemini():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="gemini.google.com")
    print(f"Gemini page URL: {page.url}")
    print(f"Gemini page Title: {page.title()}")

    # Find responses
    responses = page.query_selector_all('.response-container, model-response, .message-content')
    print(f"Found {len(responses)} response elements:")
    for i, r in enumerate(responses):
        txt = r.inner_text()
        print(f"\n--- Response [{i}] (len={len(txt)}) ---")
        print(txt[:400])

    # Check for video elements or video players
    videos = page.query_selector_all('video, [data-test-id*="video"]')
    print(f"\nFound {len(videos)} video tags.")
    for v in videos:
        print("Video tag src:", v.get_attribute("src"))

    # Check buttons inside the last response
    if responses:
        last_r = responses[-1]
        buttons = last_r.query_selector_all('button, a[download]')
        print(f"\nButtons in LAST response ({len(buttons)}):")
        for b in buttons:
            print("  ", b.get_attribute("aria-label"), b.get_attribute("data-test-id"), b.get_attribute("href"))

    bm.close()

if __name__ == "__main__":
    inspect_gemini()
