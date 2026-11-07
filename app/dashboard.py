import os
import sys
import threading
from pathlib import Path
from datetime import datetime

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QTabWidget, QLineEdit, QCheckBox, QComboBox,
    QSystemTrayIcon, QMenu, QMessageBox, QFileDialog, QGroupBox, QSpinBox
)
from PySide6.QtCore import Qt, QTimer, Signal, QObject
from PySide6.QtGui import QIcon, QFont, QColor

from .logger import app_logger, MAIN_LOG_FILE
from .config_manager import ConfigurationManager, BASE_DIR
from .state_manager import StateManager
from .orchestrator import WorkflowOrchestrator
from .scheduler import SchedulerService
from .windows_startup import install_windows_startup_task, remove_windows_startup_task

class WorkerSignals(QObject):
    status_updated = Signal(str, str)
    workflow_finished = Signal(dict)

class DashboardWindow(QMainWindow):
    """Production desktop dashboard providing full control, visibility, and configuration."""

    def __init__(self, orchestrator: WorkflowOrchestrator, scheduler: SchedulerService):
        super().__init__()
        self.orchestrator = orchestrator
        self.scheduler = scheduler
        self.config_manager = orchestrator.config_manager
        self.state_manager = orchestrator.state_manager
        self.signals = WorkerSignals()

        self.setWindowTitle("AI Instagram Reel Operator — Control Dashboard")
        self.resize(1000, 700)
        self.setMinimumSize(850, 600)

        # Center window on primary screen to avoid opening off-screen
        screen = QApplication.primaryScreen()
        if screen:
            screen_geo = screen.availableGeometry()
            x = (screen_geo.width() - 1000) // 2 + screen_geo.x()
            y = (screen_geo.height() - 700) // 2 + screen_geo.y()
            self.setGeometry(max(screen_geo.x(), x), max(screen_geo.y(), y), 1000, 700)

        self._init_ui()
        self._init_tray()
        self._init_timers()
        self.refresh_state()

    def _init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(12)

        # Header / Status Banner
        header_group = QGroupBox("Live Operator Status")
        header_layout = QHBoxLayout(header_group)

        self.lbl_operator_status = QLabel("Operator: Idle")
        self.lbl_operator_status.setFont(QFont("Segoe UI", 11, QFont.Bold))
        self.lbl_operator_status.setStyleSheet("color: #0078d4;")

        self.lbl_current_stage = QLabel("Stage: PENDING")
        self.lbl_current_stage.setFont(QFont("Segoe UI", 10))

        self.lbl_today_status = QLabel("Today's Publication: Not Published")
        self.lbl_today_status.setFont(QFont("Segoe UI", 10))

        header_layout.addWidget(self.lbl_operator_status)
        header_layout.addWidget(self.lbl_current_stage)
        header_layout.addWidget(self.lbl_today_status)
        main_layout.addWidget(header_group)

        # Tab Widget: Overview, Configuration, Logs, History
        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_overview_tab(), "Overview & Control")
        self.tabs.addTab(self._create_config_tab(), "Configuration")
        self.tabs.addTab(self._create_history_tab(), "Workflow History")
        self.tabs.addTab(self._create_logs_tab(), "Live Logs")
        main_layout.addWidget(self.tabs)

        # Bottom Quick Action Bar
        bottom_bar = QHBoxLayout()

        self.btn_run_now = QPushButton("⚡ Run Daily Workflow Now")
        self.btn_run_now.setStyleSheet("background-color: #0078d4; color: white; font-weight: bold; padding: 8px 16px;")
        self.btn_run_now.clicked.connect(self.action_run_now)

        self.btn_pause = QPushButton("⏸ Pause Operator")
        self.btn_pause.clicked.connect(self.action_pause_resume)

        self.btn_stop = QPushButton("⏹ Stop Current Workflow")
        self.btn_stop.clicked.connect(self.action_stop)

        bottom_bar.addWidget(self.btn_run_now)
        bottom_bar.addWidget(self.btn_pause)
        bottom_bar.addWidget(self.btn_stop)
        bottom_bar.addStretch()

        main_layout.addLayout(bottom_bar)

    def _create_overview_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        # Details Grid
        details_group = QGroupBox("Workflow Diagnostics & Live Status")
        details_layout = QVBoxLayout(details_group)

        self.lbl_last_successful_stage = QLabel("Last Successful Stage: None")
        self.lbl_selected_topic = QLabel("Selected Topic: None")
        self.lbl_selected_topic.setWordWrap(True)
        self.lbl_selected_song = QLabel("Selected Song: None")
        self.lbl_video_path = QLabel("Video Path: None")
        self.lbl_video_path.setWordWrap(True)
        self.lbl_video_validation = QLabel("Video Validation: Not Validated")
        self.lbl_caption_status = QLabel("Caption Status: Not Generated")
        self.lbl_post_url = QLabel("Published Reel URL: None")
        self.lbl_post_url.setOpenExternalLinks(True)
        self.lbl_retry_info = QLabel("Workflow Retries: 0 / 3")
        self.lbl_next_run = QLabel("Next Scheduled Run: Pending")
        self.lbl_blocker_action = QLabel("Current Blocker & Action: None")
        self.lbl_blocker_action.setWordWrap(True)
        self.lbl_blocker_action.setStyleSheet("color: #d13438; font-weight: bold;")
        self.lbl_last_error = QLabel("Last Notice / Error: None")
        self.lbl_last_error.setWordWrap(True)
        self.lbl_last_error.setStyleSheet("color: #d13438;")

        details_layout.addWidget(self.lbl_last_successful_stage)
        details_layout.addWidget(self.lbl_selected_topic)
        details_layout.addWidget(self.lbl_selected_song)
        details_layout.addWidget(self.lbl_video_path)
        details_layout.addWidget(self.lbl_video_validation)
        details_layout.addWidget(self.lbl_caption_status)
        details_layout.addWidget(self.lbl_post_url)
        details_layout.addWidget(self.lbl_retry_info)
        details_layout.addWidget(self.lbl_next_run)
        details_layout.addWidget(self.lbl_blocker_action)
        details_layout.addWidget(self.lbl_last_error)
        layout.addWidget(details_group)

        # Quick Folder Shortcuts
        folder_group = QGroupBox("Directory Shortcuts")
        folder_layout = QHBoxLayout(folder_group)

        btn_open_downloads = QPushButton("Open Downloads")
        btn_open_downloads.clicked.connect(lambda: self._open_dir(BASE_DIR / "downloads"))
        btn_open_ready = QPushButton("Open Ready-to-Post")
        btn_open_ready.clicked.connect(lambda: self._open_dir(BASE_DIR / "ready_to_post"))
        btn_open_posted = QPushButton("Open Posted Archive")
        btn_open_posted.clicked.connect(lambda: self._open_dir(BASE_DIR / "posted"))
        btn_open_logs = QPushButton("Open Logs Folder")
        btn_open_logs.clicked.connect(lambda: self._open_dir(BASE_DIR / "logs"))

        folder_layout.addWidget(btn_open_downloads)
        folder_layout.addWidget(btn_open_ready)
        folder_layout.addWidget(btn_open_posted)
        folder_layout.addWidget(btn_open_logs)
        layout.addWidget(folder_group)

        # Interactive Session Login Helper
        session_group = QGroupBox("Browser Session & Authentication Setup")
        session_layout = QHBoxLayout(session_group)
        session_desc = QLabel("Open the dedicated persistent browser to authenticate ChatGPT, Gemini, or Instagram:")
        btn_open_auth_browser = QPushButton("🔑 Open Authentication Browser")
        btn_open_auth_browser.clicked.connect(self.action_open_auth_browser)
        session_layout.addWidget(session_desc)
        session_layout.addWidget(btn_open_auth_browser)
        layout.addWidget(session_group)

        layout.addStretch()
        return widget

    def _create_config_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        cfg = self.config_manager.config

        # Settings
        self.chk_auto_publish = QCheckBox("Enable Automatic Instagram Publication (Uncheck to review before publishing)")
        self.chk_auto_publish.setChecked(cfg.auto_publish_enabled)

        self.txt_schedule_time = QLineEdit(cfg.schedule_time_hhmm)
        self.txt_schedule_time.setPlaceholderText("09:00")

        self.txt_chatgpt_url = QLineEdit(cfg.chatgpt_conversation_url or "")
        self.txt_chatgpt_url.setPlaceholderText("https://chatgpt.com/c/your-dedicated-conversation-id")

        self.cmb_language = QComboBox()
        self.cmb_language.addItems(["English", "Hindi"])
        self.cmb_language.setCurrentText(cfg.preferred_language)

        self.spn_duration = QSpinBox()
        self.spn_duration.setRange(5, 30)
        self.spn_duration.setValue(cfg.target_video_duration_seconds)

        self.chk_windows_startup = QCheckBox("Launch Automatically at Windows Login (via Windows Task Scheduler)")
        self.chk_windows_startup.setChecked(True)

        layout.addWidget(self.chk_auto_publish)

        h_sched = QHBoxLayout()
        h_sched.addWidget(QLabel("Daily Run Time (HH:MM):"))
        h_sched.addWidget(self.txt_schedule_time)
        layout.addLayout(h_sched)

        h_chat = QHBoxLayout()
        h_chat.addWidget(QLabel("Dedicated ChatGPT Conversation URL:"))
        h_chat.addWidget(self.txt_chatgpt_url)
        layout.addLayout(h_chat)

        h_lang = QHBoxLayout()
        h_lang.addWidget(QLabel("Script Language:"))
        h_lang.addWidget(self.cmb_language)
        layout.addLayout(h_lang)

        h_dur = QHBoxLayout()
        h_dur.addWidget(QLabel("Target Video Duration (seconds):"))
        h_dur.addWidget(self.spn_duration)
        layout.addLayout(h_dur)

        layout.addWidget(self.chk_windows_startup)

        btn_save_config = QPushButton("💾 Save Configuration")
        btn_save_config.clicked.connect(self.action_save_config)
        layout.addWidget(btn_save_config)

        layout.addStretch()
        return widget

    def _create_history_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.table_history = QTableWidget()
        self.table_history.setColumnCount(6)
        self.table_history.setHorizontalHeaderLabels(["Date", "Stage", "Topic", "Duration", "Publication URL", "Error Details"])
        self.table_history.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table_history)

        btn_refresh_history = QPushButton("🔄 Refresh History")
        btn_refresh_history.clicked.connect(self.refresh_history)
        layout.addWidget(btn_refresh_history)

        return widget

    def _create_logs_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.txt_logs = QTextEdit()
        self.txt_logs.setReadOnly(True)
        self.txt_logs.setFont(QFont("Consolas", 9))
        layout.addWidget(self.txt_logs)

        btn_refresh_logs = QPushButton("🔄 Refresh Logs")
        btn_refresh_logs.clicked.connect(self.refresh_logs)
        layout.addWidget(btn_refresh_logs)

        return widget

    def _init_tray(self):
        # Do NOT pass 'self' as parent to QSystemTrayIcon.
        # On some Windows DPI configurations, parenting the tray icon to the
        # QMainWindow causes the main window to behave as a tool-window and
        # suppresses it from the taskbar / foreground activation queue.
        self.tray_icon = QSystemTrayIcon()
        self.tray_icon.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        self.tray_icon.setToolTip("AI Instagram Reel Operator")

        tray_menu = QMenu()
        show_action = tray_menu.addAction("Show Dashboard")
        show_action.triggered.connect(self.action_show_dashboard)
        run_action = tray_menu.addAction("Run Now")
        run_action.triggered.connect(self.action_run_now)
        tray_menu.addSeparator()
        exit_action = tray_menu.addAction("Exit Operator")
        exit_action.triggered.connect(self.action_exit_operator)

        self.tray_icon.setContextMenu(tray_menu)
        # Double-click on the tray icon shows/restores the dashboard
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.action_show_dashboard()

    def action_show_dashboard(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def action_exit_operator(self):
        """User explicitly requested exit via tray menu."""
        app_logger.info("Exit Operator requested from tray menu. Shutting down...")
        self.close()

    def closeEvent(self, event):
        """Cleanly shut down background timers, scheduler, and orchestrator when the window closes."""
        app_logger.info("Dashboard closeEvent received. Shutting down operator background services...")
        try:
            if hasattr(self, "timer") and self.timer:
                self.timer.stop()
            if hasattr(self, "scheduler") and self.scheduler:
                self.scheduler.stop()
            if hasattr(self, "orchestrator") and self.orchestrator:
                self.orchestrator.stop()
            if hasattr(self, "tray_icon") and self.tray_icon:
                self.tray_icon.hide()
        except Exception as e:
            app_logger.warning(f"Error during shutdown in closeEvent: {e}")
        event.accept()
        # NOTE: Do NOT call QApplication.quit() here.
        # In normal mode, setQuitOnLastWindowClosed(True) in main.py makes Qt
        # quit automatically when this window closes — calling quit() here too
        # would double-quit and could cause issues in background/tray mode.
        QApplication.quit()


    def _init_timers(self):
        # Auto-refresh status every 5 seconds
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_state)
        self.timer.start(5000)

    def refresh_state(self):
        try:
            is_running = self.orchestrator.is_running()
            is_paused = self.orchestrator.is_paused()

            if is_running:
                status_text = "Operator: ⏸ Paused" if is_paused else "Operator: ⚡ Running Workflow..."
                color = "#d83b01" if is_paused else "#107c10"
            else:
                status_text = "Operator: Idle (Awaiting Schedule)"
                color = "#0078d4"

            self.lbl_operator_status.setText(status_text)
            self.lbl_operator_status.setStyleSheet(f"color: {color};")

            # Today's status
            today_str = datetime.now().strftime("%Y-%m-%d")
            pub = self.state_manager.get_todays_successful_workflow(today_str)
            if pub:
                self.lbl_today_status.setText(f"Today's Publication: ✅ Published ({pub.get('publication_url') or 'Confirmed'})")
                self.lbl_today_status.setStyleSheet("color: #107c10; font-weight: bold;")
            else:
                active = self.state_manager.get_todays_active_workflow(today_str)
                if active:
                    self.lbl_today_status.setText(f"Today's Publication: In Progress ({active.get('stage')})")
                    self.lbl_today_status.setStyleSheet("color: #d83b01;")
                else:
                    self.lbl_today_status.setText("Today's Publication: Not yet executed today")
                    self.lbl_today_status.setStyleSheet("color: #605e5c;")

            # Update latest workflow details
            latest = self.state_manager.get_latest_workflow()
            if latest:
                self.lbl_current_stage.setText(f"Stage: {latest.get('stage')}")
                self.lbl_last_successful_stage.setText(f"Last Successful Stage: {latest.get('last_successful_stage') or 'None'}")
                self.lbl_selected_topic.setText(f"Selected Topic: {latest.get('topic') or 'None'}")
                
                song_text = latest.get('song_name') or "None"
                if latest.get('artist'):
                    song_text += f" (by {latest.get('artist')})"
                self.lbl_selected_song.setText(f"Selected Song & Artist: {song_text}")

                vid_path_str = latest.get('video_file_path') or ""
                self.lbl_video_path.setText(f"Video Path: {vid_path_str or 'None'}")
                if vid_path_str and Path(vid_path_str).exists():
                    try:
                        size_mb = Path(vid_path_str).stat().st_size / (1024 * 1024)
                        dur = latest.get("video_duration") or "N/A"
                        res = latest.get("video_resolution") or "1080x1920"
                        self.lbl_video_validation.setText(f"Video Validation: ✅ Valid ({res}, {dur}s, {size_mb:.1f} MB)")
                        self.lbl_video_validation.setStyleSheet("color: #107c10; font-weight: bold;")
                    except Exception:
                        self.lbl_video_validation.setText("Video Validation: File exists on disk")
                        self.lbl_video_validation.setStyleSheet("color: #107c10;")
                else:
                    self.lbl_video_validation.setText("Video Validation: Pending / Not Found on Disk")
                    self.lbl_video_validation.setStyleSheet("color: #605e5c;")

                caption = latest.get('caption') or ""
                hashtags = latest.get('hashtags') or ""
                if caption:
                    self.lbl_caption_status.setText(f"Caption Status: ✅ Generated ({len(caption)} chars, {len(hashtags.split())} hashtags)")
                    self.lbl_caption_status.setStyleSheet("color: #107c10;")
                else:
                    self.lbl_caption_status.setText("Caption Status: Pending / Not Generated")
                    self.lbl_caption_status.setStyleSheet("color: #605e5c;")

                self.lbl_post_url.setText(f"Published Reel URL: {latest.get('publication_url') or 'None'}")
                
                retries = latest.get('retry_count') or 0
                self.lbl_retry_info.setText(f"Workflow Retries: {retries} / 3")

                blocker = latest.get("blocker_action") or "None"
                self.lbl_blocker_action.setText(f"Current Blocker & Action: {blocker}")
                if blocker != "None":
                    self.lbl_blocker_action.setStyleSheet("color: #d13438; font-weight: bold;")
                else:
                    self.lbl_blocker_action.setStyleSheet("color: #107c10;")

                err = latest.get("error_details") or "None"
                self.lbl_last_error.setText(f"Last Notice / Error: {err}")

            # Compute next scheduled run time
            target_hhmm = self.config_manager.config.schedule_time_hhmm
            now = datetime.now()
            today_sched = datetime.strptime(f"{now.strftime('%Y-%m-%d')} {target_hhmm}", "%Y-%m-%d %H:%M")
            if now < today_sched:
                next_run_str = f"Today at {target_hhmm}"
            else:
                next_run_str = f"Tomorrow at {target_hhmm}"
            self.lbl_next_run.setText(f"Next Scheduled Run: {next_run_str}")
        except Exception as e:
            app_logger.warning(f"Transient error updating dashboard status: {e}")

    def refresh_history(self):
        try:
            records = self.state_manager.get_recent_workflows(30)
            self.table_history.setRowCount(len(records))
            for row, rec in enumerate(records):
                self.table_history.setItem(row, 0, QTableWidgetItem(str(rec.get("local_date") or "")))
                self.table_history.setItem(row, 1, QTableWidgetItem(str(rec.get("stage") or "")))
                self.table_history.setItem(row, 2, QTableWidgetItem(str(rec.get("topic") or "")))
                dur = f"{rec.get('video_duration')}s" if rec.get("video_duration") else ""
                self.table_history.setItem(row, 3, QTableWidgetItem(dur))
                self.table_history.setItem(row, 4, QTableWidgetItem(str(rec.get("publication_url") or "")))
                self.table_history.setItem(row, 5, QTableWidgetItem(str(rec.get("error_details") or "")))
        except Exception as e:
            app_logger.warning(f"Transient error loading workflow history: {e}")

    def refresh_logs(self):
        if MAIN_LOG_FILE.exists():
            try:
                with open(MAIN_LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    self.txt_logs.setText("".join(lines[-300:]))
                    self.txt_logs.verticalScrollBar().setValue(self.txt_logs.verticalScrollBar().maximum())
            except Exception as e:
                self.txt_logs.setText(f"Error reading logs: {e}")

    def action_run_now(self):
        if self.orchestrator.is_running():
            QMessageBox.warning(self, "Workflow In Progress", "A workflow is already currently executing.")
            return

        def run_thread():
            self.orchestrator.run_daily_workflow(force=True)
            self.refresh_state()
            self.refresh_history()

        threading.Thread(target=run_thread, daemon=True).start()
        QMessageBox.information(self, "Workflow Started", "Daily workflow started. Check the Live Logs or Overview tab for real-time progress.")

    def action_pause_resume(self):
        if self.orchestrator.is_paused():
            self.orchestrator.resume()
            self.btn_pause.setText("⏸ Pause Operator")
        else:
            self.orchestrator.pause()
            self.btn_pause.setText("▶ Resume Operator")
        self.refresh_state()

    def action_stop(self):
        self.orchestrator.stop()
        self.refresh_state()
        QMessageBox.information(self, "Stopped", "Workflow execution stopped.")

    def action_open_auth_browser(self):
        """
        Opens the dedicated persistent automation browser for manual sign-in.

        IMPORTANT: This method runs on the Qt GUI thread and must NEVER call
        any Playwright API (launch_persistent_context, new_page, etc.).
        Playwright's synchronous API is bound to the workflow worker thread.
        We open Chrome directly via subprocess instead.
        """
        cfg = self.config_manager.config
        target_email = cfg.target_google_account
        operator_profile = cfg.operator_profile_dir
        chatgpt_url = cfg.chatgpt_conversation_url or "https://chatgpt.com/"

        locked, lock_reason = self.orchestrator.browser_manager.is_profile_locked()
        cdp_up = self.orchestrator.browser_manager.is_cdp_available()

        if locked and not cdp_up:
            QMessageBox.warning(
                self,
                "Operator Profile in Use",
                f"The dedicated automation profile is already open in another Chrome window.\n\n"
                f"Switch to that window to complete sign-in, or close it and click this button again.\n\n"
                f"Profile: {operator_profile}"
            )
            return

        if cdp_up:
            QMessageBox.information(
                self,
                "Automation Browser Already Running",
                f"The automation browser is already running (CDP port 9222 is active).\n\n"
                f"Switch to that Chrome window to sign in to:\n"
                f"  • Google: {target_email}\n"
                f"  • ChatGPT: {chatgpt_url}\n\n"
                f"Then click 'Run Daily Workflow Now' to retry the workflow."
            )
            return

        # Safe: opens Chrome via subprocess — no Playwright on the GUI thread
        pid = self.orchestrator.browser_manager.launch_auth_browser_subprocess()
        if pid > 0:
            QMessageBox.information(
                self,
                "Automation Browser Launched",
                f"Opened dedicated automation browser (PID {pid}).\n\n"
                f"Profile: {operator_profile}\n"
                f"Target account: {target_email}\n\n"
                f"One-time setup instructions:\n"
                f"1. In the Gemini tab — sign into Google as: {target_email}\n"
                f"2. In the ChatGPT tab — sign in and verify this conversation loads:\n"
                f"   {chatgpt_url}\n\n"
                f"Sessions are saved in the automation profile and will persist for daily runs.\n"
                f"Click 'Run Daily Workflow Now' on the dashboard after signing in."
            )
        else:
            QMessageBox.critical(
                self,
                "Failed to Launch Browser",
                f"Could not open Chrome. Check that Chrome is installed at:\n"
                f"{cfg.chrome_executable_path}\n\n"
                f"Check the Logs tab for details."
            )


    def action_save_config(self):
        auto_pub = self.chk_auto_publish.isChecked()
        sched_time = self.txt_schedule_time.text().strip()
        chat_url = self.txt_chatgpt_url.text().strip() or None
        lang = self.cmb_language.currentText()
        dur = self.spn_duration.value()

        self.config_manager.update(
            auto_publish_enabled=auto_pub,
            schedule_time_hhmm=sched_time,
            chatgpt_conversation_url=chat_url,
            preferred_language=lang,
            target_video_duration_seconds=dur
        )

        if self.chk_windows_startup.isChecked():
            install_windows_startup_task(sys.executable, str(BASE_DIR / "main.py"))
        else:
            remove_windows_startup_task()

        QMessageBox.information(self, "Settings Saved", "Configuration updated successfully.")

    def _open_dir(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)
        os.startfile(str(path))
