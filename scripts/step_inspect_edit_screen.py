import sys
import time
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

def inspect_edit():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="instagram.com")

    print("Clicking 'Next' on Crop screen...")
    next_btn = page.query_selector('button:has-text("Next"), div[role="button"]:has-text("Next")')
    if not next_btn:
        next_btn = page.query_selector('xpath=//div[text()="Next"]')
    if not next_btn:
        print("Could not find Next button!")
        bm.close()
        return

    next_btn.click()
    time.sleep(3)

    # Inspect current modal
    info = page.evaluate("""() => {
        const dialog = document.querySelector('div[role="dialog"]');
        if (!dialog) return { hasDialog: false };
        const buttons = Array.from(dialog.querySelectorAll('button, div[role="button"], a[role="button"]')).map(b => ({
            text: b.innerText.trim(),
            ariaLabel: b.getAttribute('aria-label')
        }));
        const tabs = Array.from(dialog.querySelectorAll('[role="tab"], div._aacl, h2, h1')).map(t => t.innerText.trim());
        const allText = dialog.innerText;
        return {
            hasDialog: true,
            dialogTitle: dialog.querySelector('h1, [role="heading"], ._aacl')?.innerText || '',
            allText: allText,
            buttons: buttons,
            tabs: tabs
        };
    }""")
    print("Edit Screen Info:")
    print(json.dumps(info, indent=2))

    bm.close()

if __name__ == "__main__":
    inspect_edit()
