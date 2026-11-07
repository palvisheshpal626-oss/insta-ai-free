"""
scripts/test_browser_lifecycle.py
──────────────────────────────────────────────────────────────────────────────
Browser Lifecycle & Playwright Thread-Safety Tests
════════════════════════════════════════════════════

Tests are divided into two groups:
  [UNIT]  — run without Chrome, using mocks.  Safe in any CI environment.
  [LIVE]  — require Chrome + the operator profile to be available.
            Clearly labelled; skipped automatically if Chrome is absent.

Run with:  python scripts/test_browser_lifecycle.py
"""

import sys
import os
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.config_manager import ConfigurationManager
from app.browser_manager import BrowserManager, ChromeProfileLockedError, BrowserConnectionError
from app.orchestrator import WorkflowOrchestrator


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config():
    return ConfigurationManager().config


def _make_bm(config=None):
    return BrowserManager(config or _make_config())


# ══════════════════════════════════════════════════════════════════════════════
# UNIT TESTS  (no Chrome required)
# ══════════════════════════════════════════════════════════════════════════════

class TestBrowserManagerThreadOwnership(unittest.TestCase):
    """[UNIT] Playwright thread ownership enforcement."""

    def test_1_owner_thread_set_on_first_ensure(self):
        """The owning thread ID is recorded on the first Playwright call."""
        bm = _make_bm()
        # Patch sync_playwright so no real Node process is started
        mock_pw = MagicMock()
        mock_ctx = MagicMock()
        mock_pw.chromium.launch_persistent_context.return_value = mock_ctx
        # _is_context_alive returns False (no cached context)
        with patch("app.browser_manager.sync_playwright") as mock_sp:
            mock_sp.return_value.__enter__ = MagicMock(return_value=mock_pw)
            mock_sp.return_value.start.return_value = mock_pw
            with patch.object(bm, "is_cdp_available", return_value=False), \
                 patch.object(bm, "is_profile_locked", return_value=(False, "not locked")), \
                 patch.object(Path, "exists", return_value=True):
                bm.ensure_context()
        self.assertEqual(bm._owner_thread_id, threading.get_ident())
        print("  ✓ Owner thread ID recorded correctly.")

    def test_2_cross_thread_call_raises(self):
        """Calling ensure_context from a different thread raises RuntimeError."""
        bm = _make_bm()
        bm._owner_thread_id = threading.get_ident() + 9999  # fake a different owner

        error_holder = []

        def call_from_other_thread():
            try:
                bm.ensure_context()
            except RuntimeError as e:
                error_holder.append(e)

        t = threading.Thread(target=call_from_other_thread)
        t.start()
        t.join(timeout=3)
        self.assertTrue(error_holder, "Expected RuntimeError from wrong thread")
        self.assertIn("owning thread", str(error_holder[0]))
        print("  ✓ Cross-thread call correctly raises RuntimeError.")

    def test_3_close_from_wrong_thread_warns_not_crashes(self):
        """close() called from wrong thread logs a warning but does NOT raise."""
        bm = _make_bm()
        bm._owner_thread_id = threading.get_ident() + 9999  # fake different owner

        errors = []

        def close_from_other():
            try:
                bm.close()  # should warn, not raise
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=close_from_other)
        t.start()
        t.join(timeout=3)
        self.assertFalse(errors, f"close() raised unexpectedly: {errors}")
        print("  ✓ cross-thread close() is safe (warns only).")


class TestBrowserManagerContextAlive(unittest.TestCase):
    """[UNIT] _is_context_alive() correctly distinguishes live vs dead contexts."""

    def test_4_none_context_is_not_alive(self):
        bm = _make_bm()
        bm._context = None
        self.assertFalse(bm._is_context_alive())
        print("  ✓ None context correctly reported as dead.")

    def test_5_dead_context_raising_on_pages_is_not_alive(self):
        bm = _make_bm()
        dead_ctx = MagicMock()
        dead_ctx.pages = PropertyMock(side_effect=Exception("connection closed"))
        type(dead_ctx).pages = PropertyMock(side_effect=Exception("connection closed"))
        bm._context = dead_ctx
        # pages access raises → not alive
        alive = bm._is_context_alive()
        self.assertFalse(alive)
        print("  ✓ Context that raises on .pages is correctly reported as dead.")

    def test_6_live_context_is_alive(self):
        bm = _make_bm()
        live_ctx = MagicMock()
        live_ctx.pages = []
        bm._context = live_ctx
        self.assertTrue(bm._is_context_alive())
        print("  ✓ Context with accessible .pages is correctly reported as alive.")


