import sys
from pathlib import Path
import json

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager
from app.chatgpt_client import ChatGPTClient

def inspect():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page(prefer_existing_url="chatgpt.com")
    
    info = page.evaluate("""() => {
        const res = {};
        res.url = window.location.href;
        res.title = document.title;
        
        // Find input
        const inputs = Array.from(document.querySelectorAll('div[contenteditable="true"], #prompt-textarea, textarea, div.ProseMirror'));
        res.inputs = inputs.map(el => ({
            tag: el.tagName,
            id: el.id,
            className: el.className,
            placeholder: el.getAttribute('placeholder') || el.getAttribute('data-placeholder'),
            text: el.innerText
        }));

        // Find buttons in footer/composer
        const buttons = Array.from(document.querySelectorAll('form button, div[class*="composer"] button, [data-testid*="send"], [aria-label*="Send"]'));
        res.buttons = buttons.map(b => ({
            tag: b.tagName,
            aria_label: b.getAttribute('aria-label'),
            data_testid: b.getAttribute('data-testid'),
            className: b.className,
            disabled: b.disabled,
            text: b.innerText
        }));

        // Responses
        const responses = Array.from(document.querySelectorAll('[class*="MarkdownRoot"], [class*="DilResponseRoot"]'));
        res.responses = responses.map(r => r.innerText.slice(0, 200));

        return res;
    }""")
    print("INSPECT RESULT:")
    print(json.dumps(info, indent=2))
    bm.close()

if __name__ == "__main__":
    inspect()
