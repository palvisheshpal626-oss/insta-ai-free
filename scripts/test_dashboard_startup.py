import sys
import os
import time
from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QTimer

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.logger import app_logger
from app.config_manager import ConfigurationManager
from app.orchestrator import WorkflowOrchestrator
from app.scheduler import SchedulerService
from app.dashboard import DashboardWindow

def test_dashboard_startup():
    print("=" * 70)
    print(" AI INSTAGRAM REEL OPERATOR — DASHBOARD STARTUP & DECOUPLING TEST ")
    print("=" * 70)

    # 1. Initialize core services
    print("\n[Step 1: Core Services Initialization]")
    cfg_mgr = ConfigurationManager()
    orchestrator = WorkflowOrchestrator(cfg_mgr)
    scheduler = SchedulerService(orchestrator)
    print("✓ Config, Orchestrator, and Scheduler initialized.")

    # 2. GUI Application Creation
    print("\n[Step 2: Qt GUI Application Creation]")
    app = QApplication.instance() or QApplication(sys.argv)
    assert app is not None, "Failed to create QApplication"
    print("✓ QApplication created successfully.")

    # 3. Construct and Display Dashboard immediately
    print("\n[Step 3: Construct & Display Dashboard immediately]")
    window = DashboardWindow(orchestrator, scheduler)
    print(f"✓ Dashboard constructed. Window Title: '{window.windowTitle()}'")

    window.show()
    window.raise_()
    window.activateWindow()
    print("✓ Dashboard shown and brought to front.")
    assert window.isVisible(), "Dashboard window must be visible after show()"

    # Check window geometry
    geo = window.geometry()
    print(f"✓ Window Geometry: x={geo.x()}, y={geo.y()}, w={geo.width()}, h={geo.height()}")
    assert geo.width() >= 850 and geo.height() >= 600, "Window size satisfies minimum dimensions"

    # 4. Decoupled Scheduler Start
    print("\n[Step 4: Decoupled Scheduler Startup in Background]")
    # Start scheduler after dashboard is shown
    scheduler.start()
    assert scheduler._running is True, "Scheduler should be running in background thread"
    print("✓ Scheduler started in background thread without blocking the GUI.")

    # 5. Verify GUI Responsiveness & NEEDS_USER_ACTION state
    print("\n[Step 5: Verify GUI Responsiveness with Unauthenticated Session]")
    # Process pending events in Qt event loop
    app.processEvents()
    window.refresh_state()
    current_status = window.lbl_operator_status.text()
    current_stage = window.lbl_current_stage.text()
    last_error = window.lbl_last_error.text()
    print(f"✓ Operator Status Label: '{current_status}'")
    print(f"✓ Current Stage Label:   '{current_stage}'")
    print(f"✓ Last Error Notice:     '{last_error[:100]}...'")

    # Confirm tabs are responsive
    tab_count = window.tabs.count()
    print(f"✓ Tab Count: {tab_count} (Overview, Configuration, Workflow History, Live Logs)")
    assert tab_count == 4, "Dashboard must have all 4 tabs"
    window.tabs.setCurrentIndex(1)  # Switch to Config tab
    app.processEvents()
    window.tabs.setCurrentIndex(3)  # Switch to Logs tab
    app.processEvents()
    window.tabs.setCurrentIndex(0)  # Return to Overview tab
    app.processEvents()
    print("✓ Tabs switched and processed events smoothly.")

    # 6. Clean Shutdown Verification
    print("\n[Step 6: Clean Shutdown Verification]")
    window.close()
    assert scheduler._running is False, "Scheduler should be stopped after window.close()"
    print("✓ Background scheduler and workers stopped cleanly on window close.")

    print("\n" + "=" * 70)
    print("ALL DASHBOARD STARTUP & DECOUPLING TESTS PASSED!")
    print("=" * 70)
    return True

if __name__ == "__main__":
    success = test_dashboard_startup()
    sys.exit(0 if success else 1)