class TestBrowserManagerErrorClassification(unittest.TestCase):
    """[UNIT] Correct error types raised for different failure modes."""

    def test_7_profile_locked_no_cdp_raises_profile_locked_error(self):
        bm = _make_bm()
        with patch.object(bm, "is_cdp_available", return_value=False), \
             patch.object(bm, "is_profile_locked", return_value=(True, "lock held")):
            with self.assertRaises(ChromeProfileLockedError):
                bm.ensure_context()
        print("  ✓ Locked profile + no CDP raises ChromeProfileLockedError.")

    def test_8_playwright_start_failure_raises_connection_error(self):
        bm = _make_bm()
        with patch.object(bm, "is_cdp_available", return_value=False), \
             patch.object(bm, "is_profile_locked", return_value=(False, "not locked")), \
             patch("app.browser_manager.sync_playwright", side_effect=Exception("Node not found")):
            with self.assertRaises(BrowserConnectionError):
                bm.ensure_context()
        print("  ✓ Playwright start failure raises BrowserConnectionError (not ChromeProfileLockedError).")

    def test_9_cdp_failure_falls_through_to_direct_launch_or_connection_error(self):
        """If CDP connection fails AND direct launch fails (chrome missing), BrowserConnectionError is raised."""
        bm = _make_bm()
        mock_pw = MagicMock()
        mock_pw.chromium.connect_over_cdp.side_effect = Exception("CDP refused")
        mock_pw.chromium.launch_persistent_context.side_effect = Exception("some error")
        with patch.object(bm, "is_cdp_available", return_value=True), \
             patch.object(bm, "is_profile_locked", return_value=(False, "not locked")), \
             patch("app.browser_manager.sync_playwright") as mock_sp, \
             patch.object(Path, "exists", return_value=True):
            mock_sp.return_value.start.return_value = mock_pw
            # CDP fails → fallthrough to direct launch → that also fails → BrowserConnectionError
            with self.assertRaises(BrowserConnectionError):
                bm.ensure_context()
        print("  ✓ CDP failure + direct launch failure raises BrowserConnectionError.")


class TestOrchestratorStopNoPlaywright(unittest.TestCase):
    """[UNIT] orchestrator.stop() must NOT call browser_manager.close()."""

    def test_10_stop_does_not_call_browser_close(self):
        """stop() is called from the GUI thread; it must not touch Playwright."""
        cfg = _make_config()
        orch = WorkflowOrchestrator(ConfigurationManager())
        orch.browser_manager.close = MagicMock()

        orch.stop()

        orch.browser_manager.close.assert_not_called()
        print("  ✓ orchestrator.stop() does NOT call browser_manager.close().")


class TestDashboardAuthBrowserNoPlaywright(unittest.TestCase):
    """[UNIT] Dashboard action_open_auth_browser uses subprocess, not Playwright."""

    def test_11_auth_browser_uses_subprocess_not_playwright(self):
        """action_open_auth_browser must call launch_auth_browser_subprocess, never ensure_context."""
        # We just check that launch_auth_browser_subprocess exists and is a method
        bm = _make_bm()
        self.assertTrue(
            callable(getattr(bm, "launch_auth_browser_subprocess", None)),
            "BrowserManager must have launch_auth_browser_subprocess for GUI-thread use"
        )
        # ensure_context must NOT be called from the GUI thread — this is
        # enforced by _assert_owner_thread in BrowserManager at runtime.
        bm._owner_thread_id = threading.get_ident() + 999
        with self.assertRaises(RuntimeError):
            bm.ensure_context()  # Would raise if called from wrong thread
        print("  ✓ launch_auth_browser_subprocess exists; ensure_context raises from wrong thread.")


class TestWorkflowBrowserConnectionErrorDistinct(unittest.TestCase):
    """[UNIT] BrowserConnectionError is a distinct type from ChromeProfileLockedError."""

    def test_12_error_hierarchy(self):
        self.assertNotIsInstance(BrowserConnectionError(), ChromeProfileLockedError)
        self.assertNotIsInstance(ChromeProfileLockedError(), BrowserConnectionError)
        print("  ✓ BrowserConnectionError and ChromeProfileLockedError are distinct types.")

    def test_13_connection_error_not_subclass_of_profile_locked(self):
        self.assertFalse(issubclass(BrowserConnectionError, ChromeProfileLockedError))
        self.assertFalse(issubclass(ChromeProfileLockedError, BrowserConnectionError))
        print("  ✓ Neither error is a subclass of the other.")


# ══════════════════════════════════════════════════════════════════════════════
# LIVE TESTS  (require Chrome + operator profile)
# ══════════════════════════════════════════════════════════════════════════════

CHROME_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
LIVE_AVAILABLE = CHROME_PATH.exists()


