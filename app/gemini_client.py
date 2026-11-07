import os
import time
from pathlib import Path
from typing import Optional, Tuple, Dict, Any, List
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .logger import app_logger
from .browser_manager import BrowserManager
from .chatgpt_client import GeneratedScript
from .trend_researcher import is_valid_indian_fashion_dance_topic

class GeminiClient:
    """Automates trending topic research and video generation in Google Gemini using the user's authenticated Google session.
    
    Mandatory Rules:
    - Creates a completely NEW conversation for each day's run.
    - Never reuses yesterday's Gemini conversation.
    - Performs normal web search in Gemini to identify verifiable, current trending topics.
    - Rejects any irrelevant non-lifestyle / sports topics.
    - Submits vertical 9:16, 10-second video creation prompts in the SAME new daily conversation.
    - Waits for actual generation completion with diagnostic captures on failure.
    - Never marks a video generated merely because the prompt was sent.
    """

    def __init__(self, browser_manager: BrowserManager, base_url: str = "https://gemini.google.com/"):
        self.browser_manager = browser_manager
        self.base_url = base_url

    def open_fresh_daily_conversation(self, page: Page) -> Tuple[bool, str]:
        """Navigates to Gemini and explicitly creates a fresh new conversation."""
        app_logger.info("Opening Google Gemini to initiate a NEW daily conversation...")
        try:
            page.goto(self.base_url, wait_until="domcontentloaded", timeout=45000)
        except Exception as e:
            return False, f"Failed to navigate to Gemini ({self.base_url}): {e}"

        time.sleep(4)

        # Check authentication
        if "accounts.google.com" in page.url or "signin" in page.url:
            return False, "Google account not authenticated in Gemini. Please log in through the operator profile."

        # Click "New chat" button to guarantee a brand-new conversation
        new_chat_selectors = [
            'button[aria-label*="New chat"]',
            'a[aria-label*="New chat"]',
            'button[data-test-id="new-chat-button"]',
            'div[aria-label*="New chat"]',
            'a[href="/app"]'
        ]
        new_chat_clicked = False
        for sel in new_chat_selectors:
            btn = page.query_selector(sel)
            if btn and btn.is_visible():
                try:
                    btn.click(timeout=3000)
                    new_chat_clicked = True
                    time.sleep(2)
                    break
                except Exception:
                    try:
                        page.keyboard.press("Escape")
                        btn.click(force=True)
                        new_chat_clicked = True
                        time.sleep(2)
                        break
                    except Exception:
                        pass

        # Wait for input area to confirm ready
        try:
            page.wait_for_selector(
                'rich-textarea, div[contenteditable="true"], textarea[placeholder*="Ask Gemini"], div.ql-editor',
                timeout=20000
            )
        except PlaywrightTimeoutError:
            page_text = page.content().lower()
            if "verify" in page_text or "recaptcha" in page_text:
                return False, "Google security verification detected. Manual interaction required."
            return False, f"Gemini input field not found on page ({page.url})."

        app_logger.info(f"Fresh daily Gemini conversation confirmed: {page.url}")
        return True, "Ready"

    def research_trending_topic(self, page: Page, categories: list, duplicate_prevention_checker=None) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Uses normal web search in the fresh Gemini chat to find current trending Indian songs, dance styles, and fashion outfits."""
        app_logger.info("Asking Gemini to search the web for trending Indian songs, dance reels, and fashion trends...")
        today_date_str = time.strftime("%Y-%m-%d")
        search_prompt = (
            f"Search the web right now for currently trending Indian/Bollywood songs, popular dance Reel trends, and modern Indian casual fashion.\n"
            f"Date reference: {today_date_str}.\n"
            f"Select ONE specific, currently viral or popular Indian song and a matching modern Indian fashion concept suitable for a 10-second vertical Instagram Reel featuring an adult Indian woman (age 21+).\n"
            f"Focus on trendy casual wear or fusion styles (e.g. stylish jeans with crop top, casual chic shorts, modern co-ord sets, sneakers, contemporary fusion).\n\n"
            f"Requirements:\n"
            f"1. Must be strictly about Indian music, Bollywood songs, and Indian casual fashion. Do NOT select sports, politics, or unrelated topics.\n"
            f"2. Use current facts and actual web search results for trending songs and dance styles in India.\n"
            f"3. Do NOT invent popularity statistics, songs, or fake claims.\n"
            f"4. Return your final answer strictly in this JSON format (and nothing else):\n"
            f"```json\n"
            f"{{\n"
            f'  "trend_date": "{today_date_str}",\n'
            f'  "song_name": "Exact Song Title",\n'
            f'  "artist": "Singer / Composer / Movie",\n'
            f'  "trend_evidence": "Specific evidence of why this song/dance is trending on Instagram Reels or charts",\n'
            f'  "source_urls": ["https://verified-source-url.com"],\n'
            f'  "outfit_concept": "Detailed description of modern casual clothing (e.g. high-waist jeans, pastel crop top, sneakers, subtle accessories)",\n'
            f'  "dance_style": "Specific dance movements or hook step synchronized with the beat",\n'
            f'  "visual_theme": "Location aesthetic, natural lighting, and camera movement",\n'
            f'  "video_prompt_requirements": "Clear guidelines for realistic cinematic video generation"\n'
            f"}}\n"
            f"```"
        )

        ok, response_text, err = self._send_gemini_message(page, search_prompt)
        if not ok:
            return False, None, err

        # Parse JSON
        topic_data = self._parse_json(response_text)
        valid, val_msg = self.validate_topic_data(topic_data)
        if not valid:
            app_logger.warning(f"Initial Gemini search response was invalid ({val_msg}). Requesting structured correction...")
            corr_prompt = (
                "Please format your selected trending Indian fashion & song topic strictly as valid JSON with all required keys: "
                "trend_date, song_name, artist, trend_evidence, source_urls, outfit_concept, dance_style, visual_theme, video_prompt_requirements. "
                "The topic must be strictly about an Indian/Bollywood song and fashion, not sports or general news."
            )
            ok2, resp2, _ = self._send_gemini_message(page, corr_prompt)
            if ok2:
                topic_data = self._parse_json(resp2)
                valid, val_msg = self.validate_topic_data(topic_data)

        if not valid or not topic_data:
            return False, None, f"Could not extract valid trending Indian fashion/song JSON from Gemini: {val_msg}"

        # Standardize topic title for workflow tracking
        song_title = topic_data.get("song_name", "Trending Song")
        artist = topic_data.get("artist", "")
        combined_title = f"{song_title} - {artist} (Indian Fashion & Dance)" if artist else f"{song_title} (Indian Fashion & Dance)"
        topic_data["title"] = combined_title
        topic_data["category"] = "Indian Fashion & Dance"
        topic_data["summary"] = f"Song: {song_title} by {artist}. Trend: {topic_data.get('trend_evidence')}. Outfit: {topic_data.get('outfit_concept')}."
        topic_data["sources"] = topic_data.get("source_urls", [])

        # Check duplicate if checker provided
        if duplicate_prevention_checker and duplicate_prevention_checker(combined_title):
            app_logger.warning(f"Topic '{combined_title}' was recently used. Asking Gemini for an alternate...")
            alt_prompt = f"The song '{song_title}' was already covered recently. Pick a DIFFERENT currently trending Indian song and outfit concept, and return strictly the JSON schema."
            ok3, resp3, _ = self._send_gemini_message(page, alt_prompt)
            if ok3:
                alt_data = self._parse_json(resp3)
                alt_valid, _ = self.validate_topic_data(alt_data)
                if alt_valid:
                    topic_data = alt_data
                    alt_song = topic_data.get("song_name", "Trending Song")
                    alt_artist = topic_data.get("artist", "")
                    topic_data["title"] = f"{alt_song} - {alt_artist} (Indian Fashion & Dance)" if alt_artist else f"{alt_song} (Indian Fashion & Dance)"
                    topic_data["category"] = "Indian Fashion & Dance"
                    topic_data["summary"] = f"Song: {alt_song} by {alt_artist}. Trend: {topic_data.get('trend_evidence')}. Outfit: {topic_data.get('outfit_concept')}."
                    topic_data["sources"] = topic_data.get("source_urls", [])

        app_logger.info(f"Gemini selected verified Indian fashion & song trend: '{topic_data.get('title')}' with sources: {topic_data.get('sources')}")
        return True, topic_data, "Success"

    def submit_video_generation(
        self,
        page: Page,
        script: GeneratedScript,
        download_dir: Path,
        target_seconds: int = 10,
        timeout_seconds: int = 480
    ) -> Tuple[bool, Optional[str], Optional[str], str]:
        """Submits video generation prompt in the daily Gemini conversation and captures download.
        
        Guarantees:
        - Inspects conversation for existing completed video before re-prompting.
        - Submits prompt and waits for acceptance without expecting a plain text response.
        - Distinguishes accepted generation, generation in progress, completed video, and errors.
        - Captures diagnostic screenshot and DOM state on failure.
        """
        app_logger.info(f"Submitting video generation prompt in Gemini for topic: '{script.title}'...")
        daily_conv_url = page.url
        download_dir.mkdir(parents=True, exist_ok=True)

        # 1. First, check if this conversation ALREADY contains an existing completed video
        existing_video = self._find_and_download_video(page, download_dir)
        if existing_video:
            app_logger.info(f"Found already completed video in conversation: {existing_video}")
            return True, existing_video, daily_conv_url, "Existing video reused from conversation."

        # 2. Construct clean, policy-safe prompt
        raw_prompt = script.video_generation_prompt or ""
        for cutoff in ["Do not imitate", "Do not fabricate", "AUDIO: if audio", "If the video generator", "Commercial or promotional"]:
            if cutoff in raw_prompt:
                raw_prompt = raw_prompt.split(cutoff)[0].strip()

        if len(raw_prompt) < 20 or len(raw_prompt) > 750:
            clothing = script.clothing_details or "stylish modern pastel crop top and high-waist denim jeans with sneakers"
            choreography = script.choreography or "upbeat synchronized dance hook step and shoulder rolls"
            video_prompt = (
                f"A cinematic 10-second vertical 9:16 Instagram Reel video of a fictional 22-year-old Indian woman "
                f"with natural brown hair and realistic features dancing gracefully in a bright sunlit modern studio. "
                f"Wearing: {clothing[:150]}. "
                f"Choreography: {choreography[:150]}. "
                f"Cinematic lighting, 4k photorealistic quality, fluid natural motion, stable vertical framing."
            )
        else:
            video_prompt = raw_prompt

        # 3. Check if video is already available or generation is currently in progress
        existing_video = self._find_and_download_video(page, download_dir)
        if existing_video:
            return True, existing_video, daily_conv_url, "Video already available and downloaded."

        body_text_init = page.inner_text("body").lower()
        stop_btn_init = page.query_selector('button[aria-label*="Stop"]')
        dots_init = page.query_selector("thinking-dots-animation")
        is_generating_already = (
            "generating your video" in body_text_init
            or "generating video" in body_text_init
            or (dots_init is not None and dots_init.is_visible())
            or (stop_btn_init is not None and stop_btn_init.is_visible())
        )

        if not is_generating_already:
            # Submit the video generation prompt
            ok_sub, err_sub = self._submit_prompt_only(page, video_prompt)
            if not ok_sub:
                self._capture_failure_diagnostics(page, "gemini_prompt_submission")
                return False, None, daily_conv_url, f"Gemini video prompt submission failed: {err_sub}"
            time.sleep(4)

        # 4. Monitor generation progress with configurable timeout
        max_wait_seconds = timeout_seconds
        interval = 5
        elapsed = 0

        while elapsed < max_wait_seconds:
            time.sleep(interval)
            elapsed += interval

            # A. Check for completed video element or download button
            video_path = self._find_and_download_video(page, download_dir)
            if video_path:
                return True, video_path, daily_conv_url, "Video successfully generated and downloaded."

            # B. Check for explicit error or refusal keywords
            body_text = page.inner_text("body").lower()
            unsupported_keywords = [
                "i can't create videos",
                "i cannot generate videos",
                "i'm unable to create videos",
                "i am an ai text model and cannot generate video",
                "video generation is not supported",
                "i can't make videos yet",
                "can't generate that video",
                "cannot generate that video",
                "i can't generate that video",
                "video policy guidelines",
                "try describing another idea",
                "can't create that video",
                "something went wrong. please try again",
                "rate limit",
                "quota exceeded"
            ]
            for kw in unsupported_keywords:
                if kw in body_text:
                    app_logger.warning(f"Gemini reported video generation refusal/limitation: '{kw}'")
                    self._capture_failure_diagnostics(page, "gemini_limitation")
                    return False, None, daily_conv_url, f"Account/Policy limitation: Gemini response: '{kw}'. Workflow paused safely."

            # C. Check if thinking/generating indicator is active
            stop_btn = page.query_selector('button[aria-label*="Stop"]')
            dots = page.query_selector("thinking-dots-animation")
            is_still_generating = (
                "generating your video" in body_text
                or "generating video" in body_text
                or (dots is not None and dots.is_visible())
                or (stop_btn is not None and stop_btn.is_visible())
            )

            if is_still_generating:
                if elapsed % 25 == 0:
                    app_logger.info(f"Gemini video generation actively in progress ({elapsed}s / {max_wait_seconds}s elapsed)...")
                continue

            # D. If Stop button is gone, elapsed > 45s, and no generating indicator, inspect last assistant turn
            if elapsed > 45:
                responses = self._get_response_elements(page)
                if responses:
                    last_text = responses[-1].inner_text().lower()
                    if ("sorry" in last_text or "cannot" in last_text or "can't" in last_text) and "video" not in last_text:
                        self._capture_failure_diagnostics(page, "gemini_refusal")
                        return False, None, daily_conv_url, f"Gemini did not output a video: {last_text[:200]}"

        # Timeout reached
        self._capture_failure_diagnostics(page, "gemini_generation_timeout")
        return False, None, daily_conv_url, f"Timed out waiting for Gemini video generation after {max_wait_seconds}s"

    def _submit_prompt_only(self, page: Page, prompt_text: str) -> Tuple[bool, str]:
        """Enters and submits prompt without expecting a standard text response container."""
        try:
            try:
                page.keyboard.press("Escape")
                time.sleep(0.5)
            except Exception:
                pass

            input_elem = page.wait_for_selector(
                'rich-textarea, div[contenteditable="true"], textarea[placeholder*="Ask Gemini"], div.ql-editor',
                timeout=15000
            )
            if not input_elem:
                return False, "Gemini input field not found"

            try:
                input_elem.click(timeout=3000)
            except Exception:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                input_elem.click(force=True)

            time.sleep(0.5)
            page.keyboard.insert_text(prompt_text)
            time.sleep(1)

            send_btn = page.query_selector('button[aria-label*="Send"], button.send-button, [data-test-id="send-button"]')
            if send_btn and send_btn.is_enabled():
                try:
                    send_btn.click(timeout=3000)
                except Exception:
                    send_btn.click(force=True)
            else:
                page.keyboard.press("Enter")

            app_logger.info("Submitted video prompt to Gemini successfully.")
            return True, "Submitted"
        except Exception as e:
            return False, str(e)

    def _find_and_download_video(self, page: Page, download_dir: Path) -> Optional[str]:
        """Checks for <video> elements or video download controls and saves the file."""
        # 1. Direct download from <video> tag using in-browser fetch or context request
        video_elem = page.query_selector('video')
        if video_elem:
            v_src = video_elem.get_attribute("src")
            if v_src and len(v_src) > 5:
                app_logger.info(f"Detected video element in Gemini: {v_src[:70]}...")
                dest = download_dir / f"{time.strftime('%Y-%m-%d_%H%M%S')}_gemini_reel.mp4"

                # 1a. In-browser fetch (shares browser session cookies and cache)
                try:
                    js_code = """async (url) => {
                        const res = await fetch(url, { credentials: 'include' });
                        if (!res.ok) throw new Error('Fetch status ' + res.status);
                        const blob = await res.blob();
                        return new Promise((resolve, reject) => {
                            const reader = new FileReader();
                            reader.onloadend = () => resolve(reader.result.split(',')[1]);
                            reader.onerror = reject;
                            reader.readAsDataURL(blob);
                        });
                    }"""
                    b64_data = page.evaluate(js_code, v_src)
                    if b64_data and len(b64_data) > 10000:
                        import base64
                        bytes_data = base64.b64decode(b64_data)
                        if len(bytes_data) > 50000:
                            dest.write_bytes(bytes_data)
                            app_logger.info(f"Successfully downloaded video via in-browser fetch: {dest} ({len(bytes_data)} bytes)")
                            return str(dest)
                except Exception as e:
                    app_logger.debug(f"In-browser fetch notice: {e}")

                # 1b. Context request fallback
                if not v_src.startswith("blob:"):
                    try:
                        resp = page.context.request.get(v_src, timeout=30000)
                        if resp.status == 200:
                            body = resp.body()
                            if len(body) > 50000:
                                dest.write_bytes(body)
                                app_logger.info(f"Successfully downloaded video via context request: {dest} ({len(body)} bytes)")
                                return str(dest)
                    except Exception as e:
                        app_logger.debug(f"Direct context request notice: {e}")

        # 2. Check for explicit video download controls
        download_btn = page.query_selector(
            'button[aria-label*="Download video"], button[aria-label*="download video"], [data-test-id="video-download"], a[aria-label*="Download video"]'
        )
        if not download_btn or not download_btn.is_visible():
            candidates = page.query_selector_all('button[aria-label*="Download"], a[aria-label*="Download"]')
            for c in candidates:
                lbl = (c.get_attribute("aria-label") or "").lower()
                if "code" not in lbl and "video" in lbl:
                    download_btn = c
                    break

        if download_btn and download_btn.is_visible():
            app_logger.info("Found video download control in Gemini response. Triggering download...")
            try:
                with page.expect_download(timeout=45000) as download_info:
                    download_btn.click(force=True)
                download = download_info.value
                suggested = download.suggested_filename
                if not suggested.lower().endswith(('.json', '.txt', '.html', '.js')):
                    dest = download_dir / f"{time.strftime('%Y-%m-%d_%H%M%S')}_gemini_reel.mp4"
                    download.save_as(str(dest))
                    if dest.exists() and dest.stat().st_size > 50000:
                        app_logger.info(f"Successfully downloaded video file: {dest} ({dest.stat().st_size} bytes)")
                        return str(dest)
            except Exception as e:
                app_logger.debug(f"Download control trigger notice: {e}")

        return None

    def _get_response_elements(self, page: Page) -> List[Any]:
        """Returns all matching response elements in the Gemini UI using resilient selectors."""
        selectors = [
            'model-response',
            'message-content',
            '.response-container',
            '.model-response-text',
            'div[data-message-id]',
            'div.response-content',
            'p-chat-turn',
            'div[role="region"]',
            'article'
        ]
        elements = []
        for sel in selectors:
            try:
                found = page.query_selector_all(sel)
                if found:
                    elements.extend(found)
            except Exception:
                pass
        return elements

    def _send_gemini_message(self, page: Page, message_text: str) -> Tuple[bool, str, str]:
        """Inputs text and waits for Gemini response with resilient selector detection."""
        try:
            try:
                page.keyboard.press("Escape")
                time.sleep(0.5)
            except Exception:
                pass

            input_elem = page.wait_for_selector(
                'rich-textarea, div[contenteditable="true"], textarea[placeholder*="Ask Gemini"], div.ql-editor',
                timeout=15000
            )
            if not input_elem:
                return False, "", "Gemini input field not found"

            try:
                input_elem.click(timeout=3000)
            except Exception:
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                input_elem.click(force=True)

            time.sleep(0.5)
            page.keyboard.insert_text(message_text)
            time.sleep(1)

            send_btn = page.query_selector('button[aria-label*="Send"], button.send-button, [data-test-id="send-button"]')
            if send_btn and send_btn.is_enabled():
                try:
                    send_btn.click(timeout=3000)
                except Exception:
                    send_btn.click(force=True)
            else:
                page.keyboard.press("Enter")

            # Wait for generation to start and complete
            time.sleep(5)
            max_wait = 90
            waited = 0
            while waited < max_wait:
                stop_btn = page.query_selector('button[aria-label*="Stop"]')
                if not stop_btn:
                    break
                time.sleep(3)
                waited += 3

            time.sleep(3)
            # Extract assistant response using resilient selectors
            responses = self._get_response_elements(page)
            if responses:
                # Get the last non-empty response
                for r in reversed(responses):
                    txt = r.inner_text().strip()
                    if len(txt) > 20:
                        return True, txt, "Success"

            # Fallback: Extract via JavaScript evaluate of main body
            body_text = page.evaluate("""() => {
                const nodes = document.querySelectorAll('model-response, message-content, [data-message-id], .markdown');
                for (let i = nodes.length - 1; i >= 0; i--) {
                    const text = nodes[i].innerText.trim();
                    if (text.length > 20) return text;
                }
                return document.body.innerText;
            }""")
            if body_text and len(body_text.strip()) > 30:
                return True, body_text.strip(), "Success (Fallback extract)"

            self._capture_failure_diagnostics(page, "gemini_no_response")
            return False, "", "No response message found in Gemini interface"
        except Exception as e:
            self._capture_failure_diagnostics(page, "gemini_send_exception")
            return False, "", str(e)

    def _capture_failure_diagnostics(self, page: Page, prefix: str):
        """Captures diagnostic screenshot and logs on failure."""
        try:
            logs_dir = Path(__file__).resolve().parent.parent / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S")
            shot_path = logs_dir / f"{prefix}_{ts}.png"
            page.screenshot(path=str(shot_path))
            app_logger.info(f"Saved Gemini diagnostic screenshot to: {shot_path}")
        except Exception as e:
            app_logger.debug(f"Notice saving diagnostic screenshot: {e}")

    @staticmethod
    def _parse_json(text: str) -> Optional[Dict[str, Any]]:
        import json
        if not text:
            return None
        try:
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]
            elif "{" in text and "}" in text:
                s = text.find("{")
                e = text.rfind("}") + 1
                text = text[s:e]

            cleaned = text.strip()
            if cleaned.startswith("JSON"):
                cleaned = cleaned[4:].strip()

            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
            return None
        except Exception as e:
            app_logger.warning(f"Error parsing Gemini JSON response: {e}")
            return None

    @staticmethod
    def validate_topic_data(data: Any) -> Tuple[bool, str]:
        """Validates that extracted topic contains all required fields, credible sources, and strictly adheres to Indian fashion/dance strategy."""
        if not isinstance(data, dict):
            return False, "Response is not a JSON object."

        # Check for disallowed non-lifestyle topics (sports, politics, etc.)
        topic_title = str(data.get("song_name") or data.get("title") or "")
        summary = str(data.get("trend_evidence") or data.get("summary") or "")
        category = str(data.get("category") or "Indian Fashion & Dance")
        sources_list = data.get("source_urls") or data.get("sources") or []

        # Check for literal example placeholder tokens returned by model
        placeholders = [
            "exact song title",
            "singer / composer / movie",
            "verified-source-url.com",
            "example.com",
            "specific evidence of why",
            "clear guidelines for realistic",
        ]
        for p in placeholders:
            if (
                p in topic_title.lower()
                or p in summary.lower()
                or any(p in str(s).lower() for s in sources_list)
            ):
                return False, f"Model returned template placeholder token: '{p}'"

        valid_topic, topic_err = is_valid_indian_fashion_dance_topic(topic_title, summary, category)
        if not valid_topic:
            return False, f"Strategy rejection: {topic_err}"

        # Support rich Indian fashion & dance schema
        has_fashion_schema = any(k in data for k in ["song_name", "outfit_concept", "dance_style", "artist", "trend_evidence"])
        if has_fashion_schema:
            req_keys = ["song_name", "outfit_concept", "dance_style"]
            for k in req_keys:
                if not data.get(k):
                    return False, f"Missing required fashion/song field: '{k}'."

            sources = data.get("source_urls") or data.get("sources")
            if not isinstance(sources, list) or len(sources) == 0:
                return False, "Must contain at least one valid source URL in 'source_urls' list."

            valid_urls = [s for s in sources if isinstance(s, str) and (s.startswith("http://") or s.startswith("https://"))]
            if not valid_urls:
                return False, f"None of the provided sources are valid web URLs: {sources}."

            return True, "Valid"

        # Standard topic schema fallback
        required = ["title", "category", "summary", "sources"]
        for req in required:
            if req not in data or not data[req]:
                return False, f"Missing required topic field: '{req}'."

        title = str(data.get("title", "")).strip()
        summary_str = str(data.get("summary", "")).strip()
        sources = data.get("sources")

        if len(title) < 5:
            return False, f"Topic title is too brief: '{title}'."
        if len(summary_str) < 20:
            return False, f"Topic summary is too brief: '{summary_str}'."
        if not isinstance(sources, list) or len(sources) == 0:
            return False, "Topic must contain at least one valid source URL in 'sources' list."

        valid_urls = [s for s in sources if isinstance(s, str) and (s.startswith("http://") or s.startswith("https://"))]
        if not valid_urls:
            return False, f"None of the provided sources are valid web URLs: {sources}."

        return True, "Valid"
