import sys
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.config_manager import ConfigurationManager
from app.state_manager import StateManager
from app.trend_researcher import TrendResearcher
from app.video_manager import VideoManager
from app.caption_generator import CaptionGenerator

def run_preflight_checks():
    print("=" * 60)
    print(" AI INSTAGRAM REEL OPERATOR — SYSTEM DIAGNOSTIC TEST ")
    print("=" * 60)

    # 1. Test Configuration Manager
    print("\n[1/5] Testing Configuration Manager...")
    cfg_mgr = ConfigurationManager()
    cfg = cfg_mgr.config
    print(f"  ✓ Config Loaded: Language={cfg.preferred_language}, Schedule={cfg.schedule_time_hhmm}, Duration={cfg.target_video_duration_seconds}s")

    # 2. Test State Manager (SQLite database)
    print("\n[2/5] Testing State Manager (SQLite)...")
    sm = StateManager()
    todays = sm.get_todays_successful_workflow()
    print(f"  ✓ Database Connected: DB at {sm.db_path.name}")
    print(f"  ✓ Today's status: {'Already Published' if todays else 'Eligible for daily run'}")

    # 3. Test Trend Researcher
    print("\n[3/5] Testing Live Trend Researcher (Verified Feeds)...")
    researcher = TrendResearcher(sm)
    topic = researcher.find_daily_topic(cfg.topic_categories)
    if topic:
        print(f"  ✓ Verified Topic Fetched: \"{topic.title}\"")
        print(f"  ✓ Category: {topic.category}")
        print(f"  ✓ Source: {topic.sources[0] if topic.sources else 'N/A'}")
    else:
        print("  ✗ Warning: No verified topic could be retrieved.")

    # 4. Test Caption Generator
    print("\n[4/5] Testing Caption Generator...")
    cap_gen = CaptionGenerator()
    test_topic = topic.title if topic else "Next-Gen AI Breakthroughs"
    meta = cap_gen.generate(
        topic_title=test_topic,
        category="Technology",
        hook="Did you know AI models can now think in parallel?",
        narration="New neural architectures are processing multi-step reasoning twenty times faster than previous generations.",
        duration_sec=10.0
    )
    print(f"  ✓ Generated Caption:\n---\n{meta.formatted_post_text}\n---")

    # 5. Test Video Manager
    print("\n[5/5] Testing Video Inspection & Processing...")
    vm = VideoManager()
    ffmpeg_found = vm.is_ffmpeg_available()
    print(f"  ✓ Video Engine: {'FFmpeg Binary Detected' if ffmpeg_found else 'Native Parser Active (FFmpeg recommended for sub-frame trimming)'}")

    print("\n" + "=" * 60)
    print(" DIAGNOSTIC COMPLETED: Core logical modules functional!")
    print("=" * 60)

if __name__ == "__main__":
    run_preflight_checks()
