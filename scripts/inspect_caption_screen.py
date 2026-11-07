import sys
import time
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

def inspect_caption_screen():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="instagram.com")

    print("Clicking 'Next' on Edit screen...")
    next_btn = page.query_selector('button:has-text("Next"), div[role="button"]:has-text("Next")')
    if next_btn:
        next_btn.click()
        time.sleep(3)

    info = page.evaluate("""() => {
        const dialog = document.querySelector('div[role="dialog"]');
        if (!dialog) return { hasDialog: false };
        const buttons = Array.from(dialog.querySelectorAll('button, div[role="button"]')).map(b => b.innerText.trim());
        const textareas = Array.from(dialog.querySelectorAll('textarea, div[contenteditable="true"]')).map(t => ({
            ariaLabel: t.getAttribute('aria-label'),
            placeholder: t.getAttribute('placeholder')
        }));
        return {
            hasDialog: true,
            dialogTitle: dialog.querySelector('h1, [role="heading"], ._aacl')?.innerText || '',
            allText: dialog.innerText,
            buttons: buttons,
            textareas: textareas
        };
    }""")
    print("Caption Screen Info:")
    print(json.dumps(info, indent=2))
    bm.close()

if __name__ == "__main__":
    inspect_caption_screen()
