"""
app/browser_manager.py
─────────────────────────────────────────────────────────────────────────────
Playwright browser lifecycle — one thread rule
═══════════════════════════════════════════════
Playwright's synchronous API binds to the OS thread that calls
sync_playwright().start().  All subsequent calls (new_page, goto, etc.)
MUST happen on that same thread.  Any call from a different thread raises
"cannot switch to a different thread" → broken pipe → "Playwright connection
closed".

Ownership contract enforced here
─────────────────────────────────
• BrowserManager.ensure_context()  — initialises Playwright + launches /
  attaches to Chrome.  Must be called from the WORKFLOW thread only.
• BrowserManager.new_page()        — same thread restriction.
• BrowserManager.close()           — same thread restriction.
• is_cdp_available() / is_profile_locked() / get_diagnostic_info()
  — safe to call from any thread (no Playwright objects touched).

The Dashboard GUI thread NEVER calls any of the above.  It opens the
authentication browser via subprocess (plain Chrome invocation) so that
the Playwright-owning thread is never involved.
"""

import os
import time
import socket
import threading
import subprocess
from pathlib import Path
from typing import Optional, Tuple, List

from playwright.sync_api import (
    sync_playwright, BrowserContext, Page, Playwright, Browser,
    Error as PlaywrightError,
)

from .logger import app_logger
from .config_manager import AppConfig


class ChromeProfileLockedError(Exception):
    """Raised when the dedicated automation browser profile is in use by another process."""


class BrowserConnectionError(Exception):
    """Raised when Playwright cannot connect or the connection has dropped.
    Distinct from ChromeProfileLockedError (auth browser open) and from
    ChatGPT authentication failures."""


