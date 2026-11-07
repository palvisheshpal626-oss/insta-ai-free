import os
import sys
import time
import json
import shutil
import uuid
import re
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List

from .logger import app_logger
from .config_manager import AppConfig, ConfigurationManager, BASE_DIR
from .state_manager import StateManager, WorkflowStage
from .browser_manager import BrowserManager, ChromeProfileLockedError, BrowserConnectionError
from .trend_researcher import TrendResearcher, is_valid_indian_fashion_dance_topic
from .chatgpt_client import ChatGPTClient, GeneratedScript
from .gemini_client import GeminiClient
from .video_manager import VideoManager
from .caption_generator import CaptionGenerator
from .instagram_publisher import InstagramPublisher

class InterProcessWorkflowLock:
    """Inter-process file lock ensuring only one workflow runs across processes and threads."""
    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._file = None

    def acquire(self) -> bool:
        try:
            self.lock_path.parent.mkdir(parents=True, exist_ok=True)
            self._file = open(self.lock_path, "w")
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            self._file.write(f"{os.getpid()}|{time.time()}")
            self._file.flush()
            return True
        except Exception:
            if self._file:
                try:
                    self._file.close()
                except Exception:
                    pass
                self._file = None
            return False

    def release(self):
        if self._file:
            try:
                if os.name == "nt":
                    import msvcrt
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                self._file.close()
            except Exception:
                pass
            self._file = None


