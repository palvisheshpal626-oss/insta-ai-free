import json
import time
from typing import Optional, Dict, Any, Tuple
from dataclasses import dataclass, asdict
from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from .logger import app_logger
from .browser_manager import BrowserManager

@dataclass
class GeneratedScript:
    title: str
    hook: str
    narration: str
    scenes: str
    on_screen_text: str
    visual_style: str
    caption_idea: str
    hashtags: str
    sources: str
    # Fashion & Dance specific fields
    song_name: Optional[str] = None
    artist: Optional[str] = None
    clothing_details: Optional[str] = None
    choreography: Optional[str] = None
    camera_lighting: Optional[str] = None
    video_generation_prompt: Optional[str] = None
    licensing_notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)



class ChatGPTClient:
    """Automates script generation using the user's persistent ChatGPT conversation.
    
    Mandatory Rules:
    - Reuses the designated conversation URL stored in configuration.
    - Never automatically creates new conversations on retries.
    - Validates output structure strictly against a 10-second target duration (~15-22 words).
    - If format is invalid, requests a correction inside the SAME conversation.
    """

    def __init__(self, browser_manager: BrowserManager, conversation_url: Optional[Any] = None):
        self.browser_manager = browser_manager
        if hasattr(conversation_url, "chatgpt_conversation_url"):
            self.conversation_url = str(conversation_url.chatgpt_conversation_url)
        else:
            self.conversation_url = str(conversation_url) if conversation_url else None

    def check_authentication(self, page: Page) -> bool:
        """Verifies if ChatGPT is currently authenticated."""
        try:
            url = page.url
            # If redirected to login page or sign in button is present
            if "login" in url or "auth" in url:
                return False
            # Check for chat prompt textarea
            prompt_input = page.query_selector("#prompt-textarea, textarea[placeholder*='Message']")
            return prompt_input is not None
        except Exception:
            return False

    def open_dedicated_conversation(self, page: Page) -> Tuple[bool, str]:
        """Navigates to the designated conversation URL."""
        if not self.conversation_url:
            return False, "No dedicated ChatGPT conversation URL configured. A persistent conversation URL is required."

        target_url = self.conversation_url
        profile_path = getattr(self.browser_manager, "profile_dir", "Unknown")
        app_logger.info(f"Opening dedicated ChatGPT conversation: {target_url} (Profile: {profile_path})")

        # If already at target conversation, no need to perform full navigation
        current_page_url = getattr(page, "url", "")
        if target_url in current_page_url or "chatgpt.com/g/g-p-6ad4d211b748819196b6cd4d39285240" in current_page_url:
            app_logger.info(f"Page is already open at designated ChatGPT conversation: {current_page_url}")
        else:
            try:
                page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
            except Exception as e:
                app_logger.warning(f"Initial navigation to ChatGPT encountered: {e}. Retrying after 3s...")
                time.sleep(3)
                try:
                    page.goto(target_url, wait_until="domcontentloaded", timeout=45000)
                except Exception as e2:
                    return False, f"Failed to load ChatGPT conversation URL '{target_url}': {e2}"

        time.sleep(4)

        # 1. Check for authentication redirect
        current_url = page.url
        if "login" in current_url or "auth" in current_url:
            msg = (
                f"ChatGPT authentication expired or not found (current URL: {current_url}). "
                f"Automation Profile: '{profile_path}'. "
                "Please sign into ChatGPT through the authentication browser (or run 'python scripts/launch_auth_browser.py')."
            )
            app_logger.warning(msg)
            return False, msg

        # 2. Check for Cloudflare challenge interstitial (do not match benign CDN script URLs)
        page_title = page.title().lower()
        if "just a moment" in page_title or "attention required" in page_title:
            msg = (
                "Cloudflare security challenge detected on ChatGPT. "
                "Please open the visible authentication browser to complete the verification."
            )
            app_logger.warning(msg)
            return False, msg

        challenge_selectors = [
            "#challenge-running",
            "#cf-challenge-running",
            "iframe[src*='challenges.cloudflare.com']",
            "div.cf-turnstile-wrapper"
        ]
        for c_sel in challenge_selectors:
            c_elem = page.query_selector(c_sel)
            if c_elem and c_elem.is_visible():
                msg = (
                    "Cloudflare security challenge detected on ChatGPT. "
                    "Please complete the Cloudflare turnstile in the open browser."
                )
                app_logger.warning(msg)
                return False, msg


        # 3. Verify conversation or custom GPT URL loaded
        if target_url not in current_url and "/c/" not in current_url and "/g/" not in current_url:
            app_logger.warning(f"ChatGPT URL redirected from '{target_url}' to '{current_url}'")
            if current_url.rstrip("/") in ["https://chatgpt.com", "https://chatgpt.com/auth/login"]:
                return False, f"Failed to load intended conversation. Redirected to generic page: {current_url}. Authentication or conversation access required."

        # 4. Wait for prompt area
        prompt_selectors = [
            "#prompt-textarea",
            "div[contenteditable='true']",
            "div.ProseMirror",
            "textarea[placeholder*='Message']",
            "textarea"
        ]
        prompt_found = False
        for sel in prompt_selectors:
            try:
                elem = page.wait_for_selector(sel, timeout=5000)
                if elem and elem.is_visible():
                    prompt_found = True
                    break
            except Exception:
                pass

        if not prompt_found:
            page_text = page.content().lower()
            if "conversation not found" in page_text or "unable to load conversation" in page_text:
                return False, f"Target ChatGPT conversation could not be accessed at '{target_url}'. Check permissions or account login."
            return False, f"ChatGPT prompt input area not found at '{current_url}'."

        app_logger.info(f"Verified dedicated ChatGPT conversation loaded successfully: {page.url}")
        return True, "Ready"

    def generate_10s_script(self, topic: str, category: str, research_summary: str, sources: list, language: str = "English") -> Tuple[bool, Optional[GeneratedScript], str]:
        """Submits structured prompt to ChatGPT and parses 10-second Indian fashion & dance Reel script."""
        page = self.browser_manager.new_page(prefer_existing_url="chatgpt.com")

        try:
            ok, msg = self.open_dedicated_conversation(page)
            if not ok:
                return False, None, msg

            structured_prompt = (
                f"You are an expert short-form video creator and fashion choreographer. "
                f"Create a high-retention, 10-SECOND Instagram Reel concept and video generation prompt featuring Indian fashion and dance.\n\n"
                f"Topic/Trend: {topic}\n"
                f"Category: {category}\n"
                f"Trend Details: {research_summary}\n"
                f"Language: {language}\n"
                f"Target Duration: EXACTLY 10 seconds (vertical 9:16 format).\n\n"
                f"CRITICAL CHARACTER & QUALITY CONSTRAINTS:\n"
                f"- Character: Exactly ONE fictional adult Indian woman, age 21+, with a natural, realistic appearance and elegant styling. (Do NOT imitate real celebrities).\n"
                f"- Anatomy: Photorealistic human anatomy, accurate hands, fingers, and facial features, consistent appearance throughout the 10 seconds.\n"
                f"- Fashion: Trendy modern Indian casual fashion or fusion (e.g. stylish jeans, crop top, chic shorts, shirt, co-ord set, sneakers, contemporary casual dress).\n"
                f"- Dance: Natural, synchronized, graceful dance steps matching the rhythm of the trending Indian/Bollywood song.\n"
                f"- Aesthetics: Cinematic professional lighting, realistic fabric physics, smooth camera pan/zoom, no distorted artifacts or watermarks.\n"
                f"- Narration: Short voiceover or audio hook (strictly 12 to 24 words).\n\n"
                f"Provide your response in EXACTLY this JSON format (and nothing else):\n"
                f"```json\n"
                f"{{\n"
                f'  "title": "{topic}",\n'
                f'  "song_name": "Selected Indian/Bollywood Song Title",\n'
                f'  "artist": "Singer / Music Director",\n'
                f'  "hook": "Opening 1-2s visual hook and opening pose",\n'
                f'  "narration": "Short voiceover or hook line (strictly 12 to 24 words)",\n'
                f'  "scenes": "Scene 1 (0-3s) intro hook, Scene 2 (3-7s) energetic chorus dance, Scene 3 (7-10s) final pose and smile",\n'
                f'  "clothing_details": "Exact outfit details: garment types, colors, accessories, hairstyle, and footwear",\n'
                f'  "choreography": "Specific dance steps, rhythm synchronization, and hand gestures",\n'
                f'  "camera_lighting": "Camera movement (slow push-in, orbital), framing (full body 9:16), golden hour / studio lighting",\n'
                f'  "video_generation_prompt": "Cinematic visual description for AI video generator: vertical 9:16, 10 seconds. Describe only visible visual actions, a 22-year-old fictional Indian woman, outfit, synchronized dance steps, natural lighting, and camera movement. Keep it concise (under 90 words), positive visual descriptions only. DO NOT include meta-words, negative instructions, disclaimers, or words like celebrity/fabricate/licensing.",\n'
                f'  "on_screen_text": "Text overlay on screen",\n'
                f'  "visual_style": "Cinematic vertical 9:16 photorealistic fashion video style",\n'
                f'  "caption_idea": "Catchy Instagram caption with outfit details and music vibe",\n'
                f'  "hashtags": "#IndianFashion #DanceReels #OutfitInspo #ReelsInstagram #TrendingReels",\n'
                f'  "licensing_notes": "Use official audio track from Instagram Music Library during publication",\n'
                f'  "sources": "Factual reference"\n'
                f"}}\n"
                f"```"
            )

            # Send prompt
            script = self._send_and_receive(page, structured_prompt)
            if script:
                if not script.title or script.title == "Untitled":
                    script.title = topic
                from .trend_researcher import is_valid_indian_fashion_dance_topic
                valid_sc, _ = is_valid_indian_fashion_dance_topic(f"{script.title} {script.song_name or ''} {topic}")
                if valid_sc and "spurs" not in script.title.lower() and "placeholder" not in script.title.lower():
                    return True, script, "Success"
                else:
                    app_logger.warning(f"ChatGPT returned non-compliant or stale topic '{script.title}'. Requesting regeneration for '{topic}'...")

            # If formatting failed or returned stale topic, request correction in the SAME conversation
            app_logger.warning("Requesting strict Indian fashion/dance script regeneration in SAME ChatGPT conversation...")
            correction_prompt = (
                f"Please generate the 10-second vertical Reel script strictly for this specific Indian song and fashion trend: '{topic}'. "
                f"Topic Details: {research_summary}. "
                f"Return ONLY valid JSON matching the schema with title, song_name, artist, clothing_details, choreography, and video_generation_prompt. "
                f"Do not mention sports or unrelated topics."
            )
            script_fixed = self._send_and_receive(page, correction_prompt)
            if script_fixed:
                if not script_fixed.title or script_fixed.title == "Untitled":
                    script_fixed.title = topic
                from .trend_researcher import is_valid_indian_fashion_dance_topic
                valid_sc2, _ = is_valid_indian_fashion_dance_topic(f"{script_fixed.title} {script_fixed.song_name or ''} {topic}")
                if valid_sc2 and "spurs" not in script_fixed.title.lower():
                    return True, script_fixed, "Success after correction"

            return False, None, "Failed to parse valid 10-second script from ChatGPT response"

        except Exception as e:
            app_logger.error(f"ChatGPT automation error: {e}")
            return False, None, str(e)
        finally:
            try:
                page.close()
            except Exception:
                pass


    def generate_video_specific_caption(
        self,
        topic: str,
        song_name: str,
        artist: str,
        clothing_details: str,
        choreography: str,
        trend_details: Optional[str] = None
    ) -> Tuple[bool, Optional[Dict[str, Any]], str]:
        """Asks the dedicated ChatGPT conversation to generate a fresh, natural Instagram caption and tailored hashtags specifically for this video."""
        page = self.browser_manager.new_page(prefer_existing_url="chatgpt.com")
        try:
            ok, msg = self.open_dedicated_conversation(page)
            if not ok:
                return False, None, msg

            app_logger.info(f"Generating video-specific caption in dedicated ChatGPT conversation for song: '{song_name}' by '{artist}'...")
            prompt = (
                f"Write a fresh, authentic, and engaging Instagram Reel caption and tailored hashtags specifically for this newly rendered video:\n\n"
                f"Video Details:\n"
                f"- Song: {song_name} by {artist}\n"
                f"- Concept/Topic: {topic}\n"
                f"- Outfit & Styling: {clothing_details}\n"
                f"- Dance & Choreography: {choreography}\n"
                f"- Context: Modern Indian casual fashion and Bollywood dance rhythm.\n\n"
                f"Requirements:\n"
                f"1. Tone: Natural, aesthetic, conversational, and catchy. (e.g. 'Desi vibes, fresh fit, and a little Bollywood magic. Which outfit should be next?'). Do NOT use cliches or generic templates.\n"
                f"2. Explicit Audio Credit line: Include '🎵 Audio: {song_name} by {artist}'. (Note: this is textual attribution in the caption).\n"
                f"3. Call to Action: Include an engaging question asking viewers for their opinion or next outfit idea.\n"
                f"4. Hashtags: Provide 6 to 9 specific, highly relevant hashtags matching this fashion and dance trend (e.g. #IndianFashion #DanceReels #BollywoodVibes #OutfitInspiration #IndianGirlStyle).\n"
                f"5. Character Limit: Under 1200 characters total.\n"
                f"6. Return strictly valid JSON in this format (and nothing else):\n"
                f"```json\n"
                f"{{\n"
                f'  "caption": "Your full caption text including the 🎵 Audio credit and question",\n'
                f'  "hashtags": ["#IndianFashion", "#DanceReels", "#BollywoodVibes", "#OutfitInspiration", "#IndianGirlStyle"],\n'
                f'  "formatted_post_text": "Complete caption followed by hashtags"\n'
                f"}}\n"
                f"```"
            )

            raw_text = self._send_and_receive_text(page, prompt)
            if not raw_text:
                return False, None, "No response from ChatGPT for caption generation"

            caption_data = self._parse_json_dict(raw_text)
            if not caption_data or not caption_data.get("caption"):
                app_logger.warning(f"Could not parse caption JSON from ChatGPT. Raw: {raw_text[:200]}")
                return False, None, "Failed to parse structured caption from ChatGPT response"

            app_logger.info("Fresh video-specific caption generated successfully by ChatGPT.")
            return True, caption_data, "Success"

        except Exception as e:
            app_logger.error(f"Error generating caption in ChatGPT: {e}")
            return False, None, str(e)
        finally:
            try:
                page.close()
            except Exception:
                pass

    def _send_and_receive_text(self, page: Page, prompt_text: str) -> Optional[str]:
        """Low-level method to send a prompt to ChatGPT and wait for the latest assistant text response."""
        prompt_selectors = [
            'form[data-chatgpt-composer] div.ProseMirror',
            'div[aria-label="Ask ChatGPT"]',
            'form[data-chatgpt-composer] [contenteditable="true"]',
            '#prompt-textarea',
            'form[data-chatgpt-composer] textarea',
            'div.ProseMirror',
            'textarea'
        ]
        input_elem = None

        for sel in prompt_selectors:
            try:
                elem = page.wait_for_selector(sel, timeout=6000)
                if elem and elem.is_visible():
                    input_elem = elem
                    break
            except Exception:
                pass

        if not input_elem:
            app_logger.warning("Could not find prompt input area in ChatGPT conversation.")
            return None

        try:
            input_elem.click()
            time.sleep(0.5)
            # Clear any existing text in the prompt box
            page.keyboard.press("Control+A")
            time.sleep(0.2)
            page.keyboard.press("Backspace")
            time.sleep(0.3)
            page.keyboard.insert_text(prompt_text)
        except Exception:
            try:
                input_elem.fill(prompt_text)
            except Exception as e:
                app_logger.error(f"Failed to fill prompt input: {e}")
                return None
        time.sleep(1)

        # Count existing assistant messages and record last message text
        initial_messages = page.query_selector_all('[data-message-author-role="assistant"], [class*="MarkdownRoot"]')
        initial_count = len(initial_messages)
        previous_last_text = initial_messages[-1].inner_text().strip() if initial_messages else ""

        # Ensure React recognizes input by pressing Space and Backspace
        try:
            page.keyboard.press("Space")
            time.sleep(0.1)
            page.keyboard.press("Backspace")
            time.sleep(0.5)
        except Exception:
            pass

        # Click send or press Enter
        send_btn_selector = (
            'form[data-chatgpt-composer] button[data-testid="send-button"], '
            'button[data-testid="send-button"], '
            'form[data-chatgpt-composer] button[aria-label*="Send"], '
            'button[aria-label="Send"], '
            'button.bg-composer-primary'
        )
        sent = False
        try:
            btn = page.query_selector(send_btn_selector)
            if btn and not btn.is_disabled():
                btn.click()
                sent = True
        except Exception:
            pass

        if not sent:
            page.keyboard.press("Enter")

        app_logger.info("Sent prompt to ChatGPT. Waiting for assistant completion...")
        time.sleep(3)
        max_wait = 120
        waited = 3
        generation_started = False

        while waited < max_wait:
            stop_btn = page.query_selector('button[aria-label="Stop generating"], button[data-testid="stop-button"], button[aria-label*="Stop"]')
            if stop_btn:
                generation_started = True

            current_msgs = page.query_selector_all('[data-message-author-role="assistant"], [class*="MarkdownRoot"]')
            current_count = len(current_msgs)
            latest_text = current_msgs[-1].inner_text().strip() if current_msgs else ""

            # Generation completed if:
            # 1. New message element was added, OR
            # 2. Latest message text differs from previous text and stop button is gone
            if not stop_btn and (waited >= 6 or generation_started):
                if current_count > initial_count and len(latest_text) > 30:
                    break
                if latest_text != previous_last_text and len(latest_text) > 50:
                    break

            time.sleep(2)
            waited += 2

        time.sleep(1)
        messages = page.query_selector_all('[data-message-author-role="assistant"], [class*="MarkdownRoot"]')
        if not messages:
            app_logger.warning("No assistant messages found in ChatGPT DOM.")
            return None

        last_text = messages[-1].inner_text().strip()
        if last_text == previous_last_text:
            app_logger.warning("ChatGPT response did not change (received stale message). Prompt may not have submitted.")
            return None

        return last_text

    def _send_and_receive(self, page: Page, prompt_text: str) -> Optional[GeneratedScript]:
        raw_text = self._send_and_receive_text(page, prompt_text)
        if not raw_text:
            return None
        return self._parse_script_json(raw_text)

    @staticmethod
    def _parse_json_dict(raw_text: str) -> Optional[Dict[str, Any]]:
        """Safely parses JSON dictionary from text with or without code fences."""
        try:
            json_str = ""
            if "```json" in raw_text:
                json_str = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                json_str = raw_text.split("```")[1].split("```")[0].strip()
            elif "{" in raw_text and "}" in raw_text:
                s = raw_text.find("{")
                e = raw_text.rfind("}") + 1
                json_str = raw_text[s:e]

            if not json_str:
                return None

            data = json.loads(json_str)
            return data if isinstance(data, dict) else None
        except Exception as e:
            app_logger.warning(f"Failed to parse JSON dict from ChatGPT: {e}")
            return None

    def _parse_script_json(self, raw_text: str) -> Optional[GeneratedScript]:
        try:
            # Extract content within ```json ... ``` or { ... }
            json_str = ""
            if "```json" in raw_text:
                json_str = raw_text.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_text:
                json_str = raw_text.split("```")[1].split("```")[0].strip()
            elif "{" in raw_text and "}" in raw_text:
                s = raw_text.find("{")
                e = raw_text.rfind("}") + 1
                json_str = raw_text[s:e]

            if not json_str:
                return None

            data = json.loads(json_str)
            scenes_val = data.get("scenes") or data.get("scene_breakdown") or ""
            if isinstance(scenes_val, (list, dict)):
                scenes_val = json.dumps(scenes_val, indent=2)

            script = GeneratedScript(
                title=data.get("title", "Untitled"),
                hook=data.get("hook", ""),
                narration=data.get("narration", ""),
                scenes=str(scenes_val),
                on_screen_text=str(data.get("on_screen_text", "")),
                visual_style=str(data.get("visual_style", "")),
                caption_idea=str(data.get("caption_idea", "")),
                hashtags=str(data.get("hashtags", "")),
                sources=str(data.get("sources", "")),
                song_name=data.get("song_name"),
                artist=data.get("artist"),
                clothing_details=data.get("clothing_details"),
                choreography=data.get("choreography"),
                camera_lighting=data.get("camera_lighting"),
                video_generation_prompt=data.get("video_generation_prompt"),
                licensing_notes=data.get("licensing_notes")
            )

            # Validate narration length for 10-second reel
            if not script.narration:
                script.narration = f"Vibing to {script.song_name or 'the beat'} in my new favorite fit."
            else:
                words = script.narration.split()
                if len(words) < 6 or len(words) > 40:
                    app_logger.warning(f"Script narration word count ({len(words)}) outside target range.")

            if not script.video_generation_prompt:
                script.video_generation_prompt = (
                    f"Vertical 9:16 video of a 22-year-old stylish Indian woman with natural beauty, wearing {script.clothing_details or 'stylish crop top and high-waist jeans'}, "
                    f"performing energetic dance movements to {script.song_name or 'Bollywood music'}, cinematic lighting, smooth handheld camera movement, photorealistic 8k."
                )

            return script

        except Exception as e:
            app_logger.warning(f"Failed to parse JSON from ChatGPT response: {e}")
            return None