class BrowserManager:
    """
    Manages the Playwright lifecycle for the dedicated operator Chrome profile.

    Thread safety
    ─────────────
    All Playwright-touching methods (ensure_context, new_page, close,
    verify_authenticated_google_account) must be called from a single
    consistent thread — the workflow worker thread.

    Methods that are safe from any thread
    ─────────────────────────────────────
    is_cdp_available, is_profile_locked, get_diagnostic_info,
    launch_auth_browser_subprocess (opens Chrome via subprocess only).
    """

    def __init__(self, config: AppConfig):
        self.config = config
        self.profile_dir = Path(config.operator_profile_dir)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.executable_path = Path(config.chrome_executable_path)
        self.target_account = config.target_google_account
        self.remote_debugging_port = getattr(config, "remote_debugging_port", 9222)

        # Playwright state — only touched from the workflow thread.
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._is_cdp_connected: bool = False
        self._managed_pages: List[Page] = []

        # Track which OS thread owns the Playwright instance so we can
        # detect cross-thread misuse early.
        self._owner_thread_id: Optional[int] = None

    # ── Thread-safe helpers (no Playwright objects) ───────────────────────────

    def is_cdp_available(self) -> bool:
        """Returns True if Chrome's remote debugging port is accepting connections."""
        try:
            with socket.create_connection(("127.0.0.1", self.remote_debugging_port), timeout=0.8):
                return True
        except (socket.timeout, ConnectionRefusedError, OSError):
            return False

    def is_profile_locked(self) -> Tuple[bool, str]:
        """Returns (locked, reason).  Safe to call from any thread."""
        lock_file = self.profile_dir / "lockfile"
        if lock_file.exists():
            try:
                with open(lock_file, "r+b"):
                    pass
            except PermissionError:
                return True, f"Operator profile lockfile is in use ({lock_file})"
            except Exception as e:
                return True, f"Cannot open operator profile lockfile: {e}"
        return False, "Profile is not locked"

    def get_diagnostic_info(self) -> dict:
        """Non-sensitive diagnostic snapshot.  Safe from any thread."""
        is_locked, lock_reason = self.is_profile_locked()
        return {
            "chrome_executable_path": str(self.executable_path),
            "chrome_executable_exists": self.executable_path.exists(),
            "operator_profile_dir": str(self.profile_dir),
            "operator_profile_exists": self.profile_dir.exists(),
            "target_google_account": self.target_account,
            "remote_debugging_port": self.remote_debugging_port,
            "cdp_available": self.is_cdp_available(),
            "profile_locked": is_locked,
            "lock_reason": lock_reason,
            "headless": self.config.browser_headless,
            "cdp_connected": self._is_cdp_connected,
        }

    def launch_auth_browser_subprocess(
        self,
        extra_urls: Optional[List[str]] = None,
    ) -> int:
        """
        Opens the dedicated operator Chrome profile in a VISIBLE window via
        subprocess — no Playwright involved.  Safe to call from the GUI thread.

        Returns the PID of the spawned Chrome process, or -1 on failure.
        """
        chatgpt_url = self.config.chatgpt_conversation_url or "https://chatgpt.com/"
        gemini_url = getattr(self.config, "gemini_url", "https://gemini.google.com/")
        urls = [chatgpt_url, gemini_url] + (extra_urls or [])

        cmd = [
            str(self.executable_path),
            f"--user-data-dir={self.profile_dir}",
            f"--remote-debugging-port={self.remote_debugging_port}",
            "--no-first-run",
            "--no-default-browser-check",
        ] + urls

        try:
            proc = subprocess.Popen(cmd)
            app_logger.info(
                f"Launched auth browser via subprocess (PID {proc.pid}): {self.profile_dir}"
            )
            return proc.pid
        except Exception as e:
            app_logger.error(f"Failed to launch auth browser via subprocess: {e}")
            return -1

    # ── Workflow-thread-only methods ──────────────────────────────────────────

    def _assert_owner_thread(self):
        """Raises RuntimeError if called from a thread that does not own Playwright."""
        tid = threading.get_ident()
        if self._owner_thread_id is None:
            self._owner_thread_id = tid
        elif self._owner_thread_id != tid:
            raise RuntimeError(
                f"BrowserManager Playwright methods must be called from the owning thread "
                f"(owner={self._owner_thread_id}, caller={tid}). "
                "Do not call browser operations from the GUI thread or multiple worker threads."
            )

    def _is_context_alive(self) -> bool:
        """Returns True only if the cached context has a live connection."""
        if self._context is None:
            return False
        try:
            # Accessing .pages on a closed/dead context raises PlaywrightError
            _ = self._context.pages
            return True
        except Exception:
            return False

    def ensure_context(self, headless: Optional[bool] = None) -> BrowserContext:
        """
        Returns a live BrowserContext, (re)creating it if necessary.

        Call only from the workflow worker thread.
        Raises ChromeProfileLockedError or BrowserConnectionError on failure.
        """
        self._assert_owner_thread()

        # Return cached context if still alive
        if self._is_context_alive():
            return self._context

        # Cached context is dead — reset state
        self._context = None
        self._browser = None
        self._is_cdp_connected = False

        is_headless = self.config.browser_headless if headless is None else headless
        cdp_active = self.is_cdp_available()
        is_locked, lock_reason = self.is_profile_locked()

        # If no CDP and profile is locked → another browser owns the profile
        if not cdp_active and is_locked:
            msg = (
                f"The operator Chrome profile at '{self.profile_dir}' is locked ({lock_reason}). "
                f"Close the open authentication browser window, or ensure it runs with "
                f"--remote-debugging-port={self.remote_debugging_port}."
            )
            app_logger.warning(msg)
            raise ChromeProfileLockedError(msg)

        # Initialise Playwright Node driver (idempotent on the owning thread)
        if self._playwright is None:
            app_logger.info("Starting Playwright Node driver...")
            try:
                self._playwright = sync_playwright().start()
            except Exception as e:
                raise BrowserConnectionError(f"Failed to start Playwright: {e}") from e

        # Path A: Attach via CDP if the debugging port is open
        if cdp_active:
            cdp_endpoint = f"http://127.0.0.1:{self.remote_debugging_port}"
            app_logger.info(
                f"Attaching to automation browser via CDP at {cdp_endpoint} "
                f"(profile: {self.profile_dir}, account: {self.target_account})"
            )
            try:
                self._browser = self._playwright.chromium.connect_over_cdp(cdp_endpoint)
                self._is_cdp_connected = True
                self._context = (
                    self._browser.contexts[0]
                    if self._browser.contexts
                    else self._browser.new_context()
                )
                app_logger.info("CDP connection established successfully.")
                return self._context
            except Exception as e:
                app_logger.warning(f"CDP connection failed at {cdp_endpoint}: {e}")
                self._browser = None
                self._context = None
                self._is_cdp_connected = False
                # Fall through to direct launch

        # Path B: Launch the dedicated profile directly via Playwright
        if not self.executable_path.exists():
            raise BrowserConnectionError(
                f"Chrome executable not found at '{self.executable_path}'."
            )

        app_logger.info(
            f"Launching dedicated operator Chrome profile:\n"
            f"  Executable : {self.executable_path}\n"
            f"  Profile    : {self.profile_dir}\n"
            f"  Account    : {self.target_account}\n"
            f"  Headless   : {is_headless}"
        )

        try:
            self._context = self._playwright.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                executable_path=str(self.executable_path),
                headless=is_headless,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-first-run",
                    "--no-default-browser-check",
                    "--disable-infobars",
                    "--disable-session-crashed-bubble",
                ],
                viewport={"width": 1280, "height": 800},
                accept_downloads=True,
            )
            self._is_cdp_connected = False
            app_logger.info("Persistent Playwright context launched.")
            return self._context
        except Exception as e:
            err_text = str(e)
            app_logger.error(f"Playwright persistent context launch failed: {err_text}")
            if any(k in err_text.lower() for k in ("timeout", "closed", "singleton", "already")):
                raise ChromeProfileLockedError(
                    f"Could not open operator profile at '{self.profile_dir}'. "
                    "Another process may hold the profile lock. "
                    f"Use --remote-debugging-port={self.remote_debugging_port} or close the other instance."
                ) from e
            raise BrowserConnectionError(f"Browser launch failed: {e}") from e

    def get_page_for_url(self, url_pattern: str) -> Optional[Page]:
        """
        In CDP mode, searches existing open tabs for one matching url_pattern.
        Returns the matching Page if found, or None.
        Call only from the workflow worker thread.
        """
        ctx = self.ensure_context()
        try:
            for p in ctx.pages:
                if not p.is_closed() and url_pattern in p.url:
                    return p
        except Exception as e:
            app_logger.warning(f"Error checking existing pages: {e}")
        return None

    def new_page(self, prefer_existing_url: Optional[str] = None) -> Page:
        """
        Creates or returns a tracked page in the active context.
        If prefer_existing_url is provided and matching tab is open in CDP mode, reuses it.
        Otherwise creates a new page.
        Call only from the workflow worker thread.
        """
        ctx = self.ensure_context()
        if prefer_existing_url:
            existing = self.get_page_for_url(prefer_existing_url)
            if existing:
                app_logger.info(f"Reusing existing open tab for '{prefer_existing_url}': {existing.url}")
                return existing

        # In CDP mode, if there's an unused blank page or matching open tab, use it
        if self._is_cdp_connected and ctx.pages:
            for p in ctx.pages:
                if not p.is_closed() and p.url in ["about:blank", "chrome://newtab/"]:
                    return p

        page = ctx.new_page()
        self._managed_pages.append(page)
        return page


    def verify_authenticated_google_account(
        self, page: Page
    ) -> Tuple[bool, Optional[str], str]:
        """Verifies the Google session in the browser.  Workflow thread only."""
        try:
            page.goto(
                "https://myaccount.google.com/",
                wait_until="domcontentloaded",
                timeout=30000,
            )
            time.sleep(3)
            current_url = page.url
            if "signin" in current_url or "InteractiveLogin" in current_url:
                return False, None, "Google session is unauthenticated (redirected to login)."

            page_content = page.content()
            target_email = self.target_account.lower()
            if target_email in page_content.lower():
                return True, self.target_account, f"Authenticated as {self.target_account}"

            import re
            emails = re.findall(r"[\w\.-]+@gmail\.com", page_content)
            found = emails[0] if emails else "Unknown"
            return (
                False,
                found,
                f"Logged in as '{found}', but target is '{self.target_account}'.",
            )
        except Exception as e:
            return False, None, f"Failed verifying Google authentication: {e}"

    def close(self):
        """
        Cleans up Playwright resources.  Must be called from the owning workflow thread.

        For CDP sessions: disconnects Playwright but does NOT close Chrome
        (the authentication browser remains open for the user).
        For direct-launch sessions: closes the Playwright-owned context and driver.
        """
        # Allow close() from the owner thread or when no owner is set yet
        tid = threading.get_ident()
        if self._owner_thread_id is not None and self._owner_thread_id != tid:
            app_logger.warning(
                f"BrowserManager.close() called from thread {tid} but owner is "
                f"{self._owner_thread_id}. Skipping to avoid cross-thread Playwright error."
            )
            return

        try:
            # Close operator-managed pages first
            for p in list(self._managed_pages):
                try:
                    if not p.is_closed():
                        p.close()
                except Exception:
                    pass
            self._managed_pages.clear()

            if self._is_cdp_connected:
                # Disconnect Playwright from CDP — do NOT close Chrome itself
                if self._browser:
                    try:
                        self._browser.close()
                    except Exception:
                        pass
                self._browser = None
                self._context = None
                self._is_cdp_connected = False
                app_logger.info("Playwright disconnected from Chrome CDP session.")
            else:
                if self._context:
                    try:
                        self._context.close()
                    except Exception:
                        pass
                    self._context = None
                if self._browser:
                    try:
                        self._browser.close()
                    except Exception:
                        pass
                    self._browser = None
                app_logger.info("Playwright persistent context closed.")

        except Exception as e:
            app_logger.warning(f"Error during browser cleanup: {e}")
        finally:
            # Stop Playwright Node driver last
            if self._playwright:
                try:
                    self._playwright.stop()
                except Exception:
                    pass
                self._playwright = None
            # Reset owner so a new workflow thread can acquire it
            self._owner_thread_id = None
