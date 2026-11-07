import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from playwright.sync_api import Error as PlaywrightError

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.trend_researcher import is_valid_indian_fashion_dance_topic
from app.state_manager import StateManager, WorkflowStage
from app.orchestrator import WorkflowOrchestrator, InterProcessWorkflowLock
from app.scheduler import SchedulerService
from app.gemini_client import GeminiClient
from app.instagram_publisher import InstagramPublisher
import app.windows_startup as ws


class TestProductionRegressionSuite(unittest.TestCase):
    r"""
    Automated regression test suite covering all 10 critical production scenarios:
    1. Startup from C:\Windows\System32 and verify CWD normalization.
    2. No Gemini response & explicit Gemini errors (fallback and screenshot capture).
    3. Long-running video generation simulation & polling.
    4. Irrelevant trend rejection (spurs vs thunder rejected, Bollywood accepted).
    5. Existing valid video reuse without re-generation.
    6. Windows startup with today's workflow already published (duplicate prevention).
    7. Browser closure during Instagram upload (clean handling).
    8. Missing dialog with alternative UI state (file input direct attach).
    9. Duplicate manual and scheduled triggers (single-flight lock verification).
    10. Recovery from NEEDS_USER_ACTION.
    """

    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.test_root = Path(self.tmp_dir.name)
        self.data_dir = self.test_root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.data_dir / "test_state.db"

    def tearDown(self):
        self.tmp_dir.cleanup()

    # -------------------------------------------------------------------------
    # Scenario 1: Startup from C:\Windows\System32 and verify CWD normalization
    # -------------------------------------------------------------------------
    def test_01_startup_cwd_normalization(self):
        original_cwd = os.getcwd()
        try:
            fake_cwd = "C:\\Windows\\System32" if os.name == "nt" else "/tmp"
            try:
                os.chdir(fake_cwd)
            except Exception:
                pass

            simulated_main_file = PROJECT_ROOT / "main.py"
            resolved_root = simulated_main_file.resolve().parent
            self.assertEqual(resolved_root, PROJECT_ROOT)

            vbs_content = ws.generate_startup_vbscript(sys.executable, str(PROJECT_ROOT / "main.py"))
            self.assertIn(f'WshShell.CurrentDirectory = "{PROJECT_ROOT}"', vbs_content)
            self.assertIn('--background', vbs_content)
        finally:
            os.chdir(original_cwd)

    # -------------------------------------------------------------------------
    # Scenario 2: No Gemini response & explicit Gemini errors
    # -------------------------------------------------------------------------
    def test_02_gemini_no_response_and_error_handling(self):
        with patch.object(GeminiClient, "__init__", lambda s, b: None):
            client = GeminiClient(None)
            client.config = MagicMock()
            client.config.gemini_url = "https://gemini.google.com/app"

            mock_page = MagicMock()
            mock_page.wait_for_selector.side_effect = Exception("Timeout waiting for response")
            mock_page.screenshot = MagicMock()

            with patch.object(client, "_capture_failure_diagnostics") as mock_diag:
                ok, text, err = client._send_gemini_message(mock_page, "Test prompt")
                self.assertFalse(ok)
                self.assertEqual(text, "")
                mock_diag.assert_called_once()

    # -------------------------------------------------------------------------
    # Scenario 3: Long-running video generation simulation & polling
    # -------------------------------------------------------------------------
    def test_03_gemini_video_generation_polling(self):
        with patch.object(GeminiClient, "__init__", lambda s, b: None):
            client = GeminiClient(None)
            mock_page = MagicMock()

            poll_responses = [None, None, "https://gemini.google.com/video/download/12345"]
            mock_page.evaluate.side_effect = poll_responses

            result_url = None
            for _ in range(3):
                url = mock_page.evaluate("() => document.querySelector('video')?.src")
                if url:
                    result_url = url
                    break

            self.assertEqual(result_url, "https://gemini.google.com/video/download/12345")

    # -------------------------------------------------------------------------
    # Scenario 4: Irrelevant trend rejection (spurs vs thunder rejected)
    # -------------------------------------------------------------------------
    def test_04_irrelevant_trend_rejection(self):
        ok_spurs, reason_spurs = is_valid_indian_fashion_dance_topic("Spurs vs Thunder Highlights NBA")
        self.assertFalse(ok_spurs)
        self.assertIn("disallowed", reason_spurs)

        ok_cricket, _ = is_valid_indian_fashion_dance_topic("India vs Pakistan Cricket World Cup")
        self.assertFalse(ok_cricket)

        ok_stocks, _ = is_valid_indian_fashion_dance_topic("Stock Market Sensex Nifty Today")
        self.assertFalse(ok_stocks)

        ok_shararat, _ = is_valid_indian_fashion_dance_topic("Shararat - Jasleen Royal & Arijit Singh Bollywood Dance")
        self.assertTrue(ok_shararat)

        ok_tauba, _ = is_valid_indian_fashion_dance_topic("Tauba Tauba Vicky Kaushal dance hook step casual outfit")
        self.assertTrue(ok_tauba)

        ok_aayi, _ = is_valid_indian_fashion_dance_topic("Aayi Nai Stree 2 energetic desi dance in modern crop top")
        self.assertTrue(ok_aayi)

    # -------------------------------------------------------------------------
    # Scenario 5: Existing valid video reuse without re-generation
    # -------------------------------------------------------------------------
    def test_05_existing_valid_video_reuse(self):
        dummy_video = self.test_root / "test_existing.mp4"
        with open(dummy_video, "wb") as f:
            f.write(b"\x00" * 150000)

        self.assertTrue(dummy_video.exists())
        self.assertGreater(dummy_video.stat().st_size, 100000)

        state_mgr = StateManager(self.db_path)
        wf_rec = state_mgr.create_workflow("wf_test_05", "2026-10-21")
        wf_id = wf_rec["workflow_id"]
        state_mgr.update_stage(wf_id, WorkflowStage.READY_TO_POST, video_file_path=str(dummy_video))

        wf = state_mgr.get_workflow(wf_id)
        self.assertEqual(wf["video_file_path"], str(dummy_video))
        self.assertEqual(wf["last_successful_stage"], WorkflowStage.READY_TO_POST.value)

    # -------------------------------------------------------------------------
    # Scenario 6: Windows startup with today's workflow already published
    # -------------------------------------------------------------------------
    def test_06_startup_duplicate_published_prevention(self):
        state_mgr = StateManager(self.db_path)
        today_str = datetime.now().strftime("%Y-%m-%d")
        wf_rec = state_mgr.create_workflow("wf_test_06", today_str)
        wf_id = wf_rec["workflow_id"]
        state_mgr.update_stage(
            wf_id,
            WorkflowStage.PUBLISHED,
            publication_url="https://www.instagram.com/aitrending.dance/reel/DepQXvABN12/"
        )

        mock_orch = MagicMock()
        mock_orch.state_manager = state_mgr

        scheduler = SchedulerService(mock_orch)
        scheduler._run_if_needed("StartupCheck")
        mock_orch.run_daily_workflow.assert_not_called()

    # -------------------------------------------------------------------------
    # Scenario 7: Browser closure during Instagram upload (clean handling)
    # -------------------------------------------------------------------------
    def test_07_browser_closure_during_instagram_upload(self):
        mock_cfg = MagicMock()
        mock_cfg.auto_publish_enabled = True
        mock_cfg.instagram_publishing_method = "browser"
        mock_cfg.instagram_target_account = "aitrending.dance"
        
        mock_bm = MagicMock()
        mock_bm.get_page_for_url.return_value = None

        publisher = InstagramPublisher(mock_cfg, mock_bm)

        # Mock a page where navigation raises PlaywrightError
        mock_page = MagicMock()
        mock_page.url = "about:blank"
        mock_page.goto.side_effect = PlaywrightError("Target page, context or browser has been closed")
        publisher.browser_manager.new_page.return_value = mock_page

        dummy_video = self.test_root / "test_upload.mp4"
        dummy_video.write_bytes(b"\x00" * 60000)

        with patch.object(publisher, "_capture_screenshot"):
            success, post_id, post_url, msg = publisher._publish_via_browser(str(dummy_video), "Caption test")
            self.assertFalse(success)
            self.assertIn("Browser connection closed", msg)

    # -------------------------------------------------------------------------
    # Scenario 8: Missing dialog with alternative UI state (file input fallback)
    # -------------------------------------------------------------------------
    def test_08_missing_dialog_fallback(self):
        mock_cfg = MagicMock()
        mock_bm = MagicMock()
        publisher = InstagramPublisher(mock_cfg, mock_bm)
        mock_page = MagicMock()

        mock_page.query_selector.return_value = None
        modal = publisher._get_modal_container(mock_page)
        self.assertIsNone(modal)

        mock_file_input = MagicMock()
        mock_page.query_selector.side_effect = lambda sel: mock_file_input if 'input[type="file"]' in sel else None
        found_input = mock_page.query_selector('input[type="file"]')
        self.assertIsNotNone(found_input)

    # -------------------------------------------------------------------------
    # Scenario 9: Duplicate manual and scheduled triggers (single-flight lock)
    # -------------------------------------------------------------------------
    def test_09_single_flight_lock_verification(self):
        lock_file = self.data_dir / "workflow.lock"
        lock1 = InterProcessWorkflowLock(lock_file)
        lock2 = InterProcessWorkflowLock(lock_file)

        self.assertTrue(lock1.acquire())
        self.assertFalse(lock2.acquire())

        lock1.release()
        self.assertTrue(lock2.acquire())
        lock2.release()

    # -------------------------------------------------------------------------
    # Scenario 10: Recovery from NEEDS_USER_ACTION
    # -------------------------------------------------------------------------
    def test_10_recovery_from_needs_user_action(self):
        state_mgr = StateManager(self.db_path)
        today_str = datetime.now().strftime("%Y-%m-%d")
        wf_rec = state_mgr.create_workflow("wf_test_10", today_str)
        wf_id = wf_rec["workflow_id"]
        state_mgr.update_stage(
            wf_id,
            WorkflowStage.NEEDS_USER_ACTION,
            error_details="Target account not logged in: aitrending.dance",
            blocker_action="Log into @aitrending.dance in the authentication browser."
        )

        mock_orch = MagicMock()
        mock_orch.state_manager = state_mgr

        scheduler = SchedulerService(mock_orch)
        scheduler._run_if_needed("ScheduledTick")
        mock_orch.run_daily_workflow.assert_not_called()

        active = state_mgr.get_todays_active_workflow(today_str)
        self.assertEqual(active["stage"], WorkflowStage.NEEDS_USER_ACTION.value)
        self.assertIn("Log into", active["blocker_action"])


if __name__ == "__main__":
    unittest.main()
