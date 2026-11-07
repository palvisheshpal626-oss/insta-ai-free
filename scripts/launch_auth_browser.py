import os
import sys
import subprocess
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager

def launch_authentication_browser():
    print("=" * 70)
    print(" AI INSTAGRAM REEL OPERATOR — LAUNCH AUTHENTICATION BROWSER ")
    print("=" * 70)

    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)

    chrome_exe = cfg.chrome_executable_path
    operator_profile = cfg.operator_profile_dir
    target_email = cfg.target_google_account
    chatgpt_url = cfg.chatgpt_conversation_url or "https://chatgpt.com/"
    gemini_url = cfg.gemini_url or "https://gemini.google.com/"
    port = getattr(cfg, "remote_debugging_port", 9222)

    print(f"Browser Executable:   {chrome_exe}")
    print(f"Automation Profile:   {operator_profile}")
    print(f"Target Google Account:{target_email}")
    print(f"ChatGPT Target URL:   {chatgpt_url}")
    print(f"Gemini Target URL:    {gemini_url}")
    print(f"Remote Debugging Port:{port}")

    if not Path(chrome_exe).exists():
        print(f"\nERROR: Chrome executable not found at '{chrome_exe}'.")
        return False

    is_locked, lock_reason = bm.is_profile_locked()
    if is_locked:
        print(f"\nNotice: The operator profile is currently open ({lock_reason}).")
        print("Please switch to the open Chrome window or close it to restart.")
        return True

    print("\nLaunching visible Chrome window with dedicated automation profile...")
    cmd = [
        chrome_exe,
        f"--user-data-dir={operator_profile}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        chatgpt_url,
        gemini_url
    ]

    proc = subprocess.Popen(cmd)
    print(f"Launched Chrome process PID: {proc.pid}")
    print("\n" + "-" * 70)
    print("MANUAL AUTHENTICATION INSTRUCTIONS:")
    print(f"1. In the Gemini tab, sign into Google with: {target_email}")
    print("2. In the ChatGPT tab, sign into your ChatGPT account.")
    print(f"3. Ensure your dedicated conversation loads successfully:\n   {chatgpt_url}")
    print("4. Sessions will persist in data/operator_chrome_profile.")
    print("5. You can leave the window open or close it when done.")
    print("-" * 70)
    return True

if __name__ == "__main__":
    launch_authentication_browser()