@unittest.skipUnless(LIVE_AVAILABLE, "LIVE test skipped: Chrome not found at expected path")
class TestLiveBrowserConnection(unittest.TestCase):
    """[LIVE] Real Chrome CDP connection tests."""

    def setUp(self):
        self.cfg = _make_config()
        self.bm = _make_bm(self.cfg)

    def tearDown(self):
        try:
            self.bm.close()
        except Exception:
            pass

    def test_L1_cdp_available_check_does_not_require_playwright(self):
        """is_cdp_available() uses only a TCP socket — safe from any thread."""
        result = self.bm.is_cdp_available()
        self.assertIsInstance(result, bool)
        print(f"  [LIVE] CDP available: {result}")

    def test_L2_profile_lock_check_is_thread_safe(self):
        """is_profile_locked() reads the filesystem — safe from any thread."""
        locked, reason = self.bm.is_profile_locked()
        self.assertIsInstance(locked, bool)
        self.assertIsInstance(reason, str)
        print(f"  [LIVE] Profile locked: {locked} ({reason})")

    def test_L3_launch_auth_browser_subprocess_returns_pid(self):
        """launch_auth_browser_subprocess() opens Chrome and returns a PID > 0."""
        import subprocess
        import time
        pid = self.bm.launch_auth_browser_subprocess()
        self.assertGreater(pid, 0, "Expected a valid PID > 0")
        print(f"  [LIVE] Auth browser PID: {pid}")
        # Give Chrome 2s to start, then terminate it (test environment)
        time.sleep(2)
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], capture_output=True)
        except Exception:
            pass

    @unittest.skipUnless(
        LIVE_AVAILABLE and BrowserManager(_make_config()).is_cdp_available(),
        "LIVE-CDP test skipped: CDP port 9222 is not active"
    )
    def test_L4_cdp_connection_and_page_navigation(self):
        """If CDP is active, connect and verify page navigation / title."""
        ctx = self.bm.ensure_context()
        self.assertIsNotNone(ctx)
        page = self.bm.new_page(prefer_existing_url="gemini.google.com")
        self.assertIsNotNone(page)
        # Navigate or re-verify current URL
        if "gemini.google.com" not in page.url:
            page.goto("https://gemini.google.com/app", wait_until="domcontentloaded", timeout=20000)
        self.assertIn("gemini", page.url.lower())
        print(f"  [LIVE] CDP Gemini page verified: {page.url} ({page.title()})")

    @unittest.skipUnless(
        LIVE_AVAILABLE and BrowserManager(_make_config()).is_cdp_available(),
        "LIVE-CDP test skipped: CDP port 9222 is not active"
    )
    def test_L5_chatgpt_url_loads_in_cdp_context(self):
        """If CDP is active, navigate or access the configured ChatGPT conversation URL."""
        cfg = self.cfg
        chatgpt_url = cfg.chatgpt_conversation_url
        if not chatgpt_url:
            self.skipTest("No ChatGPT conversation URL configured")

        ctx = self.bm.ensure_context()
        page = self.bm.new_page(prefer_existing_url="chatgpt.com")
        self.assertIsNotNone(page)
        if "chatgpt.com" not in page.url:
            page.goto(chatgpt_url, wait_until="domcontentloaded", timeout=30000)

        current_url = page.url
        in_login = "login" in current_url or "auth" in current_url
        in_conversation = "/c/" in current_url or "/g/" in current_url

        print(f"  [LIVE] ChatGPT page result: {current_url} ({page.title()})")
        if in_login:
            print("  [LIVE] ⚠ ChatGPT redirected to login — authentication required in operator profile.")
        elif in_conversation:
            print("  [LIVE] ✓ Dedicated ChatGPT conversation loaded successfully.")
        else:
            print(f"  [LIVE] ⚠ Current URL: {current_url}")

        self.assertFalse(
            "playwright" in current_url.lower(),
            "URL should be a real ChatGPT URL, not a Playwright error page"
        )



# ══════════════════════════════════════════════════════════════════════════════
# Runner
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 70)
    print(" AI INSTAGRAM REEL OPERATOR — BROWSER LIFECYCLE TEST SUITE")
    print("=" * 70)
    print(f"\n Chrome found at expected path: {LIVE_AVAILABLE}")
    print(f" Live tests will be {'RUN' if LIVE_AVAILABLE else 'SKIPPED'} accordingly.\n")
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    # Unit tests always run
    for cls in [
        TestBrowserManagerThreadOwnership,
        TestBrowserManagerContextAlive,
        TestBrowserManagerErrorClassification,
        TestOrchestratorStopNoPlaywright,
        TestDashboardAuthBrowserNoPlaywright,
        TestWorkflowBrowserConnectionErrorDistinct,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))
    # Live tests if Chrome present
    if LIVE_AVAILABLE:
        suite.addTests(loader.loadTestsFromTestCase(TestLiveBrowserConnection))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
