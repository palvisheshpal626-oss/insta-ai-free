import os
import sys
import json
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager
from app.state_manager import StateManager
from app.scheduler import SchedulerService
from app.orchestrator import WorkflowOrchestrator

def run_system_and_scheduler_diagnostics():
    print("=" * 70)
    print(" AI INSTAGRAM REEL OPERATOR — SYSTEM & SCHEDULER DIAGNOSTIC REPORT ")
    print("=" * 70)

    # 1. Config & Target Account
    print("\n[1/5] Checking Configuration & Profile Mapping...")
    cfg = ConfigurationManager().config
    bm = BrowserManager(cfg)
    diag = bm.get_diagnostic_info()
    for k, v in diag.items():
        print(f"  - {k}: {v}")

    # 2. Database & Active State
    print("\n[2/5] Inspecting Workflow Database State...")
    sm = StateManager()
    latest = sm.get_latest_workflow()
    if latest:
        print(f"  - Latest Workflow ID: {latest.get('workflow_id')}")
        print(f"  - Current Stage: {latest.get('stage')}")
        print(f"  - Date: {latest.get('local_date')}")
        print(f"  - Topic: {latest.get('topic') or 'None'}")
        print(f"  - Notice / Status: {latest.get('error_details') or 'None'}")
    else:
        print("  - No workflows recorded yet.")

    # 3. Test Scheduler Call with Mock Orchestrator
    print("\n[3/5] Testing Scheduler Handling of Workflow Results...")
    orch = WorkflowOrchestrator()
    scheduler = SchedulerService(orch)

    # Test that _run_if_needed can execute without crashing
    print("  - Testing defensive scheduler check with existing state...")
    try:
        # Trigger StartupCheck logic directly
        scheduler._run_if_needed("DiagnosticCheck")
        print("  ✓ Scheduler executed _run_if_needed safely without any exception!")
    except Exception as e:
        print(f"  ✗ Scheduler crashed: {e}")
        return False

    # 4. Verify Operator Profile on Disk
    print("\n[4/5] Verifying Dedicated Automation Profile on Disk...")
    op_profile = Path(cfg.operator_profile_dir)
    print(f"  - Operator Profile Path: {op_profile}")
    print(f"  - Directory Exists: {op_profile.exists()}")
    assert op_profile.exists(), "Operator profile directory should exist"
    print("  ✓ Dedicated automation profile verified on disk.")

    # 5. Clean Browser Shutdown
    bm.close()
    print("\n[5/5] Diagnostic completed successfully!")
    print("=" * 70)
    return True

if __name__ == "__main__":
    success = run_system_and_scheduler_diagnostics()
    sys.exit(0 if success else 1)
