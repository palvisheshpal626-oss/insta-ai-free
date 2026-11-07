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
    responses = p.query_selector_all('.response-container, model-response, .message-content')
    if responses:
        last = responses[-1]
        print("Latest response HTML:\n", last.evaluate("el => el.outerHTML")[:2000])

bm.close()
