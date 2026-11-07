import os
import sys
import subprocess
import ctypes
from pathlib import Path
from .logger import app_logger

TASK_NAME = "AI_Instagram_Reel_Operator"

def is_user_session_available() -> bool:
    """Checks whether an interactive Windows desktop session is active and available.
    
    Prevents interactive browser automation before user logon or in non-interactive sessions.
    """
    if os.name != "nt":
        return True
    try:
        user32 = ctypes.windll.user32
        # Check process window station
        hwinsta = user32.GetProcessWindowStation()
        if not hwinsta:
            return False
        # Try to open the input desktop (fails if workstation is locked or pre-logon)
        DESKTOP_SWITCHDESKTOP = 0x0100
        hdesk = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
        if hdesk:
            user32.CloseDesktop(hdesk)
            return True
        return False
    except Exception as e:
        app_logger.debug(f"User session check notice: {e}")
        return True

def generate_startup_vbscript(python_exe: str, script_path: str) -> str:
    """Generates the VBScript content ensuring project directory is set as CurrentDirectory."""
    project_dir = Path(script_path).resolve().parent
    return (
        'Set WshShell = CreateObject("WScript.Shell")\r\n'
        f'WshShell.CurrentDirectory = "{project_dir}"\r\n'
        f'WshShell.Run """{python_exe}"" ""{script_path}"" --background", 0, False\r\n'
    )

def install_windows_startup_task(python_exe: str, script_path: str) -> bool:
    """Registers auto-startup when the Windows user logs in.
    
    Guarantees:
    - Resolves project root directory and ensures the process starts in that directory.
    - Sets up Startup folder VBS launcher (always available without admin privileges).
    - Attempts Task Scheduler registration as complementary option.
    """
    project_dir = Path(script_path).resolve().parent
    installed = False

    # Method 1: User Startup Folder (Guaranteed to work without UAC elevation)
    try:
        startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        if startup_dir.exists():
            vbs_script = startup_dir / f"{TASK_NAME}.vbs"
            # Explicitly set CurrentDirectory so running from System32 is impossible
            vbs_content = generate_startup_vbscript(python_exe, script_path)
            with open(vbs_script, "w", encoding="utf-8") as f:
                f.write(vbs_content)
            app_logger.info(f"Registered Windows Startup Folder launcher: {vbs_script} (Working dir: {project_dir})")
            installed = True
    except Exception as e:
        app_logger.warning(f"Failed creating Startup Folder launcher: {e}")

    # Method 2: Try schtasks with ONLOGON as well
    try:
        # Wrap in a cmd command that cd's to project directory before running python
        tr_command = f'cmd.exe /c "cd /d ""{project_dir}"" && ""{python_exe}"" ""{script_path}"" --background"'
        cmd = [
            "schtasks", "/Create",
            "/TN", TASK_NAME,
            "/TR", tr_command,
            "/SC", "ONLOGON",
            "/F"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            app_logger.info(f"Windows Task Scheduler entry '{TASK_NAME}' registered successfully.")
            installed = True
        else:
            app_logger.debug(f"schtasks non-elevated notice: {res.stderr.strip()}")
    except Exception as e:
        app_logger.debug(f"schtasks invocation notice: {e}")

    return installed

def remove_windows_startup_task() -> bool:
    """Removes both the Startup folder launcher and any Task Scheduler task."""
    removed = False
    # 1. Remove from Startup folder
    try:
        startup_dir = Path(os.environ.get("APPDATA", "")) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        vbs_script = startup_dir / f"{TASK_NAME}.vbs"
        if vbs_script.exists():
            vbs_script.unlink()
            app_logger.info(f"Removed Startup folder script: {vbs_script}")
            removed = True
    except Exception as e:
        app_logger.warning(f"Error removing Startup folder script: {e}")

    # 2. Remove schtasks
    try:
        cmd = ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            app_logger.info(f"Windows Task Scheduler entry '{TASK_NAME}' removed.")
            removed = True
    except Exception as e:
        app_logger.debug(f"Error deleting schtasks: {e}")

    return removed
