import os
import sys
import time
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Ensure CWD is project root
os.chdir(str(PROJECT_ROOT))

from app.config_manager import ConfigurationManager
from app.orchestrator import WorkflowOrchestrator
from app.logger import app_logger

def run_batch(count: int = 3):
    print("=" * 70)
    print(f" AI INSTAGRAM REEL OPERATOR — BATCH RUNNER ({count} REELS)")
    print("=" * 70)
    app_logger.info(f"Starting batch run of {count} Reels back-to-back...")

    config_mgr = ConfigurationManager()

    successful = []
    failed = []

    for idx in range(1, count + 1):
        banner = f"--- STARTING REEL {idx} OF {count} ---"
        print("\n" + "=" * len(banner))
        print(banner)
        print("=" * len(banner) + "\n")
        app_logger.info(f"Batch progress: Starting Reel {idx}/{count}...")

        try:
            orchestrator = WorkflowOrchestrator(config_mgr)
            res = orchestrator.run_daily_workflow(force=True)
            print(f"Reel {idx} Execution Result: {res}")
            app_logger.info(f"Reel {idx} finished with status: {res.get('status')}")

            if res.get("success") and res.get("status") == "PUBLISHED":
                successful.append({
                    "reel_number": idx,
                    "workflow_id": res.get("workflow_id"),
                    "url": res.get("url"),
                    "topic": res.get("topic")
                })
                print(f"SUCCESS: Reel {idx} published live at: {res.get('url')}")
            else:
                failed.append({
                    "reel_number": idx,
                    "status": res.get("status"),
                    "message": res.get("message")
                })
                print(f"WARNING: Reel {idx} did not publish: {res.get('message')}")
                # If blocked or failed, do not crash; wait and decide whether to continue
                if res.get("status") in ["NEEDS_USER_ACTION", "FAILED"]:
                    app_logger.warning(f"Batch halted at Reel {idx} due to: {res.get('message')}")
                    break

        except Exception as e:
            app_logger.error(f"Unexpected error in batch reel {idx}: {e}", exc_info=True)
            failed.append({"reel_number": idx, "error": str(e)})
            break

        if idx < count:
            cooldown_seconds = 20
            print(f"\nWaiting {cooldown_seconds}s cooldown before starting next Reel in batch...")
            app_logger.info(f"Batch cooldown: waiting {cooldown_seconds}s before Reel {idx + 1}...")
            time.sleep(cooldown_seconds)

    print("\n" + "=" * 70)
    print(" BATCH EXECUTION SUMMARY ")
    print("=" * 70)
    print(f"Requested: {count}")
    print(f"Published: {len(successful)}")
    for s in successful:
        print(f"  - Reel #{s['reel_number']}: {s.get('url')} (Workflow: {s.get('workflow_id')})")
    if failed:
        print(f"Incomplete / Failed: {len(failed)}")
        for f in failed:
            print(f"  - Reel #{f['reel_number']}: {f.get('status')} - {f.get('message') or f.get('error')}")
    print("=" * 70)

    return successful, failed

if __name__ == "__main__":
    reels_to_run = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    run_batch(reels_to_run)
