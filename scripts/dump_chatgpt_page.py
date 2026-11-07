import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager
from app.chatgpt_client import ChatGPTClient

def dump_page():
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    bm.ensure_context()
    page = bm.new_page()
    client = ChatGPTClient(bm, cfg.chatgpt_conversation_url)
    client.open_dedicated_conversation(page)

    import time
    time.sleep(3) # allow any deferred hydration
    html = page.content()
    with open("chatgpt_dump.html", "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Dumped HTML length: {len(html)}")

    # Print interesting tag names and IDs
    elements_info = page.evaluate("""() => {
        const buttons = Array.from(document.querySelectorAll('button')).map(b => b.outerHTML.slice(0, 100));
        const inputs = Array.from(document.querySelectorAll('input, textarea, [contenteditable]')).map(i => i.outerHTML.slice(0, 100));
        const mainText = document.body.innerText.slice(0, 500);
        return { buttons, inputs, mainText };
    }""")
    print("Main Text:")
    print(elements_info["mainText"])
    print("\nInputs:")
    for inp in elements_info["inputs"]:
        print(" ", inp)
    print("\nButtons count:", len(elements_info["buttons"]))
    for b in elements_info["buttons"][:10]:
        print(" ", b)

    bm.close()

if __name__ == "__main__":
    dump_page()
