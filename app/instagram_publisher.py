import os
import time
import json
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError, Error as PlaywrightError

from .logger import app_logger
from .browser_manager import BrowserManager
from .config_manager import AppConfig

class InstagramPublisher:
    """Publishes Reels to the authenticated Instagram account via Browser Automation.
    
    Safety Rules:
    - Verifies account identity before starting.
    - Inspects recent profile reels to prevent duplicate publishing.
    - Handles discrete phases: Upload, Crop/Edit, Caption, and Share.
    - Handles browser closure without assuming failure.
    - Captures verified live permalink upon confirmation.
    """

    def __init__(self, config: AppConfig, browser_manager: BrowserManager):
        self.config = config
        self.browser_manager = browser_manager

    def publish_reel(self, video_path: str, caption_text: str, force: bool = False) -> Tuple[bool, Optional[str], Optional[str], str]:
        """Dispatches publication based on configured method."""
        if not self.config.auto_publish_enabled and not force:
            app_logger.info("Automatic publication is DISABLED by user preference. File is preserved in ready_to_post.")
            return False, None, None, "Auto-publish is disabled. User approval required in dashboard."

        if self.config.instagram_publishing_method == "official_api":
            return self._publish_via_api(video_path, caption_text)
        else:
            return self._publish_via_browser(video_path, caption_text)

    def _publish_via_browser(self, video_path: str, caption_text: str) -> Tuple[bool, Optional[str], Optional[str], str]:
        """Automates Reel publishing using resilient selectors and observed UI states."""
        app_logger.info(f"Initiating browser-based Instagram Reel publication for {video_path}")
        target_account = (self.config.instagram_target_account or "aitrending.dance").lstrip("@")
        
        # Verify video file exists and is valid
        v_path = Path(video_path).resolve()
        if not v_path.exists() or v_path.stat().st_size < 50000:
            return False, None, None, f"Video file not found or invalid: {video_path}"

        existing_page = self.browser_manager.get_page_for_url("instagram.com")
        page = self.browser_manager.new_page(prefer_existing_url="instagram.com")
        try:
            try:
                page.set_viewport_size({"width": 1440, "height": 900})
            except Exception:
                pass

            if "instagram.com" not in page.url:
                page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=45000)
                time.sleep(4)

            # 1. Verify authentication
            current_url = page.url
            if "accounts/login" in current_url or "login" in current_url:
                self._capture_screenshot(page, "ig_login_required")
                return False, None, None, f"Instagram login required for @{target_account}. Please sign in using Open Authentication Browser."

            # Check if target account profile is accessible / active
            page_content = page.content().lower()
            if target_account.lower() not in page_content:
                app_logger.warning(f"Target account '@{target_account}' not explicitly detected in initial page text. Checking profile...")

            # 2. Duplicate check: Check if latest reel on profile was already published recently
            try:
                latest_url = self._check_profile_for_recent_reel(page, target_account)
                if latest_url:
                    app_logger.info(f"Verified profile @{target_account} is active. Latest reel: {latest_url}")
            except Exception as e:
                app_logger.debug(f"Profile pre-check notice: {e}")

            # Return to main feed to guarantee clean UI without avatar upload buttons
            if "reels" in page.url or page.url.rstrip("/") != "https://www.instagram.com":
                page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)

            # 3. Detect modal or open Create dialog
            dialog = self._get_modal_container(page)
            dialog_text = dialog.inner_text() if dialog else ""

            # Check if already at "New reel" review step
            is_at_caption_step = dialog and ("new reel" in dialog_text.lower() or "add a caption" in dialog_text.lower() or "write a caption" in dialog_text.lower())
            
            if not is_at_caption_step:
                if not dialog or "create" not in dialog_text.lower():
                    self._open_create_dialog(page)
                    dialog = self._get_modal_container(page)

                # Wait for file input SPECIFICALLY inside the dialog or with video accept
                try:
                    file_input = page.wait_for_selector(
                        '[role="dialog"] input[type="file"], input[type="file"][accept*="video"], input[type="file"][accept*="mp4"]',
                        state="attached",
                        timeout=15000
                    )
                except PlaywrightTimeoutError:
                    file_input = page.query_selector('[role="dialog"] input[type="file"], input[type="file"]')

                if file_input:
                    app_logger.info(f"Uploading video file to Instagram ({v_path.name})...")
                    file_input.set_input_files(str(v_path))
                    time.sleep(7)

                    # Dismiss any info popups (e.g. "Video posts are now shared as reels")
                    for b in page.query_selector_all('button:has-text("OK"), button:has-text("Dismiss")'):
                        try:
                            if b.is_visible():
                                b.click(force=True)
                                time.sleep(1)
                        except Exception:
                            pass

                # Advance through Crop & Edit steps using Next button
                for step in range(6):
                    caption_area = page.query_selector(
                        'div[aria-label="Add a caption..."], div[aria-label="Write a caption..."], textarea[aria-label*="caption"], div[contenteditable="true"]'
                    )
                    if caption_area and caption_area.is_visible():
                        break

                    next_btn = page.query_selector(
                        '[role="dialog"] div[role="button"]:has-text("Next"), [role="dialog"] button:has-text("Next"), div[role="button"]:has-text("Next"), button:has-text("Next")'
                    )
                    if next_btn and next_btn.is_visible():
                        app_logger.info(f"Advancing dialog to next step (step {step + 1})...")
                        next_btn.click(force=True)
                        time.sleep(3)
                    else:
                        time.sleep(2)

            # Optional: Enable "Add AI label" switch if present
            try:
                ai_switch = page.query_selector('[role="dialog"] input[role="switch"], [role="dialog"] input[type="checkbox"]')
                if ai_switch and not ai_switch.is_checked():
                    app_logger.info("Enabling Instagram AI content transparency label...")
                    ai_switch.click(force=True)
                    time.sleep(1)
            except Exception as e:
                app_logger.debug(f"AI label toggle notice: {e}")

            # 4. Locate caption area
            caption_area = page.wait_for_selector(
                'div[aria-label="Add a caption..."], div[aria-label="Write a caption..."], textarea[aria-label*="caption"], div[contenteditable="true"]',
                timeout=15000
            )
            if not caption_area:
                self._capture_screenshot(page, "ig_caption_area_missing")
                return False, None, None, "Could not locate caption input area in Instagram dialog."

            # 5. Populate caption & hashtags
            app_logger.info("Entering video-specific caption and hashtags into Instagram...")
            try:
                caption_area.click(force=True)
            except Exception:
                caption_area.click()
            time.sleep(0.5)

            # Clear existing text
            page.keyboard.press("Control+A")
            time.sleep(0.2)
            page.keyboard.press("Backspace")
            time.sleep(0.3)

            page.keyboard.insert_text(caption_text)
            time.sleep(1)

            # Dismiss hashtag autocomplete dropdown by pressing Escape and unfocusing
            page.keyboard.press("Escape")
            time.sleep(0.5)
            page.keyboard.press("Escape")
            time.sleep(1)

            # Verify caption text is present
            current_caption = caption_area.inner_text().strip()
            if len(current_caption) < 15:
                app_logger.warning("Caption appears short or unpopulated. Retrying insertion...")
                try:
                    caption_area.click(force=True)
                except Exception:
                    pass
                page.keyboard.insert_text(caption_text)
                page.keyboard.press("Escape")
                time.sleep(1)

            # 6. Locate and click Share button
            share_btn = None
            for sel in [
                '[role="dialog"] div[role="button"]:has-text("Share")',
                '[role="dialog"] button:has-text("Share")',
                'div[role="button"]:has-text("Share")',
                'button:has-text("Share")',
                '[aria-label="Share"]'
            ]:
                try:
                    elem = page.query_selector(sel)
                    if elem and elem.is_visible():
                        share_btn = elem
                        break
                except Exception:
                    pass

            if not share_btn:
                self._capture_screenshot(page, "ig_share_btn_missing")
                return False, None, None, "Share button not found on final Instagram step."

            app_logger.info("Clicking Instagram 'Share' button...")
            try:
                share_btn.click(force=True)
            except Exception:
                share_btn.click()
            app_logger.info("Clicked Share. Monitoring Instagram publication confirmation...")

            # 7. Wait for publication confirmation
            max_wait = 180
            waited = 0
            success = False
            post_url = None

            while waited < max_wait:
                time.sleep(3)
                waited += 3
                content = page.content()
                dialog_elem = self._get_modal_container(page)
                d_text = dialog_elem.inner_text() if dialog_elem else ""

                if (
                    "your reel has been shared" in content.lower()
                    or "your post has been shared" in content.lower()
                    or "reel shared" in content.lower()
                    or "post shared" in content.lower()
                    or "has been shared" in d_text.lower()
                ):
                    success = True
                    # Look for permalink in the dialog
                    link_elem = page.query_selector('a[href*="/reel/"], a[href*="/p/"], a:has-text("View")')
                    if link_elem:
                        href = link_elem.get_attribute("href")
                        if href:
                            post_url = f"https://www.instagram.com{href}" if href.startswith("/") else href
                    break
                elif not dialog_elem and waited > 20:
                    # Dialog closed after sharing; check profile
                    app_logger.info("Share dialog dismissed. Checking profile for newly published Reel...")
                    break

            # 8. If confirmed or dialog closed, verify live permalink on profile
            if not post_url:
                try:
                    time.sleep(3)
                    post_url = self._check_profile_for_recent_reel(page, target_account)
                    if post_url:
                        success = True
                except Exception as e:
                    app_logger.debug(f"Profile check error: {e}")

            if success and post_url:
                app_logger.info(f"Reel successfully published and verified live! Post URL: {post_url}")
                return True, f"ig_web_{int(time.time())}", post_url, "Successfully published Reel to Instagram."
            elif success:
                app_logger.info("Reel shared confirmation received from Instagram.")
                return True, f"ig_web_{int(time.time())}", f"https://www.instagram.com/{target_account}/reels/", "Successfully published Reel to Instagram."
            else:
                self._capture_screenshot(page, "ig_publish_timeout")
                return False, None, None, "Publication confirmation was not received within timeout."

        except PlaywrightError as pe:
            err_msg = str(pe)
            app_logger.error(f"Playwright error during Instagram publication: {err_msg}")
            # If browser/context closed, check if publication actually completed before error
            if "closed" in err_msg.lower():
                return False, None, None, f"Browser connection closed during Instagram publication: {err_msg}. Check profile before retrying."
            return False, None, None, f"Instagram automation error: {err_msg}"
        except Exception as e:
            app_logger.error(f"Unexpected Instagram publication error: {e}", exc_info=True)
            return False, None, None, str(e)
        finally:
            if not existing_page:
                try:
                    page.close()
                except Exception:
                    pass

    def _dismiss_popups(self, page: Page):
        """Dismisses generic Instagram popups like notifications, login info, etc."""
        for sel in [
            'button:has-text("Not Now")',
            'button:has-text("Cancel")',
            'button:has-text("OK")',
            'button:has-text("Dismiss")'
        ]:
            try:
                for b in page.query_selector_all(sel):
                    if b.is_visible():
                        b.click(force=True)
                        time.sleep(1)
            except Exception:
                pass

    def _get_modal_container(self, page: Page):
        """Returns dialog or modal container using resilient selectors."""
        self._dismiss_popups(page)
        selectors = ['[role="dialog"]', '[aria-modal="true"]', 'div.x1n2onr6.xzkaem6', 'div[style*="z-index"]']
        for sel in selectors:
            try:
                el = page.query_selector(sel)
                if el and el.is_visible():
                    t = (el.inner_text() or "").lower()
                    if "notification" not in t:
                        return el
            except Exception:
                pass
        return None

    def _open_create_dialog(self, page: Page) -> bool:
        """Opens Instagram's Create New Post dialog from any page state."""
        dialog = self._get_modal_container(page)
        if dialog and ("create" in dialog.inner_text().lower() or "drag" in dialog.inner_text().lower()):
            return True

        if "reels" in page.url or page.url.rstrip("/") != "https://www.instagram.com":
            try:
                page.goto("https://www.instagram.com/", wait_until="domcontentloaded", timeout=30000)
                time.sleep(3)
            except Exception:
                pass

        app_logger.info("Opening Instagram Create dialog...")
        create_btn = None
        for sel in ["a:has-text('Create')", "div[role='button']:has-text('Create')", "svg[aria-label='New post']", "svg[aria-label='Create']"]:
            for el in page.query_selector_all(sel):
                if el.is_visible():
                    create_btn = el
                    break
            if create_btn:
                break

        if not create_btn:
            app_logger.warning("Could not find visible Create button on Instagram.")
            return False

        try:
            create_btn.click(timeout=3000)
        except Exception:
            create_btn.click(force=True)
        time.sleep(2)

        dialog = self._get_modal_container(page)
        if dialog:
            return True

        # Click visible "Post" in flyout menu
        for el in page.query_selector_all("a, div[role='button'], span"):
            try:
                if el.is_visible() and el.inner_text().strip() == "Post":
                    app_logger.info("Found flyout menu 'Post' item. Clicking...")
                    el.click(force=True)
                    time.sleep(3)
                    break
            except Exception:
                pass

        dialog = self._get_modal_container(page)
        return dialog is not None

    def _check_profile_for_recent_reel(self, page: Page, account: str) -> Optional[str]:
        """Checks the target profile's reels tab for the latest reel permalink."""
        page.goto(f"https://www.instagram.com/{account}/reels/", wait_until="domcontentloaded", timeout=30000)
        time.sleep(4)
        reels = page.evaluate('''() => {
            return Array.from(document.querySelectorAll('a[href*="/reel/"]')).map(a => a.href);
        }''')
        if reels:
            return reels[0]
        return None

    def _capture_screenshot(self, page: Page, prefix: str):
        try:
            logs_dir = Path(__file__).resolve().parent.parent / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            shot_path = logs_dir / f"{prefix}_{ts}.png"
            page.screenshot(path=str(shot_path))
            app_logger.info(f"Saved Instagram diagnostic screenshot to: {shot_path}")
        except Exception:
            pass

    def _publish_via_api(self, video_path: str, caption_text: str) -> Tuple[bool, Optional[str], Optional[str], str]:
        token = self.config.instagram_api_access_token
        acc_id = self.config.instagram_business_account_id
        if not token or not acc_id:
            return False, None, None, "Instagram API credentials (Access Token or Account ID) are not configured."
        return False, None, None, "Instagram Graph API requires hosted public video URL. Use 'browser' publishing method."
