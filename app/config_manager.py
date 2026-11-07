import os
import json
from pathlib import Path
from dataclasses import dataclass, asdict, field
from typing import List, Dict, Any, Optional

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
DOWNLOADS_DIR = BASE_DIR / "downloads"
READY_TO_POST_DIR = BASE_DIR / "ready_to_post"
POSTED_DIR = BASE_DIR / "posted"
HISTORY_DIR = BASE_DIR / "history"
TEMP_DIR = BASE_DIR / "temp"

CONFIG_FILE = CONFIG_DIR / "settings.json"

@dataclass
class AppConfig:
    # Workflow & Scheduling
    max_reels_per_day: int = 1
    schedule_time_hhmm: str = "09:00"
    auto_publish_enabled: bool = False  # False until user confirms initial publication
    duplicate_prevention_days: int = 30
    
    # Content & Script parameters
    target_video_duration_seconds: int = 10
    preferred_language: str = "English"  # or "Hindi"
    topic_categories: List[str] = field(default_factory=lambda: [
        "Artificial Intelligence",
        "Technology",
        "Gaming",
        "Interesting Facts",
        "Science",
        "Educational Information",
        "Current Viral Topics",
        "Major Current News Stories"
    ])
    caption_style: str = "Engaging, hook-driven, factual, with relevant hashtags"
    
    # Browser Automation Settings (Dedicated Automation Profile)
    browser_headless: bool = False  # ChatGPT/Gemini/IG often require headed/minimized window to avoid bot walls
    chrome_executable_path: str = "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
    target_google_account: str = "palvisheshpal292@gmail.com"
    operator_profile_dir: str = str(BASE_DIR / "data" / "operator_chrome_profile")
    remote_debugging_port: int = 9222
    
    # ChatGPT Settings
    chatgpt_conversation_url: Optional[str] = "https://chatgpt.com/g/g-p-6ad4d211b748819196b6cd4d39285240-ai-instagram/c/6ad4d21e-d484-83ee-b9c3-953e67f0c525"
    chatgpt_model_hint: str = "auto"
    
    # Gemini Settings
    gemini_url: str = "https://gemini.google.com/"
    
    # Instagram Settings
    instagram_publishing_method: str = "browser"  # 'browser' or 'official_api'
    instagram_target_account: Optional[str] = None
    instagram_api_access_token: Optional[str] = None
    instagram_business_account_id: Optional[str] = None
    
    # System Paths
    ffmpeg_path: Optional[str] = None  # auto-detected or configured
    ffprobe_path: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppConfig":
        valid_keys = cls.__dataclass_fields__.keys()
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        if "operator_profile_dir" not in filtered:
            filtered["operator_profile_dir"] = str(BASE_DIR / "data" / "operator_chrome_profile")
        return cls(**filtered)


class ConfigurationManager:
    """Manages application configuration with persistence and validation."""
    
    def __init__(self, config_path: Path = CONFIG_FILE):
        self.config_path = config_path
        self.config: AppConfig = self.load()

    def load(self) -> AppConfig:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return AppConfig.from_dict(data)
            except Exception as e:
                print(f"[ConfigManager] Warning loading config: {e}. Falling back to default.")
        
        cfg = AppConfig()
        self.save(cfg)
        return cfg

    def save(self, cfg: Optional[AppConfig] = None) -> None:
        if cfg is not None:
            self.config = cfg
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.config.to_dict(), f, indent=4)

    def update(self, **kwargs) -> AppConfig:
        current_dict = self.config.to_dict()
        for k, v in kwargs.items():
            if k in current_dict:
                current_dict[k] = v
        self.config = AppConfig.from_dict(current_dict)
        self.save()
        return self.config
