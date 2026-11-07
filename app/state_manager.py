import sqlite3
import json
import contextlib
from pathlib import Path
from datetime import datetime, date
from typing import Optional, List, Dict, Any
from enum import Enum

from .logger import app_logger

DATABASE_PATH = Path(__file__).resolve().parent.parent / "data" / "operator.db"

class WorkflowStage(str, Enum):
    PENDING = "PENDING"
    RESEARCHING = "RESEARCHING"
    SCRIPT_GENERATING = "SCRIPT_GENERATING"
    SCRIPT_VALIDATED = "SCRIPT_VALIDATED"
    GEMINI_GENERATING = "GEMINI_GENERATING"
    VIDEO_DOWNLOADING = "VIDEO_DOWNLOADING"
    VIDEO_VALIDATING = "VIDEO_VALIDATING"
    READY_TO_POST = "READY_TO_POST"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    FAILED = "FAILED"
    NEEDS_USER_ACTION = "NEEDS_USER_ACTION"

class StateManager:
    """Persistent SQLite database manager for workflow execution, state tracking, and duplicate prevention."""

    def __init__(self, db_path: Path = DATABASE_PATH):
        self.db_path = Path(db_path).resolve()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextlib.contextmanager
    def _get_connection(self):
        conn = sqlite3.connect(str(self.db_path), timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            conn.close()

    def _init_db(self):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id TEXT PRIMARY KEY,
                    local_date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    completion_time TEXT,
                    stage TEXT NOT NULL,
                    last_successful_stage TEXT,
                    topic TEXT,
                    song_name TEXT,
                    artist TEXT,
                    research_sources TEXT,
                    chatgpt_conv_id TEXT,
                    gemini_conv_id TEXT,
                    script_file_path TEXT,
                    video_file_path TEXT,
                    video_duration REAL,
                    video_width INTEGER,
                    video_height INTEGER,
                    caption TEXT,
                    hashtags TEXT,
                    publication_id TEXT,
                    publication_url TEXT,
                    publication_status TEXT,
                    retry_count INTEGER DEFAULT 0,
                    error_details TEXT,
                    blocker_action TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Add optional columns if migrating an older database
            existing_cols = [c[1] for c in cursor.execute("PRAGMA table_info(workflows)").fetchall()]
            for col in ["last_successful_stage", "song_name", "artist", "blocker_action"]:
                if col not in existing_cols:
                    try:
                        cursor.execute(f"ALTER TABLE workflows ADD COLUMN {col} TEXT")
                    except Exception:
                        pass

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_workflows_date ON workflows (local_date)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_workflows_stage ON workflows (stage)
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS topics_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    topic TEXT NOT NULL,
                    category TEXT NOT NULL,
                    sources TEXT NOT NULL,
                    used_date TEXT NOT NULL,
                    workflow_id TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()

    def get_todays_successful_workflow(self, target_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Checks if a workflow has already successfully published for today."""
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM workflows WHERE local_date = ? AND stage = ? LIMIT 1",
                (target_date, WorkflowStage.PUBLISHED.value)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_todays_active_workflow(self, target_date: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Returns today's active or recoverable workflow if not yet published."""
        if not target_date:
            target_date = datetime.now().strftime("%Y-%m-%d")

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM workflows WHERE local_date = ? AND stage != ? ORDER BY updated_at DESC LIMIT 1",
                (target_date, WorkflowStage.PUBLISHED.value)
            )
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_latest_workflow(self) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workflows ORDER BY updated_at DESC LIMIT 1")
            row = cursor.fetchone()
            return dict(row) if row else None

    def create_workflow(self, workflow_id: str, local_date: Optional[str] = None) -> Dict[str, Any]:
        if not local_date:
            local_date = datetime.now().strftime("%Y-%m-%d")

        now_str = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO workflows (
                    workflow_id, local_date, start_time, stage, retry_count, updated_at
                ) VALUES (?, ?, ?, ?, 0, ?)
            """, (workflow_id, local_date, now_str, WorkflowStage.PENDING.value, now_str))
            conn.commit()

        app_logger.info(f"Created workflow record {workflow_id} for date {local_date}")
        return self.get_workflow(workflow_id)

    def get_workflow(self, workflow_id: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workflows WHERE workflow_id = ?", (workflow_id,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def update_stage(self, workflow_id: str, stage: WorkflowStage, error_details: Optional[str] = None, **kwargs) -> None:
        now_str = datetime.now().isoformat()
        fields = ["stage = ?", "updated_at = ?"]
        values = [stage.value, now_str]

        # Automatically track last successful stage for non-failing transitions
        if stage not in [WorkflowStage.FAILED, WorkflowStage.NEEDS_USER_ACTION]:
            fields.append("last_successful_stage = ?")
            values.append(stage.value)

        if error_details is not None:
            fields.append("error_details = ?")
            values.append(error_details)

        if stage == WorkflowStage.PUBLISHED:
            fields.append("completion_time = ?")
            values.append(now_str)

        for k, v in kwargs.items():
            if isinstance(v, (dict, list)):
                v = json.dumps(v)
            fields.append(f"{k} = ?")
            values.append(v)

        values.append(workflow_id)
        sql = f"UPDATE workflows SET {', '.join(fields)} WHERE workflow_id = ?"

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, values)
            conn.commit()

        app_logger.info(f"Workflow {workflow_id} progressed to stage: {stage.value}")

    def increment_retry(self, workflow_id: str) -> int:
        now_str = datetime.now().isoformat()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE workflows 
                SET retry_count = retry_count + 1, updated_at = ? 
                WHERE workflow_id = ?
            """, (now_str, workflow_id))
            cursor.execute("SELECT retry_count FROM workflows WHERE workflow_id = ?", (workflow_id,))
            row = cursor.fetchone()
            count = row[0] if row else 1
            conn.commit()
            return count

    def record_used_topic(self, topic: str, category: str, sources: List[str], workflow_id: str, used_date: Optional[str] = None):
        if not used_date:
            used_date = datetime.now().strftime("%Y-%m-%d")

        sources_json = json.dumps(sources)
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO topics_history (topic, category, sources, used_date, workflow_id)
                VALUES (?, ?, ?, ?, ?)
            """, (topic, category, sources_json, used_date, workflow_id))
            conn.commit()

    def is_topic_recently_used(self, topic: str, days_window: int = 30) -> bool:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT COUNT(*) FROM topics_history 
                WHERE LOWER(topic) = LOWER(?) 
                AND julianday('now') - julianday(used_date) <= ?
            """, (topic, days_window))
            count = cursor.fetchone()[0]
            return count > 0

    def get_recent_topics(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM topics_history ORDER BY id DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def get_recent_workflows(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workflows ORDER BY start_time DESC LIMIT ?", (limit,))
            return [dict(r) for r in cursor.fetchall()]
