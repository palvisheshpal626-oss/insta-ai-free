import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

CAPTION = (
    "Desi vibes, fresh fit, and a little Bollywood magic. Which outfit should be next? ✨\n\n"
    "🎵 Audio: Ishq Jalakar - Karvaan by Shashwat Sachdev, Shahzad Ali, Subhadeep Das Chowdhury\n\n"
    "#IndianFashion #DanceReels #BollywoodVibes #OutfitInspiration #IndianGirlStyle #TrendingReels"
)

def prepare_caption():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="instagram.com")

    # Locate caption area
    caption_elem = page.query_selector('div[aria-label="Add a caption..."], div[contenteditable="true"]')
    if not caption_elem:
        print("Caption area not found!")
        bm.close()
        return

    print("Clicking caption area...")
    caption_elem.click()
    time.sleep(0.5)

    print("Inserting caption text...")
    page.keyboard.insert_text(CAPTION)
    time.sleep(1)

    # Check Add AI label
    ai_label_btn = page.query_selector('//span[contains(text(), "Add AI label")] | //div[contains(text(), "Add AI label")]')
    if ai_label_btn:
        print("Found AI label section. Checking toggle...")
        # Toggle checkbox or switch if present
        toggle = page.query_selector('input[type="checkbox"][aria-label*="AI"], [role="switch"]')
        if toggle and not toggle.is_checked():
            try:
                toggle.click()
                print("Toggled AI label to ON.")
            except Exception as e:
                print("Could not toggle switch directly:", e)

    # Read back current dialog state
    dialog_text = page.evaluate("""() => {
        const dialog = document.querySelector('div[role="dialog"]');
        return dialog ? dialog.innerText : '';
    }""")
    print("\nCurrent Dialog Text Summary:\n" + dialog_text[:600])

    bm.close()

if __name__ == "__main__":
    prepare_caption()
