import sys
import subprocess
from pathlib import Path

# Add project root to sys.path
BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.windows_startup import install_windows_startup_task

def setup_environment():
    base_dir = Path(__file__).resolve().parent.parent
    main_py = base_dir / "main.py"
    python_exe = sys.executable

    print("==================================================")
    print("   AI Instagram Reel Operator - Setup & Startup   ")
    print("==================================================")
    print(f"Base Directory: {base_dir}")
    print(f"Python Executable: {python_exe}")

    # Register Windows Task Scheduler task
    print("\n[1/2] Registering Windows Task Scheduler startup task...")
    ok = install_windows_startup_task(python_exe, str(main_py))
    if ok:
        print("  -> Windows Task Scheduler entry successfully created!")
        print("  -> The Operator will launch automatically whenever you log into Windows.")
    else:
        print("  -> Note: Run terminal as Administrator if Task Scheduler registration was restricted.")

    print("\n[2/2] Setup verification complete.")
    print("To launch the dashboard now, run: python main.py")

if __name__ == "__main__":
    setup_environment()
