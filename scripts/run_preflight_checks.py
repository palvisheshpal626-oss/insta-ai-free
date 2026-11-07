import sys
import os
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config_manager import ConfigurationManager
from app.state_manager import StateManager, WorkflowStage
from app.browser_manager import BrowserManager
from app.chatgpt_client import ChatGPTClient
from app.gemini_client import GeminiClient
from app.video_manager import VideoManager

def run_preflight():
    print("=" * 70)
    print(" AI INSTAGRAM REEL OPERATOR — STEP 1 PREFLIGHT DIAGNOSTICS")
    print(f" Timestamp: {datetime.now().isoformat()}")
    print("=" * 70)

    results = {}

    # 1. Imports and Dependencies
    print("\n[1/7] Python Dependencies & Imports...")
    try:
        import playwright
        import PySide6
        import requests
        results["imports"] = "PASS"
        print("  ✓ All required Python packages imported successfully.")
    except Exception as e:
        results["imports"] = f"FAIL: {e}"
        print(f"  ✗ Import failure: {e}")

    # 2. Configuration & Database Access
    print("\n[2/7] Configuration & Database Access...")
    try:
        cfg = ConfigurationManager().config
        sm = StateManager()
        with sm._get_connection() as conn:
            cnt = conn.execute("SELECT COUNT(*) FROM workflows").fetchone()[0]
        results["config_db"] = "PASS"
        print(f"  ✓ Configuration loaded. Database accessible ({cnt} total workflows recorded).")
        print(f"  ✓ Target Google Account: {cfg.target_google_account}")
        print(f"  ✓ Operator Profile Dir: {cfg.operator_profile_dir}")
        print(f"  ✓ ChatGPT Dedicated Conv: {cfg.chatgpt_conversation_url}")
    except Exception as e:
        results["config_db"] = f"FAIL: {e}"
        print(f"  ✗ Config/DB error: {e}")

    # 3. Existing Workflow Status & Duplicate Protection
    print("\n[3/7] Existing Workflow Status & Duplicate Protection...")
    today_str = datetime.now().strftime("%Y-%m-%d")
    already_published = sm.get_todays_successful_workflow(today_str)
    if already_published:
        print(f"  ⚠ A Reel has ALREADY been published today ({today_str}): {already_published.get('publication_url')}")
        results["duplicate_check"] = "ALREADY_PUBLISHED"
    else:
        print(f"  ✓ No Reel published yet for today ({today_str}). Duplicate protection clear.")
        results["duplicate_check"] = "CLEAR"

    # Check recent workflows today
    with sm._get_connection() as conn:
        today_wfs = conn.execute(
            "SELECT workflow_id, stage, topic, error_details, video_file_path FROM workflows WHERE local_date = ? ORDER BY created_at DESC",
            (today_str,)
        ).fetchall()
        print(f"  Found {len(today_wfs)} previous workflow runs for today:")
        for wf in today_wfs:
            print(f"    - ID: {wf['workflow_id']} | Stage: {wf['stage']} | Topic: {wf['topic']} | Error: {wf['error_details']} | Video: {wf['video_file_path']}")

    # Check ready_to_post folder
    ready_dir = ROOT / "ready_to_post"
    ready_files = list(ready_dir.glob("*.mp4"))
    print(f"  ready_to_post videos: {[f.name for f in ready_files]}")

    # 4. Browser/Playwright Connection & Persistent Profile
    print("\n[4/7] Browser Manager & Profile Diagnostics...")
    bm = BrowserManager(cfg)
    diag = bm.get_diagnostic_info()
    print(f"  - Chrome executable exists: {diag['chrome_executable_exists']} ({diag['chrome_executable_path']})")
    print(f"  - Operator profile exists: {diag['operator_profile_exists']} ({diag['operator_profile_dir']})")
    print(f"  - CDP port {diag['remote_debugging_port']} active: {diag['cdp_available']}")
    print(f"  - Profile locked: {diag['profile_locked']} (Reason: {diag['lock_reason']})")

    # If CDP is not active and profile not locked, launch auth browser subprocess so we attach via CDP
    if not diag["cdp_available"] and not diag["profile_locked"]:
        print("  Starting auth browser subprocess with remote debugging port 9222...")
        pid = bm.launch_auth_browser_subprocess()
        print(f"  Spawned browser PID: {pid}. Waiting 4 seconds for CDP port to open...")
        import time
        time.sleep(4)
        diag = bm.get_diagnostic_info()
        print(f"  - Re-checked CDP port 9222 active: {diag['cdp_available']}")

    # 5. Connect and test ChatGPT, Gemini, Instagram sessions
    print("\n[5/7] Testing Session Authentication (ChatGPT, Gemini, Instagram)...")
    try:
        ctx = bm.ensure_context()
        print("  ✓ Playwright context established.")

        # Test ChatGPT
        print("  Checking ChatGPT dedicated conversation...")
        chat_client = ChatGPTClient(bm, cfg.chatgpt_conversation_url)
        page_chat = bm.new_page(prefer_existing_url="chatgpt.com")
        ok_chat, msg_chat = chat_client.open_dedicated_conversation(page_chat)
        print(f"    ChatGPT Auth Result: ok={ok_chat}, msg='{msg_chat}', url='{page_chat.url}'")
        results["chatgpt"] = "PASS" if ok_chat else f"FAIL: {msg_chat}"

        # Test Gemini
        print("  Checking Gemini conversation...")
        gemini_client = GeminiClient(bm, cfg.gemini_url or "https://gemini.google.com/")
        page_gemini = bm.new_page(prefer_existing_url="gemini.google.com")
        ok_gemini, msg_gemini = gemini_client.open_fresh_daily_conversation(page_gemini)
        print(f"    Gemini Auth Result: ok={ok_gemini}, msg='{msg_gemini}', url='{page_gemini.url}'")
        results["gemini"] = "PASS" if ok_gemini else f"FAIL: {msg_gemini}"

        # Test Instagram
        print("  Checking Instagram session...")
        page_ig = bm.new_page(prefer_existing_url="instagram.com")
        if "instagram.com" not in page_ig.url:
            page_ig.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            import time
            time.sleep(3)
        is_ig_login = "login" in page_ig.url or "accounts/login" in page_ig.url
        print(f"    Instagram Session Result: logged_in={not is_ig_login}, url='{page_ig.url}', title='{page_ig.title()}'")
        results["instagram"] = "PASS" if not is_ig_login else "FAIL: Redirected to login page"

    except Exception as e:
        print(f"  ✗ Browser testing error: {e}")
        results["browser"] = f"FAIL: {e}"
    finally:
        bm.close()

    print("\n" + "=" * 70)
    print("PREFLIGHT SUMMARY:")
    for k, v in results.items():
        print(f"  {k:15}: {v}")
    print("=" * 70)
    return results

if __name__ == "__main__":
    run_preflight()
