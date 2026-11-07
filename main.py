import sys
import os
import traceback
import argparse
from datetime import datetime
from pathlib import Path

# ── Force project root regardless of how or where process was launched ────────
PROJECT_ROOT = Path(__file__).resolve().parent
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── DPI-awareness MUST be set before QApplication is instantiated ────────────
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QTimer

# Set HighDPI pixmap attribute before any QApplication instance exists
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

from app.logger import app_logger, LOGS_DIR
from app.config_manager import ConfigurationManager, DATA_DIR, DOWNLOADS_DIR, READY_TO_POST_DIR, POSTED_DIR, HISTORY_DIR
from app.orchestrator import WorkflowOrchestrator
from app.scheduler import SchedulerService
from app.dashboard import DashboardWindow
from app.windows_startup import is_user_session_available

import ctypes

def acquire_single_instance_lock():
    """Acquires a named Windows mutex to prevent duplicate application instances."""
    if os.name != "nt":
        return None
    try:
        kernel32 = ctypes.windll.kernel32
        MUTEX_NAME = "Local\\AI_Instagram_Reel_Operator_SingleInstance"
        mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
        last_error = kernel32.GetLastError()
        ERROR_ALREADY_EXISTS = 183
        if last_error == ERROR_ALREADY_EXISTS:
            if mutex:
                kernel32.CloseHandle(mutex)
            return None
        return mutex
    except Exception as e:
        app_logger.warning(f"Single-instance mutex check notice: {e}")
        return None

def release_single_instance_lock(mutex):
    if mutex and os.name == "nt":
        try:
            ctypes.windll.kernel32.CloseHandle(mutex)
        except Exception:
            pass

