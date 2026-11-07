"""
scripts/diagnose_window_visibility.py
─────────────────────────────────────
Real-world diagnostic that checks whether the AI Instagram Reel Operator
dashboard window is actually visible on the Windows desktop.

This script works WITHOUT launching a new QApplication — it uses Windows
API (ctypes) to enumerate all top-level windows and find our dashboard.

Run this WHILE python main.py is running (in a separate terminal):
    python scripts/diagnose_window_visibility.py
"""

import sys
import ctypes
import ctypes.wintypes
import subprocess
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ── Windows API definitions ────────────────────────────────────────────────
user32 = ctypes.windll.user32
EnumWindows = user32.EnumWindows
EnumWindows.restype = ctypes.c_bool

GetWindowTextW = user32.GetWindowTextW
GetWindowTextLengthW = user32.GetWindowTextLengthW
IsWindowVisible = user32.IsWindowVisible
IsIconic = user32.IsIconic          # IsIconic = minimized
GetWindowRect = user32.GetWindowRect

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)


def get_window_title(hwnd) -> str:
    length = GetWindowTextLengthW(hwnd)
    if length == 0:
        return ""
    buf = ctypes.create_unicode_buffer(length + 1)
    GetWindowTextW(hwnd, buf, length + 1)
    return buf.value


def get_window_rect(hwnd):
    rect = ctypes.wintypes.RECT()
    if GetWindowRect(hwnd, ctypes.byref(rect)):
        return rect.left, rect.top, rect.right, rect.bottom
    return None


def find_operator_windows():
    results = []
    TARGET = "AI Instagram Reel Operator"

    def callback(hwnd, lParam):
        title = get_window_title(hwnd)
        if TARGET in title:
            visible = bool(IsWindowVisible(hwnd))
            minimized = bool(IsIconic(hwnd))
            rect = get_window_rect(hwnd)
            width = (rect[2] - rect[0]) if rect else 0
            height = (rect[3] - rect[1]) if rect else 0
            results.append({
                "hwnd": hwnd,
                "title": title,
                "visible": visible,
                "minimized": minimized,
                "rect": rect,
                "width": width,
                "height": height,
            })
        return True

    EnumWindows(WNDENUMPROC(callback), 0)
    return results


def find_python_main_processes():
    """Find python.exe processes running main.py."""
    try:
        result = subprocess.run(
            ["tasklist", "/fi", "imagename eq python.exe", "/fo", "csv"],
            capture_output=True, text=True, timeout=5
        )
        pids = []
        for line in result.stdout.splitlines()[1:]:  # skip header
            parts = line.strip('"').split('","')
            if len(parts) >= 2:
                pids.append(parts[1])  # PID is field 1
        return pids
    except Exception as e:
        return [f"ERROR: {e}"]


def main():
    print("=" * 70)
    print(" AI INSTAGRAM REEL OPERATOR — REAL WINDOW VISIBILITY DIAGNOSTIC")
    print("=" * 70)
    print()

    # 1. Check for running python.exe processes
    print("[1/3] Checking for running python.exe processes...")
    pids = find_python_main_processes()
    if pids:
        print(f"  Found {len(pids)} python.exe process(es): PIDs = {', '.join(pids)}")
    else:
        print("  ⚠ No python.exe processes found — main.py is not running.")
    print()

    # 2. Enumerate Windows desktop for our window
    print("[2/3] Scanning Windows desktop for 'AI Instagram Reel Operator' window(s)...")
    windows = find_operator_windows()

    if not windows:
        print("  ✗ NO dashboard window found on the desktop.")
        print("  → main.py is either not running, has crashed, or Qt failed to create a window.")
        print()
        print("  RECOMMENDATION: Run this in a terminal and watch the output:")
        print("    python main.py")
        print("  Then run this diagnostic in a second terminal window.")
    else:
        for w in windows:
            print(f"\n  Window HWND: {w['hwnd']:#010x}")
            print(f"    Title:     {w['title']}")
            print(f"    Visible:   {w['visible']}")
            print(f"    Minimized: {w['minimized']}")
            print(f"    Rect:      left={w['rect'][0]}, top={w['rect'][1]}, right={w['rect'][2]}, bottom={w['rect'][3]}")
            print(f"    Size:      {w['width']} x {w['height']}")

            if not w["visible"]:
                print("    ✗ INVISIBLE — window exists but IsWindowVisible() = False")
                print("      Possible causes: hidden by code, WS_VISIBLE not set, or tray-only mode")
            elif w["minimized"]:
                print("    ⚠ MINIMIZED — window is on the taskbar but not shown on screen")
            elif w["width"] <= 0 or w["height"] <= 0:
                print("    ✗ ZERO-SIZE window — window exists but has no area")
            else:
                # Check if it's off-screen
                left, top, right, bottom = w["rect"]
                # Approximate: primary monitor is typically 0,0 to ~3840x2160
                if right < 0 or bottom < 0 or left > 7680 or top > 4320:
                    print("    ✗ OFF-SCREEN — window is positioned outside any visible monitor area")
                else:
                    print("    ✓ VISIBLE and on-screen — the window should be visible to the user")
    print()

    # 3. Summarise
    print("[3/3] Summary")
    if not windows:
        print("  STATUS: Dashboard window does not exist. main.py may not be running.")
        print("  ACTION: Run 'python main.py' in a terminal and check for errors.")
    elif any(w["visible"] and not w["minimized"] and w["width"] > 0 for w in windows):
        print("  STATUS: ✓ Dashboard window IS visible on screen.")
        print("          If you still cannot see it, it may be behind another window.")
        print("          Look for 'AI Instagram Reel Operator' in your taskbar.")
    else:
        print("  STATUS: ✗ Dashboard window exists but is NOT visible.")
        details = windows[0]
        if details["minimized"]:
            print("  → Window is MINIMIZED. Click its taskbar button or tray icon to restore it.")
        elif not details["visible"]:
            print("  → Window has IsWindowVisible=False. A hide() call may have suppressed it.")
        else:
            print("  → Window has zero or off-screen geometry. Check DPI scaling settings.")
    print()
    print("=" * 70)


if __name__ == "__main__":
    main()
