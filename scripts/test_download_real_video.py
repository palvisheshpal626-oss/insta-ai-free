import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager
from app.video_manager import VideoManager

def test_download():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="gemini.google.com")
    print(f"Gemini page URL: {page.url}")

    # Look for 'Download video' button
    dl_btn = page.query_selector('button[aria-label*="Download video"]')
    if not dl_btn:
        print("Could not find 'Download video' button.")
        return

    print("Found 'Download video' button. Clicking and expecting download...")
    downloads_dir = BASE_DIR / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)

    with page.expect_download(timeout=60000) as download_info:
        dl_btn.click()
    download = download_info.value
    target_path = downloads_dir / download.suggested_filename
    print(f"Downloaded suggested filename: {download.suggested_filename}")
    download.save_as(str(target_path))
    print(f"Saved video to: {target_path} (Size: {target_path.stat().st_size} bytes)")

    # Validate video
    vm = VideoManager()
    valid, info, msg = vm.validate_video(str(target_path))
    print(f"Video validation result: valid={valid}, info={info}, msg={msg}")

    bm.close()

if __name__ == "__main__":
    test_download()