class WorkflowOrchestrator:
    """Master workflow orchestrator executing the 13-step daily reel creation and publishing pipeline.
    
    Guarantees:
    - Never duplicates today's reel if already published.
    - Prevents simultaneous overlapping workflows using process & thread locks.
    - Reuses the designated ChatGPT conversation.
    - Creates a fresh Gemini conversation for each daily run.
    - Rejects invalid topics (e.g. sports/politics) and enforces Indian fashion & Bollywood dance.
    - Validates downloaded video and trims to 10s if needed.
    - Recovers from the earliest incomplete stage with valid prerequisites.
    - Bounded retries with backoff and clear blocker actions on NEEDS_USER_ACTION.
    """

    def __init__(self, config_manager: Optional[ConfigurationManager] = None):
        self.config_manager = config_manager or ConfigurationManager()
        self.config = self.config_manager.config
        self.state_manager = StateManager()
        self.video_manager = VideoManager(self.config.ffmpeg_path, self.config.ffprobe_path)
        self.browser_manager = BrowserManager(self.config)
        self.trend_researcher = TrendResearcher(self.state_manager, self.config.duplicate_prevention_days)
        self.caption_generator = CaptionGenerator()
        self.instagram_publisher = InstagramPublisher(self.config, self.browser_manager)

        self.chatgpt_client = ChatGPTClient(self.browser_manager, self.config.chatgpt_conversation_url)
        self.gemini_client = GeminiClient(self.browser_manager, self.config.gemini_url)

        self._is_running = False
        self._is_paused = False
        self._thread_lock = threading.Lock()

    def is_running(self) -> bool:
        return self._is_running

    def is_paused(self) -> bool:
        return self._is_paused

    def pause(self):
        self._is_paused = True
        app_logger.info("Workflow execution paused by user.")

    def resume(self):
        self._is_paused = False
        app_logger.info("Workflow execution resumed by user.")

    def stop(self):
        self._is_running = False
        self._is_paused = False
        app_logger.info("Workflow execution stopped by user.")

    def run_daily_workflow(self, force: bool = False) -> Dict[str, Any]:
        """Main daily workflow execution loop with single-flight locking, topic validation, and stage resumption."""
        with self._thread_lock:
            if self._is_running:
                app_logger.warning("A workflow is already currently executing in this process. Preventing duplicate run.")
                return {"status": "RUNNING", "message": "Workflow already in progress", "success": False}

            ip_lock = InterProcessWorkflowLock(BASE_DIR / "data" / "workflow.lock")
            if not ip_lock.acquire():
                app_logger.warning("Another process holds the workflow execution lock. Preventing duplicate run.")
                return {"status": "RUNNING", "message": "Workflow lock is held by another process", "success": False}

            self._is_running = True

        today_str = datetime.now().strftime("%Y-%m-%d")

        try:
            # 1. Duplicate check: has today's Reel already been published?
            if not force:
                existing_pub = self.state_manager.get_todays_successful_workflow(today_str)
                if existing_pub:
                    app_logger.info(f"Reel workflow for today ({today_str}) already completed successfully (Workflow ID: {existing_pub['workflow_id']}). Skipping.")
                    return {
                        "status": "ALREADY_PUBLISHED",
                        "message": f"Today's Reel already published ({today_str})",
                        "success": True,
                        "workflow": existing_pub
                    }

            # 2. Check for recoverable existing run from today
            active = self.state_manager.get_todays_active_workflow(today_str)
            if active:
                workflow_id = active["workflow_id"]
                current_stage = WorkflowStage(active["stage"])
                app_logger.info(f"Resuming active workflow {workflow_id} from stage: {current_stage.value}")

                # Verify topic compliance if topic was already set
                if active.get("topic"):
                    valid_topic, topic_err = is_valid_indian_fashion_dance_topic(active["topic"])
                    if not valid_topic:
                        app_logger.warning(
                            f"Existing topic '{active['topic']}' rejected: {topic_err}. "
                            "Invalidating and resetting workflow stage to PENDING to select a compliant topic."
                        )
                        self.state_manager.update_stage(
                            workflow_id,
                            WorkflowStage.PENDING,
                            topic=None,
                            script_file_path=None,
                            video_file_path=None,
                            error_details=f"Previous topic rejected: {topic_err}"
                        )
                        current_stage = WorkflowStage.PENDING
                        active = self.state_manager.get_workflow(workflow_id)

                # If interrupted during generation or research, resume gracefully from previous verified state
                if current_stage == WorkflowStage.GEMINI_GENERATING:
                    if active.get("script_file_path") and Path(active["script_file_path"]).exists():
                        current_stage = WorkflowStage.SCRIPT_VALIDATED
                    else:
                        current_stage = WorkflowStage.SCRIPT_GENERATING

                if current_stage in [WorkflowStage.NEEDS_USER_ACTION, WorkflowStage.FAILED]:
                    err_notice = active.get("error_details") or "Resuming workflow..."
                    app_logger.info(f"Workflow {workflow_id} previously paused/failed: {err_notice}")
                    
                    # Check prerequisites from earliest to latest valid state
                    if active.get("video_file_path") and Path(active["video_file_path"]).exists() and active.get("topic"):
                        if "ready_to_post" in str(active["video_file_path"]):
                            current_stage = WorkflowStage.READY_TO_POST
                        else:
                            current_stage = WorkflowStage.VIDEO_DOWNLOADING
                    elif active.get("script_file_path") and Path(active["script_file_path"]).exists() and active.get("topic"):
                        try:
                            s_data = json.loads(Path(active["script_file_path"]).read_text(encoding="utf-8"))
                            s_title = s_data.get("title", "")
                            s_valid, _ = is_valid_indian_fashion_dance_topic(s_title)
                            if s_valid:
                                current_stage = WorkflowStage.SCRIPT_VALIDATED
                            else:
                                app_logger.warning(f"Cached script '{active['script_file_path']}' has non-compliant topic '{s_title}'. Invaliding cached script.")
                                self.state_manager.update_stage(workflow_id, WorkflowStage.PENDING, script_file_path=None)
                                current_stage = WorkflowStage.PENDING
                        except Exception:
                            current_stage = WorkflowStage.PENDING
                    elif active.get("topic"):
                        valid_t, _ = is_valid_indian_fashion_dance_topic(active["topic"])
                        if valid_t:
                            current_stage = WorkflowStage.SCRIPT_GENERATING
                        else:
                            current_stage = WorkflowStage.PENDING
                    else:
                        current_stage = WorkflowStage.PENDING
                    app_logger.info(f"Attempting to re-verify prerequisites and resume from stage: {current_stage.value}")
            else:
                # Check if today's UNPUBLISHED valid ready-to-post video already exists on disk
                ready_dir = BASE_DIR / "ready_to_post"
                existing_videos = list(ready_dir.glob(f"{today_str}_*.mp4"))
                unpublished_videos = []
                with self.state_manager._get_connection() as conn:
                    cur = conn.cursor()
                    for v in existing_videos:
                        cur.execute(
                            "SELECT 1 FROM workflows WHERE (video_file_path = ? OR video_file_path = ?) AND stage = ?",
                            (str(v), str(v.resolve()), WorkflowStage.PUBLISHED.value)
                        )
                        if not cur.fetchone():
                            unpublished_videos.append(v)

                if unpublished_videos:
                    v_path = unpublished_videos[0]
                    workflow_id = f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
                    active = self.state_manager.create_workflow(workflow_id, today_str)
                    current_stage = WorkflowStage.READY_TO_POST
                    app_logger.info(f"Found existing unpublished ready-to-post video for today: {v_path}. Reusing for workflow {workflow_id}.")
                    self.state_manager.update_stage(workflow_id, WorkflowStage.READY_TO_POST, video_file_path=str(v_path))
                    active = self.state_manager.get_workflow(workflow_id)
                else:
                    workflow_id = f"wf_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
                    active = self.state_manager.create_workflow(workflow_id, today_str)
                    current_stage = WorkflowStage.PENDING
                    app_logger.info(f"Initiated new workflow {workflow_id} for date {today_str}")

            gemini_page = None

            # Stage 1: Trend Researching using normal web search in a brand NEW Gemini chat
            if current_stage in [WorkflowStage.PENDING, WorkflowStage.FAILED]:
                if self._check_paused_or_stopped():
                    return {"status": "STOPPED", "message": "Workflow paused or stopped by user", "success": False}

                try:
                    self.browser_manager.ensure_context()
                except ChromeProfileLockedError as e:
                    err = str(e)
                    app_logger.warning(f"Browser profile locked at workflow start: {err}")
                    self.state_manager.update_stage(
                        workflow_id, WorkflowStage.NEEDS_USER_ACTION,
                        error_details=err, blocker_action="Close external browser using profile or verify CDP port 9222."
                    )
                    return {"status": "NEEDS_USER_ACTION", "message": err, "success": False, "stage": "NEEDS_USER_ACTION"}
                except BrowserConnectionError as e:
                    err = f"Browser connection failed: {e}. Open Authentication Browser from Dashboard."
                    app_logger.error(err)
                    self.state_manager.update_stage(
                        workflow_id, WorkflowStage.NEEDS_USER_ACTION,
                        error_details=err, blocker_action="Launch Authentication Browser and verify Chrome loads."
                    )
                    return {"status": "NEEDS_USER_ACTION", "message": err, "success": False, "stage": "NEEDS_USER_ACTION"}

                try:
                    gemini_page = self.browser_manager.new_page(prefer_existing_url="gemini.google.com")
                except Exception as e:
                    err = f"Failed to create Gemini browser page: {e}"
                    app_logger.error(err, exc_info=True)
                    self.state_manager.update_stage(workflow_id, WorkflowStage.NEEDS_USER_ACTION, error_details=err, blocker_action="Re-open Chrome authentication browser.")
                    return {"status": "NEEDS_USER_ACTION", "message": err, "success": False, "stage": "NEEDS_USER_ACTION"}

                ok_gem, msg_gem = self.gemini_client.open_fresh_daily_conversation(gemini_page)
                if not ok_gem:
                    err = f"Gemini initialization required: {msg_gem}"
                    app_logger.warning(err)
                    self.state_manager.update_stage(workflow_id, WorkflowStage.NEEDS_USER_ACTION, error_details=err, blocker_action="Log into Google on Gemini in the operator browser.")
                    return {"status": "NEEDS_USER_ACTION", "message": err, "success": False, "stage": "NEEDS_USER_ACTION"}

                self.state_manager.update_stage(workflow_id, WorkflowStage.RESEARCHING)

                def is_dup(t: str) -> bool:
                    return self.state_manager.is_topic_recently_used(t, self.config.duplicate_prevention_days)

                ok_topic, topic_data, msg_topic = self.gemini_client.research_trending_topic(
                    gemini_page,
                    self.config.topic_categories,
                    duplicate_prevention_checker=is_dup
                )

                if not ok_topic or not topic_data:
                    app_logger.warning(f"Gemini web search extraction notice: {msg_topic}. Falling back to verified Indian trend researcher.")
                    rss_topic = self.trend_researcher.find_daily_topic()
                    if not rss_topic:
                        err = f"Could not determine daily trending topic: {msg_topic}"
                        self.state_manager.update_stage(workflow_id, WorkflowStage.FAILED, error_details=err)
                        return {"status": "FAILED", "message": err, "success": False, "stage": "FAILED"}
                    topic_title = rss_topic.title
                    topic_category = rss_topic.category
                    topic_summary = rss_topic.summary
                    topic_sources = rss_topic.sources
                    song = rss_topic.song_name or ""
                    artist = rss_topic.artist or ""
                else:
                    song = topic_data.get("song_name", "")
                    artist = topic_data.get("artist", "")
                    outfit = topic_data.get("outfit_concept", "")
                    dance = topic_data.get("dance_style", "")
                    evidence = topic_data.get("trend_evidence", "")
                    
                    topic_title = f"{song} - {artist} (Indian Fashion & Dance)" if artist else f"{song} (Indian Fashion & Dance)"
                    topic_category = "Indian Fashion & Dance"
                    topic_summary = f"Song: {song} by {artist}. Outfit: {outfit}. Dance Style: {dance}. Evidence: {evidence}"
                    topic_sources = topic_data.get("source_urls") or topic_data.get("sources", [])

                # Strict final verification before advancing
                val_ok, val_err = is_valid_indian_fashion_dance_topic(topic_title, topic_summary, topic_category)
                if not val_ok:
                    app_logger.warning(f"Encountered non-compliant topic '{topic_title}': {val_err}. Falling back to curated trend researcher.")
                    rss_topic = self.trend_researcher.find_daily_topic()
                    if rss_topic:
                        topic_title = rss_topic.title
                        topic_category = rss_topic.category
                        topic_summary = rss_topic.summary
                        topic_sources = rss_topic.sources
                        song = rss_topic.song_name or ""
                        artist = rss_topic.artist or ""
                        val_ok = True
                    else:
                        err = f"Encountered non-compliant topic '{topic_title}': {val_err}"
                        self.state_manager.update_stage(workflow_id, WorkflowStage.FAILED, error_details=err)
                        return {"status": "FAILED", "message": err, "success": False, "stage": "FAILED"}

                self.state_manager.update_stage(
                    workflow_id,
                    WorkflowStage.SCRIPT_GENERATING,
                    topic=topic_title,
                    song_name=song,
                    artist=artist,
                    research_sources=topic_sources,
                    gemini_conv_id=gemini_page.url
                )
                current_stage = WorkflowStage.SCRIPT_GENERATING
                active = self.state_manager.get_workflow(workflow_id)

            # Stage 2: Generate Reel Script in the EXACT dedicated ChatGPT conversation
            if current_stage == WorkflowStage.SCRIPT_GENERATING:
                if self._check_paused_or_stopped():
                    return {"status": "STOPPED", "message": "Workflow paused or stopped by user", "success": False}
                topic_title = active["topic"]
                sources = json.loads(active["research_sources"]) if active.get("research_sources") else []
                category = "Indian Fashion & Dance"
                summary_text = active.get("summary") or f"Trending Indian Song and Fashion: {topic_title}"

                configured_chatgpt_url = self.config.chatgpt_conversation_url
                self.chatgpt_client.conversation_url = configured_chatgpt_url

                app_logger.info(f"Generating 10s script using dedicated ChatGPT conversation: '{configured_chatgpt_url}'")
                ok, script, msg = self.chatgpt_client.generate_10s_script(
                    topic=topic_title,
                    category=category,
                    research_summary=summary_text,
                    sources=sources,
                    language=self.config.preferred_language
                )

                if not ok or not script:
                    stage_to_set = WorkflowStage.NEEDS_USER_ACTION if ("authentication" in msg.lower() or "challenge" in msg.lower() or "not found" in msg.lower()) else WorkflowStage.FAILED
                    blocker = "Log into ChatGPT and open the dedicated conversation." if stage_to_set == WorkflowStage.NEEDS_USER_ACTION else "Check ChatGPT script prompt formatting."
                    self.state_manager.update_stage(workflow_id, stage_to_set, error_details=msg, blocker_action=blocker)
                    return {"status": stage_to_set.value, "message": f"ChatGPT notice: {msg}", "success": False, "stage": stage_to_set.value}

                slug = self._slugify(topic_title)
                script_path = BASE_DIR / "history" / f"{today_str}_{slug}_script.json"
                script_path.parent.mkdir(parents=True, exist_ok=True)
                with open(script_path, "w", encoding="utf-8") as f:
                    json.dump(script.to_dict(), f, indent=4)

                self.state_manager.update_stage(
                    workflow_id,
                    WorkflowStage.SCRIPT_VALIDATED,
                    chatgpt_conv_id=configured_chatgpt_url,
                    script_file_path=str(script_path),
                    song_name=script.song_name,
                    artist=script.artist
                )
                current_stage = WorkflowStage.SCRIPT_VALIDATED
                active = self.state_manager.get_workflow(workflow_id)

            # Stage 3: Return to the NEW daily Gemini conversation and submit video generation
            if current_stage == WorkflowStage.SCRIPT_VALIDATED:
                if self._check_paused_or_stopped():
                    return {"status": "STOPPED", "message": "Workflow paused or stopped by user", "success": False}
                self.state_manager.update_stage(workflow_id, WorkflowStage.GEMINI_GENERATING)

                with open(active["script_file_path"], "r", encoding="utf-8") as f:
                    script_data = json.load(f)
                script_obj = GeneratedScript(**script_data)

                if not gemini_page or gemini_page.is_closed():
                    gemini_page = self.browser_manager.new_page(prefer_existing_url="gemini.google.com")
                    existing_gem_url = active.get("gemini_conv_id")
                    if existing_gem_url and "gemini.google.com" in existing_gem_url and existing_gem_url != gemini_page.url:
                        gemini_page.goto(existing_gem_url, wait_until="domcontentloaded", timeout=45000)
                    elif not existing_gem_url:
                        self.gemini_client.open_fresh_daily_conversation(gemini_page)

                try:
                    gemini_page.bring_to_front()
                except Exception:
                    pass

                downloads_dir = BASE_DIR / "downloads"
                ok_vid, video_dl_path, gemini_conv_url, msg_vid = self.gemini_client.submit_video_generation(
                    page=gemini_page,
                    script=script_obj,
                    download_dir=downloads_dir,
                    target_seconds=self.config.target_video_duration_seconds,
                    timeout_seconds=480
                )

                if not ok_vid:
                    stage_to_set = WorkflowStage.NEEDS_USER_ACTION if ("limitation" in msg_vid.lower() or "not support" in msg_vid.lower()) else WorkflowStage.FAILED
                    blocker = "Gemini account video generation limitation. Review prompt or video permissions." if stage_to_set == WorkflowStage.NEEDS_USER_ACTION else "Video generation failed or timed out."
                    self.state_manager.update_stage(workflow_id, stage_to_set, error_details=msg_vid, blocker_action=blocker, gemini_conv_id=gemini_conv_url)
                    return {"status": stage_to_set.value, "message": msg_vid, "success": False, "stage": stage_to_set.value}

                self.state_manager.update_stage(
                    workflow_id,
                    WorkflowStage.VIDEO_DOWNLOADING,
                    video_file_path=video_dl_path,
                    gemini_conv_id=gemini_conv_url
                )
                current_stage = WorkflowStage.VIDEO_DOWNLOADING
                active = self.state_manager.get_workflow(workflow_id)

            # Stage 4: Video Validation, Media Inspection, and Trimming
            if current_stage in [WorkflowStage.VIDEO_DOWNLOADING, WorkflowStage.VIDEO_VALIDATING]:
                if self._check_paused_or_stopped():
                    return {"status": "STOPPED", "message": "Workflow paused or stopped by user", "success": False}
                self.state_manager.update_stage(workflow_id, WorkflowStage.VIDEO_VALIDATING)

                dl_path = active["video_file_path"]
                slug = self._slugify(active["topic"])
                ready_dir = BASE_DIR / "ready_to_post"

                ok, prepared_video, info = self.video_manager.prepare_ready_to_post(
                    downloaded_file=dl_path,
                    target_dir=ready_dir,
                    date_str=today_str,
                    topic_slug=slug
                )

                if not ok:
                    err = f"Video validation failed: {info.get('error')}"
                    self.state_manager.update_stage(workflow_id, WorkflowStage.FAILED, error_details=err, blocker_action="Inspect downloaded video file integrity.")
                    return {"status": "FAILED", "message": err, "success": False, "stage": "FAILED"}

                with open(active["script_file_path"], "r", encoding="utf-8") as f:
                    script_data = json.load(f)

                meta = self.caption_generator.generate(
                    topic_title=active["topic"],
                    category="Indian Fashion & Dance",
                    hook=script_data.get("hook", ""),
                    narration=script_data.get("narration", ""),
                    duration_sec=info.get("duration", 10.0),
                    song_name=script_data.get("song_name", ""),
                    artist=script_data.get("artist", "")
                )

                meta_dict = meta.to_dict()
                meta_dict["song_name"] = script_data.get("song_name")
                meta_dict["artist"] = script_data.get("artist")
                meta_dict["clothing_details"] = script_data.get("clothing_details")
                meta_dict["choreography"] = script_data.get("choreography")
                meta_dict["video_generation_prompt"] = script_data.get("video_generation_prompt")
                meta_dict["licensing_notes"] = script_data.get("licensing_notes")

                meta_path = ready_dir / f"{Path(prepared_video).stem}_metadata.json"
                with open(meta_path, "w", encoding="utf-8") as f:
                    json.dump(meta_dict, f, indent=4)

                self.state_manager.update_stage(
                    workflow_id,
                    WorkflowStage.READY_TO_POST,
                    video_file_path=prepared_video,
                    video_duration=info.get("duration", 0),
                    video_width=info.get("width", 0),
                    video_height=info.get("height", 0),
                    caption=meta.caption,
                    hashtags=" ".join(meta.hashtags)
                )
                current_stage = WorkflowStage.READY_TO_POST
                active = self.state_manager.get_workflow(workflow_id)

            # Stage 5: Instagram Publishing
            if current_stage in [WorkflowStage.READY_TO_POST, WorkflowStage.PUBLISHING]:
                if self._check_paused_or_stopped():
                    return {"status": "STOPPED", "message": "Workflow paused or stopped by user", "success": False}
                
                if not self.config.auto_publish_enabled and not force:
                    app_logger.info("Reel is READY_TO_POST. Auto-publish is disabled pending user confirmation.")
                    self.state_manager.update_stage(workflow_id, WorkflowStage.READY_TO_POST)
                    return {
                        "status": "READY_TO_POST",
                        "message": "Reel prepared and validated. Waiting for user approval to publish.",
                        "success": False,
                        "video_path": active["video_file_path"]
                    }

                self.state_manager.update_stage(workflow_id, WorkflowStage.PUBLISHING)
                formatted_text = f"{active['caption']}\n\n{active['hashtags']}"

                ok, pub_id, pub_url, msg = self.instagram_publisher.publish_reel(
                    video_path=active["video_file_path"],
                    caption_text=formatted_text,
                    force=force
                )

                if not ok:
                    blocker = "Log into Instagram @aitrending.dance in the operator browser." if "login" in msg.lower() else "Check Instagram publishing UI."
                    self.state_manager.update_stage(workflow_id, WorkflowStage.NEEDS_USER_ACTION, error_details=msg, blocker_action=blocker)
                    return {"status": "NEEDS_USER_ACTION", "message": msg, "success": False, "stage": "NEEDS_USER_ACTION"}

                posted_dir = BASE_DIR / "posted"
                posted_dir.mkdir(parents=True, exist_ok=True)
                posted_video_path = posted_dir / Path(active["video_file_path"]).name
                shutil.copy2(active["video_file_path"], str(posted_video_path))

                sources = json.loads(active["research_sources"]) if active.get("research_sources") else []
                self.state_manager.record_used_topic(
                    topic=active["topic"],
                    category="Indian Fashion & Dance",
                    sources=sources,
                    workflow_id=workflow_id,
                    used_date=today_str
                )

                self.state_manager.update_stage(
                    workflow_id,
                    WorkflowStage.PUBLISHED,
                    publication_id=pub_id,
                    publication_url=pub_url,
                    publication_status="PUBLISHED"
                )
                app_logger.info(f"Daily Instagram Reel workflow {workflow_id} completed successfully! URL: {pub_url}")
                return {
                    "status": "PUBLISHED",
                    "message": "Successfully generated and published Instagram Reel",
                    "success": True,
                    "workflow_id": workflow_id,
                    "url": pub_url,
                    "topic": active.get("topic")
                }

        except ChromeProfileLockedError as e:
            err_msg = str(e)
            app_logger.warning(f"Workflow paused due to Chrome profile lock: {err_msg}")
            self.state_manager.update_stage(workflow_id, WorkflowStage.NEEDS_USER_ACTION, error_details=err_msg, blocker_action="Close external Chrome window.")
            return {"status": "NEEDS_USER_ACTION", "message": err_msg, "success": False}
        except Exception as e:
            app_logger.error(f"Unexpected error in orchestrator: {e}", exc_info=True)
            self.state_manager.update_stage(workflow_id, WorkflowStage.FAILED, error_details=str(e), blocker_action="Check application logs for details.")
            return {"status": "FAILED", "message": f"Unexpected error: {e}", "success": False}
        finally:
            self._is_running = False
            ip_lock.release()
            try:
                self.browser_manager.close()
            except Exception as e:
                app_logger.warning(f"Browser cleanup in workflow finally block: {e}")

    def publish_existing_reel(self, workflow_id: Optional[str] = None) -> Dict[str, Any]:
        """Publishes the existing ready-to-post Reel without generating any new video."""
        with self._thread_lock:
            if self._is_running:
                app_logger.warning("A workflow is already currently running.")
                return {"status": "RUNNING", "message": "Workflow already in progress", "success": False}

            ip_lock = InterProcessWorkflowLock(BASE_DIR / "data" / "workflow.lock")
            if not ip_lock.acquire():
                app_logger.warning("Another process holds the workflow execution lock.")
                return {"status": "RUNNING", "message": "Another process holds workflow lock", "success": False}

            self._is_running = True

        today_str = datetime.now().strftime("%Y-%m-%d")
        try:
            if workflow_id:
                active = self.state_manager.get_workflow(workflow_id)
            else:
                active = self.state_manager.get_todays_active_workflow(today_str)
                if not active or not active.get("video_file_path"):
                    with self.state_manager._get_connection() as conn:
                        cur = conn.cursor()
                        cur.execute(
                            "SELECT * FROM workflows WHERE video_file_path IS NOT NULL AND stage != 'PUBLISHED' ORDER BY updated_at DESC LIMIT 1"
                        )
                        row = cur.fetchone()
                        if row:
                            active = dict(row)

            if not active or not active.get("video_file_path"):
                err = "No existing ready-to-post video found to publish."
                app_logger.error(err)
                return {"status": "FAILED", "message": err, "success": False}

            wf_id = active["workflow_id"]
            video_path = Path(active["video_file_path"])
            if not video_path.exists():
                err = f"Existing video file not found at: {video_path}"
                app_logger.error(err)
                return {"status": "FAILED", "message": err, "success": False}

            v_info = self.video_manager.inspect_video_media(str(video_path))
            if not v_info.get("valid"):
                err = f"Existing video validation failed: {v_info.get('error')}"
                app_logger.error(err)
                return {"status": "FAILED", "message": err, "success": False}

            self.browser_manager.ensure_context()

            meta_file = video_path.parent / f"{video_path.stem}_metadata.json"
            meta_data = {}
            if meta_file.exists():
                try:
                    with open(meta_file, "r", encoding="utf-8") as f:
                        meta_data = json.load(f)
                except Exception:
                    pass

            song_name = meta_data.get("song_name") or active.get("song_name") or active.get("topic") or "Trending Indian Song"
            artist = meta_data.get("artist") or active.get("artist") or ""
            clothing = meta_data.get("clothing_details") or "Modern casual chic Indian fashion outfit"
            choreography = meta_data.get("choreography") or "Upbeat synchronized Bollywood dance hook step"
            topic = active.get("topic") or meta_data.get("topic") or "Indian Fashion & Dance"

            if meta_data.get("caption") and "Opening 1-2 seconds" not in meta_data.get("caption", ""):
                app_logger.info("Using freshly generated video-specific caption from metadata.")
                formatted_post_text = meta_data.get("formatted_post_text") or f"{meta_data['caption']}\n\n{' '.join(meta_data.get('hashtags', []))}"
            else:
                app_logger.info("Requesting fresh video-specific caption from dedicated ChatGPT conversation...")
                ok_cap, cap_dict, msg_cap = self.chatgpt_client.generate_video_specific_caption(
                    topic=topic,
                    song_name=song_name,
                    artist=artist,
                    clothing_details=clothing,
                    choreography=choreography
                )

                if ok_cap and cap_dict:
                    caption = cap_dict.get("caption", active.get("caption", ""))
                    tags = cap_dict.get("hashtags", [])
                    formatted_post_text = cap_dict.get("formatted_post_text") or f"{caption}\n\n{' '.join(tags)}"
                    meta_data["caption"] = caption
                    meta_data["hashtags"] = tags
                    meta_data["formatted_post_text"] = formatted_post_text
                    try:
                        with open(meta_file, "w", encoding="utf-8") as f:
                            json.dump(meta_data, f, indent=4)
                    except Exception as e:
                        app_logger.warning(f"Could not update metadata JSON: {e}")
                else:
                    app_logger.warning(f"ChatGPT caption generation notice: {msg_cap}. Using existing verified caption.")
                    formatted_post_text = f"{active['caption']}\n\n{active.get('hashtags', '')}"

            self.state_manager.update_stage(
                wf_id,
                WorkflowStage.PUBLISHING,
                caption=meta_data.get("caption", active.get("caption")),
                hashtags=" ".join(meta_data.get("hashtags", []))
            )

            ok_pub, pub_id, pub_url, msg_pub = self.instagram_publisher.publish_reel(
                video_path=str(video_path),
                caption_text=formatted_post_text,
                force=True
            )

            if not ok_pub:
                self.state_manager.update_stage(wf_id, WorkflowStage.NEEDS_USER_ACTION, error_details=msg_pub, blocker_action="Check Instagram login or dialog.")
                return {"status": "NEEDS_USER_ACTION", "message": msg_pub, "success": False, "stage": "NEEDS_USER_ACTION"}

            posted_dir = BASE_DIR / "posted"
            posted_dir.mkdir(parents=True, exist_ok=True)
            posted_video_path = posted_dir / video_path.name
            shutil.copy2(str(video_path), str(posted_video_path))

            self.state_manager.update_stage(
                wf_id,
                WorkflowStage.PUBLISHED,
                publication_id=pub_id,
                publication_url=pub_url,
                publication_status="PUBLISHED"
            )
            app_logger.info(f"Reel successfully published and recorded in database! URL: {pub_url}")
            return {
                "status": "PUBLISHED",
                "message": "Successfully published Instagram Reel",
                "success": True,
                "workflow_id": wf_id,
                "url": pub_url,
                "video_path": str(posted_video_path)
            }

        except Exception as e:
            app_logger.error(f"Error during publish_existing_reel: {e}", exc_info=True)
            self.state_manager.update_stage(wf_id, WorkflowStage.FAILED, error_details=str(e))
            return {"status": "FAILED", "message": str(e), "success": False}
        finally:
            self._is_running = False
            ip_lock.release()
            try:
                self.browser_manager.close()
            except Exception as e:
                app_logger.warning(f"Browser cleanup in publish_existing_reel finally block: {e}")

    def _check_paused_or_stopped(self) -> bool:
        while self._is_paused and self._is_running:
            time.sleep(1)
        return not self._is_running

    @staticmethod
    def _slugify(text: str) -> str:
        s = re.sub(r"[^\w\s-]", "", text).strip().lower()
        return re.sub(r"[-\s]+", "_", s)[:30]
