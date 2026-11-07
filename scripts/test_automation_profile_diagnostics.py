import os
import sys
from pathlib import Path

# Add project root to sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager, ChromeProfileLockedError
from app.orchestrator import WorkflowOrchestrator
from app.state_manager import WorkflowStage

def test_automation_profile_diagnostics():
    print("=== Step 1: Verify Configuration and Diagnostic Info ===")
    cfg_mgr = ConfigurationManager()
    cfg = cfg_mgr.config
    bm = BrowserManager(cfg)

    diag = bm.get_diagnostic_info()
    print("Diagnostic Output:")
    for k, v in diag.items():
        print(f"  {k}: {v}")

    assert diag["chrome_executable_path"] == "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    assert diag["chrome_executable_exists"] is True
    assert diag["operator_profile_dir"] == "E:\\insta post ai\\data\\operator_chrome_profile"
    assert diag["operator_profile_exists"] is True
    assert diag["target_google_account"] == "palvisheshpal292@gmail.com"
    assert diag["remote_debugging_port"] == 9222
    print("Step 1 PASSED: Browser manager configured precisely for operator_chrome_profile.")

    print("\n=== Step 2: Test Persistent Context Launch & Independence ===")
    # Direct launch of persistent context (even while user's normal Chrome is open)
    print("Launching persistent context at data/operator_chrome_profile (headless=True)...")
    ctx = bm.launch_persistent_context(headless=True)
    assert ctx is not None, "Failed to launch persistent context"
    page = bm.new_page()
    page.goto("about:blank")
    print(f"Opened page URL: {page.url}")
    assert page.url == "about:blank"
    bm.close()
    print("Step 2 PASSED: Operator profile launched, operated, and closed cleanly without lock contention.")

    print("\n=== Step 3: Test Unauthenticated / Fresh Profile Handling ===")
    # When profile is not yet logged into Google, workflow must transition to NEEDS_USER_ACTION
    # and MUST NOT advance stage to RESEARCHING or SCRIPT_GENERATING
    orchestrator = WorkflowOrchestrator(cfg_mgr)
    res = orchestrator.run_daily_workflow(force=True)
    print("Orchestrator result on unauthenticated fresh profile:")
    print(res)

    assert isinstance(res, dict), "Result must be a dict"
    assert "status" in res
    assert "success" in res
    assert res["success"] is False
    assert res["status"] == "NEEDS_USER_ACTION"

    # Verify that the stage in DB was transitioned to NEEDS_USER_ACTION
    latest = orchestrator.state_manager.get_latest_workflow()
    print(f"Latest workflow stage in DB: {latest.get('stage')}")
    assert latest.get("stage") == WorkflowStage.NEEDS_USER_ACTION.value
    print(f"Recorded Topic: {latest.get('topic')}")
    print("Step 3 PASSED: Workflow safely halted in NEEDS_USER_ACTION awaiting ChatGPT authentication.")

    print("\n=== Step 4: Test Dedicated Profile Persistence Across Restart ===")
    # Verify files inside operator_chrome_profile still exist
    op_dir = Path(cfg.operator_profile_dir)
    assert (op_dir / "Default").exists(), "Default directory must persist in operator profile"
    print("Step 4 PASSED: Operator profile directory structure persisted.")

    print("\nALL AUTOMATION PROFILE DIAGNOSTIC TESTS PASSED!")

if __name__ == "__main__":
    test_automation_profile_diagnostics()