def main():
    parser = argparse.ArgumentParser(description="AI Instagram Reel Operator")
    parser.add_argument(
        "--background", action="store_true",
        help="Start minimized in background / tray without opening the main dashboard window"
    )
    parser.add_argument(
        "--run-now", action="store_true",
        help="Execute the daily workflow immediately and exit (headless/CLI mode)"
    )
    parser.add_argument(
        "--publish-now", action="store_true",
        help="Publish the existing validated ready-to-post Reel to Instagram immediately (headless/CLI mode)"
    )
    args = parser.parse_args()

    mode = (
        "Background Tray" if args.background
        else "CLI Publish Now" if args.publish_now
        else "CLI Direct Run" if args.run_now
        else "Standard GUI Dashboard"
    )

    # ── Single-Instance Protection ───────────────────────────────────────────
    mutex = acquire_single_instance_lock()
    if mutex is None and os.name == "nt":
        # Another instance is already running
        app_logger.info(
            f"Another instance of AI Instagram Reel Operator is already running. "
            f"Exiting duplicate process (Mode: {mode}, PID: {os.getpid()})."
        )
        if not args.background and not args.run_now and not args.publish_now:
            # If user explicitly launched GUI, attempt to inform before exiting
            try:
                temp_app = QApplication.instance() or QApplication(sys.argv)
                QMessageBox.information(
                    None,
                    "Operator Already Running",
                    "AI Instagram Reel Operator is already running.\nCheck your system tray or Task Manager."
                )
            except Exception:
                pass
        sys.exit(0)

    # Record PID
    pid_file = DATA_DIR / "operator.pid"
    try:
        pid_file.parent.mkdir(parents=True, exist_ok=True)
        pid_file.write_text(f"{os.getpid()}|{datetime.now().isoformat()}|{mode}")
    except Exception:
        pass

    # ── Diagnostic path logging at startup ───────────────────────────────────
    app_logger.info("=" * 60)
    app_logger.info("AI Instagram Reel Operator — Application Starting")
    app_logger.info(f"Project Root (Resolved) : {PROJECT_ROOT}")
    app_logger.info(f"Working Directory       : {Path.cwd()}")
    app_logger.info(f"Python Executable       : {sys.executable}")
    app_logger.info(f"Process ID (PID)        : {os.getpid()}")
    app_logger.info(f"Execution Mode          : {mode}")
    app_logger.info(f"Interactive Session     : {is_user_session_available()}")
    app_logger.info(f"Config File Path        : {PROJECT_ROOT / 'config' / 'settings.json'}")
    app_logger.info(f"SQLite Database Path    : {DATA_DIR / 'operator.db'}")
    app_logger.info(f"Logs Directory          : {LOGS_DIR}")
    app_logger.info(f"Downloads Directory     : {DOWNLOADS_DIR}")
    app_logger.info(f"Ready to Post Directory : {READY_TO_POST_DIR}")
    app_logger.info(f"Posted Archive Directory: {POSTED_DIR}")
    app_logger.info(f"History Directory       : {HISTORY_DIR}")
    app_logger.info(f"Chrome Profile Directory: {DATA_DIR / 'operator_chrome_profile'}")
    app_logger.info("=" * 60)

    try:
        # ── Step 1: Initialize core services ─────────────────────────────────
        try:
            config_mgr = ConfigurationManager()
            orchestrator = WorkflowOrchestrator(config_mgr)
            scheduler = SchedulerService(orchestrator)
        except Exception as e:
            tb = traceback.format_exc()
            app_logger.critical(f"Fatal error during core service initialization: {e}\n{tb}")
            print(f"FATAL ERROR during startup: {e}\n{tb}", file=sys.stderr)
            sys.exit(1)

        # ── Step 2A: CLI --publish-now (headless publishing of existing video) ───
        if args.publish_now:
            app_logger.info("CLI --publish-now flag provided. Publishing existing ready-to-post Reel...")
            try:
                res = orchestrator.publish_existing_reel()
                app_logger.info(f"Publish execution finished: {res}")
                sys.exit(0 if res.get("success") else 1)
            except Exception as e:
                app_logger.error(f"Error during --publish-now: {e}", exc_info=True)
                sys.exit(1)

        # ── Step 2B: CLI --run-now (headless) ────────────────────────────────
        if args.run_now:
            app_logger.info("CLI --run-now flag provided. Starting headless execution...")
            try:
                res = orchestrator.run_daily_workflow(force=True)
                app_logger.info(f"Execution finished: {res}")
                sys.exit(0 if res.get("success") else 1)
            except Exception as e:
                app_logger.error(f"Error during --run-now: {e}", exc_info=True)
                sys.exit(1)

        # ── Step 3: Create Qt GUI application ────────────────────────────────
        app_logger.info("Creating Qt GUI Application...")
        app = QApplication.instance() or QApplication(sys.argv)
        app.setApplicationName("AI Instagram Reel Operator")

        # ── CRITICAL FIX: setQuitOnLastWindowClosed ───────────────────────────
        if args.background:
            app.setQuitOnLastWindowClosed(False)
        else:
            app.setQuitOnLastWindowClosed(True)

        # ── Step 4: Construct Dashboard and show it immediately ───────────────
        try:
            app_logger.info("Constructing Dashboard window...")
            window = DashboardWindow(orchestrator, scheduler)
            app_logger.info("Dashboard window constructed successfully.")

            if not args.background:
                app_logger.info("Displaying Dashboard window...")
                window.show()
                window.raise_()
                window.activateWindow()
                geo = window.geometry()
                app_logger.info(
                    f"Dashboard.show() called — "
                    f"isVisible={window.isVisible()}, isMinimized={window.isMinimized()}, "
                    f"geometry=({geo.x()},{geo.y()},{geo.width()}x{geo.height()})"
                )

                def _force_visible():
                    if not window.isVisible() or window.isMinimized():
                        app_logger.info("Deferred show: window not visible — calling showNormal().")
                        window.showNormal()
                    window.raise_()
                    window.activateWindow()
                    geo2 = window.geometry()
                    app_logger.info(
                        f"Deferred show complete — "
                        f"isVisible={window.isVisible()}, isMinimized={window.isMinimized()}, "
                        f"geometry=({geo2.x()},{geo2.y()},{geo2.width()}x{geo2.height()})"
                    )

                QTimer.singleShot(0, _force_visible)

            else:
                app_logger.info("--background mode: running in Windows notification area / system tray.")
                if hasattr(window, "tray_icon") and window.tray_icon:
                    window.tray_icon.showMessage(
                        "AI Instagram Reel Operator",
                        "Operator started in background. Click the tray icon to open the dashboard.",
                        window.tray_icon.MessageIcon.Information,
                        3000,
                    )

        except Exception as e:
            tb = traceback.format_exc()
            app_logger.critical(f"Fatal error displaying Dashboard UI: {e}\n{tb}")
            try:
                QMessageBox.critical(
                    None, "Startup Error",
                    f"Failed to initialize Dashboard:\n{e}\n\nCheck logs at:\n{LOGS_DIR}"
                )
            except Exception:
                pass
            sys.exit(1)

        # ── Step 5: Start background scheduler AFTER the event loop is running ────
        def start_background_services():
            try:
                app_logger.info("Starting background scheduler and automation workers...")
                scheduler.start()
                app_logger.info("Scheduler worker startup complete.")
            except Exception as e:
                app_logger.error(f"Error starting background scheduler: {e}", exc_info=True)

        QTimer.singleShot(250, start_background_services)

        # ── Step 6: Enter Qt main event loop ─────────────────────────────────
        app_logger.info("Entering GUI event loop (app.exec()).")
        exit_code = app.exec()
        app_logger.info(f"GUI event loop exited with code {exit_code}. Shutting down cleanly.")
        sys.exit(exit_code)

    finally:
        # Clean up lock & PID file
        try:
            if pid_file.exists():
                pid_file.unlink()
        except Exception:
            pass
        release_single_instance_lock(mutex)

if __name__ == "__main__":
    main()
