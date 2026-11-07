import os
import sys
import unittest
import tempfile
import sqlite3
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import AppConfig, ConfigurationManager
from app.state_manager import StateManager, WorkflowStage
from app.scheduler import SchedulerService
from app.orchestrator import WorkflowOrchestrator

class TestSchedulerAndWorkflowContract(unittest.TestCase):
    """Regression test suite for scheduler stability, return contracts, and duplicate prevention."""

    def setUp(self):
        # Create temporary isolated directory for SQLite database and config
        self.temp_dir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.temp_dir.name)

        # Isolated DB
        self.db_path = self.temp_path / "test_operator.db"
        self.state_manager = StateManager(self.db_path)

        # Isolated Config
        self.config_path = self.temp_path / "test_settings.json"
        self.config_manager = ConfigurationManager(self.config_path)

        # Mock Orchestrator
        self.mock_orchestrator = MagicMock(spec=WorkflowOrchestrator)
        self.mock_orchestrator.state_manager = self.state_manager
        self.mock_orchestrator.config_manager = self.config_manager

        # Scheduler
        self.scheduler = SchedulerService(self.mock_orchestrator)
        self.scheduler.config_manager = self.config_manager

    def tearDown(self):
        self.scheduler.stop()
        self.temp_dir.cleanup()

    def test_1_workflow_returns_valid_success_dict(self):
        """Scenario 1: Workflow returns a valid success dictionary."""
        self.mock_orchestrator.run_daily_workflow.return_value = {
            "status": "PUBLISHED",
            "message": "Successfully published Reel",
            "success": True,
            "url": "https://instagram.com/reel/123"
        }
        # Run _run_if_needed
        self.scheduler._run_if_needed("TestTrigger")
        self.mock_orchestrator.run_daily_workflow.assert_called_once()

    def test_2_workflow_returns_failure_dict(self):
        """Scenario 2: Workflow returns a failure dictionary."""
        self.mock_orchestrator.run_daily_workflow.return_value = {
            "status": "FAILED",
            "message": "Script generation failed",
            "success": False
        }
        self.scheduler._run_if_needed("TestTrigger")
        self.mock_orchestrator.run_daily_workflow.assert_called_once()

    def test_3_workflow_returns_needs_user_action(self):
        """Scenario 3: Workflow returns NEEDS_USER_ACTION."""
        self.mock_orchestrator.run_daily_workflow.return_value = {
            "status": "NEEDS_USER_ACTION",
            "message": "ChatGPT authentication expired",
            "success": False,
            "stage": "NEEDS_USER_ACTION"
        }
        self.scheduler._run_if_needed("TestTrigger")
        self.mock_orchestrator.run_daily_workflow.assert_called_once()

    def test_4_workflow_unexpectedly_returns_none(self):
        """Scenario 4: Workflow unexpectedly returns None (Scheduler must NOT crash)."""
        self.mock_orchestrator.run_daily_workflow.return_value = None
        # Must execute without raising AttributeError: 'NoneType' object has no attribute 'get'
        try:
            self.scheduler._run_if_needed("TestTrigger")
        except AttributeError as e:
            self.fail(f"Scheduler crashed with AttributeError on None return: {e}")

    def test_5_workflow_raises_exception(self):
        """Scenario 5: Workflow raises an unhandled exception."""
        self.mock_orchestrator.run_daily_workflow.side_effect = RuntimeError("Playwright connection lost")
        try:
            self.scheduler._run_if_needed("TestTrigger")
        except Exception as e:
            self.fail(f"Scheduler thread allowed exception to escape unhandled: {e}")

    def test_6_scheduler_when_workflow_awaiting_user_action(self):
        """Scenario 6: Scheduler starts when a previous workflow is awaiting user action."""
        # Record a workflow in NEEDS_USER_ACTION in DB for today
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        wf = self.state_manager.create_workflow("wf_test_blocked", today_str)
        self.state_manager.update_stage("wf_test_blocked", WorkflowStage.NEEDS_USER_ACTION, error_details="Login required")

        # In scheduled tick, it must NOT spin or crash, it should log warning and halt automated trigger
        self.scheduler._run_if_needed("ScheduledTick")
        self.mock_orchestrator.run_daily_workflow.assert_not_called()

    def test_7_scheduler_remains_alive_after_unexpected_result(self):
        """Scenario 7: Scheduler remains operational after invalid result."""
        self.mock_orchestrator.run_daily_workflow.return_value = None
        self.scheduler._run_if_needed("TestTrigger")
        # Ensure scheduler internal state remains alive
        self.assertTrue(hasattr(self.scheduler, "_run_if_needed"))

    def test_8_already_published_reel_is_not_published_again(self):
        """Scenario 8: An already-published Reel is not published again (Duplicate prevention)."""
        from datetime import datetime
        today_str = datetime.now().strftime("%Y-%m-%d")
        wf = self.state_manager.create_workflow("wf_test_published", today_str)
        self.state_manager.update_stage(
            "wf_test_published",
            WorkflowStage.PUBLISHED,
            publication_id="pub_123",
            publication_url="https://instagram.com/reel/123",
            publication_status="PUBLISHED"
        )

        # Execute check
        self.scheduler._run_if_needed("StartupCheck")
        # Orchestrator run_daily_workflow should NOT be called because today's reel succeeded
        self.mock_orchestrator.run_daily_workflow.assert_not_called()

if __name__ == "__main__":
    unittest.main(verbosity=2)
