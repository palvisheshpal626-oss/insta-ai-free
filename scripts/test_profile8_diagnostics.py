import os
import sys
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager, ChromeProfileLockedError
from app.orchestrator import WorkflowOrchestrator
from app.state_manager import WorkflowStage

def test_diagnostics_and_lock_handling():
    print("=== Step 1: Verify Configuration and Diagnostic Info ===")
    cfg_mgr = ConfigurationManager()
    cfg = cfg_mgr.config
    bm = BrowserManager(cfg)

    diag = bm.get_diagnostic_info()
    print("Diagnostic Output:")
    for k, v in diag.items():
        print(f"  {k}: {v}")

    # Assertions on configuration integrity
    assert diag["chrome_executable_path"] == "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe", "Incorrect Chrome executable path"
    assert diag["chrome_executable_exists"] is True, "Chrome executable does not exist on disk"
    assert diag["chrome_user_data_dir"] == "C:\\Users\\palvi\\AppData\\Local\\Google\\Chrome\\User Data", "Incorrect Chrome user data dir"
    assert diag["chrome_profile_name"] == "Profile 8", "Incorrect Profile name"
    assert diag["target_google_account"] == "palvisheshpal292@gmail.com", "Incorrect Target Google account"
    assert diag["remote_debugging_port"] == 9222, "Incorrect remote debugging port"
    print("Step 1 PASSED: Browser manager configured precisely for Profile 8.")

    print("\n=== Step 2: Test Safe Lock Detection & Exception Raising ===")
    is_locked, reason = bm.is_profile_locked()
    cdp_avail = bm.is_cdp_available()
    print(f"Current Profile Locked: {is_locked} ({reason})")
    print(f"Current CDP Available: {cdp_avail}")

    if is_locked and not cdp_avail:
        print("Chrome is currently running without CDP. Testing that launch_persistent_context raises ChromeProfileLockedError...")
        raised = False
        try:
            bm.launch_persistent_context()
        except ChromeProfileLockedError as e:
            raised = True
            print(f"Successfully caught ChromeProfileLockedError:\n{e}")
        assert raised, "Expected ChromeProfileLockedError was not raised when profile was locked!"
        print("Step 2 PASSED: ChromeProfileLockedError cleanly raised without falling back to data/browser_profile.")
    else:
        print("Chrome is not currently locked or CDP is open. Skipping lock exception check.")

    print("\n=== Step 3: Test Orchestrator Return Contract on Lock ===")
    orchestrator = WorkflowOrchestrator(cfg_mgr)
    # Run workflow
    res = orchestrator.run_daily_workflow(force=True)
    print("Orchestrator result on running with Profile 8:")
    print(res)

    assert isinstance(res, dict), "Result must be a dictionary"
    assert "status" in res, "Result must contain 'status'"
    assert "message" in res, "Result must contain 'message'"
    assert "success" in res, "Result must contain 'success'"

    if is_locked and not cdp_avail:
        assert res["status"] == "NEEDS_USER_ACTION", f"Expected NEEDS_USER_ACTION but got {res['status']}"
        assert res["success"] is False, "Expected success=False"
        assert "Profile 'Profile 8'" in res["message"] or "locked" in res["message"], "Error message should mention Profile 8 / lock"

        # Verify state in database
        latest = orchestrator.state_manager.get_latest_workflow()
        assert latest["stage"] == WorkflowStage.NEEDS_USER_ACTION.value, f"Expected stage NEEDS_USER_ACTION in DB, got {latest['stage']}"
        print("Step 3 PASSED: Orchestrator cleanly persisted NEEDS_USER_ACTION and returned structured contract.")

    print("\nALL PROFILE 8 TESTS PASSED!")

if __name__ == "__main__":
    test_diagnostics_and_lock_handling()
