import os
import sys
import time
import threading
from datetime import datetime
from typing import Optional

from .logger import app_logger
from .config_manager import ConfigurationManager
from .orchestrator import WorkflowOrchestrator

class SchedulerService:
    """Manages persistent background daily execution.
    
    Behavior:
    - Runs in background thread / system process.
    - Evaluates whether today's Reel has succeeded on start and on tick.
    - Runs missed work immediately on startup subject to duplicate prevention.
    - Executes automatically at configured daily time (default 09:00).
    """

    def __init__(self, orchestrator: Optional[WorkflowOrchestrator] = None):
        self.config_manager = ConfigurationManager()
        self.orchestrator = orchestrator or WorkflowOrchestrator(self.config_manager)
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_checked_day: Optional[str] = None

    def start(self):
        """Starts background monitoring loop."""
        if self._running:
            return

        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="SchedulerLoop")
        self._thread.start()
        app_logger.info("Scheduler service started in background thread.")

        # Trigger startup check (runs missed work if not yet completed today)
        self.trigger_startup_check()

    def stop(self):
        self._running = False
        app_logger.info("Scheduler service stopped.")

    def trigger_startup_check(self):
        """Immediately checks if today's reel has been completed. If not, runs workflow."""
        threading.Thread(target=self._run_if_needed, args=("StartupCheck",), daemon=True).start()

    def _run_if_needed(self, trigger_source: str):
        today_str = datetime.now().strftime("%Y-%m-%d")
        app_logger.info(f"[{trigger_source}] Verifying daily run eligibility for {today_str}...")

        # 1. Check if today's Reel has already been successfully published
        try:
            successful = self.orchestrator.state_manager.get_todays_successful_workflow(today_str)
            if successful:
                app_logger.info(f"[{trigger_source}] Today's Reel has already been published ({today_str}). No action required.")
                return
        except Exception as e:
            app_logger.error(f"[{trigger_source}] Error checking existing publication status: {e}", exc_info=True)
            return

        # 2. Check if active workflow is currently blocked waiting for user action
        active = self.orchestrator.state_manager.get_todays_active_workflow(today_str)
        if active and active.get("stage") == "NEEDS_USER_ACTION":
            err_details = active.get("error_details") or "Authentication or configuration required."
            app_logger.warning(
                f"[{trigger_source}] Workflow {active['workflow_id']} is currently blocked in NEEDS_USER_ACTION: '{err_details}'. "
                "Halting automated trigger until user resolves the action via the dashboard (or clicks Run Now to re-test)."
            )
            # Only proceed if triggered manually or user resolves it, to prevent rapid retry spinning
            if trigger_source in ["ScheduledTick", "StartupCheck"]:
                return

        app_logger.info(f"[{trigger_source}] Starting daily Reel workflow...")
        try:
            res = self.orchestrator.run_daily_workflow()
        except Exception as e:
            app_logger.error(f"[{trigger_source}] Exception raised during run_daily_workflow: {e}", exc_info=True)
            return

        # Defensive inspection of workflow result
        if res is None:
            app_logger.error(
                f"[{trigger_source}] Workflow returned None unexpectedly instead of a structured result dictionary. "
                "Scheduler thread will remain alive."
            )
            return
        elif not isinstance(res, dict):
            app_logger.error(
                f"[{trigger_source}] Workflow returned unexpected type '{type(res).__name__}': {res}. "
                "Scheduler thread will remain alive."
            )
            return

        status_str = res.get("status") or ("SUCCESS" if res.get("success") else "FAILED")
        msg_str = res.get("message") or res.get("error") or ""
        app_logger.info(f"[{trigger_source}] Daily run workflow finished with status: [{status_str}] - {msg_str}")

    def _loop(self):
        while self._running:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            current_hhmm = now.strftime("%H:%M")
            target_hhmm = self.config_manager.config.schedule_time_hhmm

            # If current time matches target scheduled time and haven't run today yet
            if current_hhmm == target_hhmm and self._last_checked_day != today_str:
                self._last_checked_day = today_str
                app_logger.info(f"[ScheduledTick] Target time {target_hhmm} reached. Triggering workflow.")
                self._run_if_needed("ScheduledTick")

            # Sleep 30 seconds between ticks
            time.sleep(30)
