import sys
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

def inspect():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="instagram.com")
    print(f"URL: {page.url}")
    print(f"Title: {page.title()}")

    info = page.evaluate("""() => {
        const dialog = document.querySelector('div[role="dialog"]');
        const inputs = Array.from(document.querySelectorAll('input[type="file"]')).map(i => ({
            name: i.name,
            accept: i.accept,
            multiple: i.multiple
        }));
        const buttons = Array.from(document.querySelectorAll('div[role="dialog"] button, div[role="dialog"] div[role="button"]')).map(b => b.innerText.trim());
        return {
            hasDialog: !!dialog,
            dialogText: dialog ? dialog.innerText.slice(0, 300) : null,
            fileInputs: inputs,
            dialogButtons: buttons
        };
    }""")
    print("Page state:")
    print(json.dumps(info, indent=2))
    bm.close()

if __name__ == "__main__":
    inspect()
