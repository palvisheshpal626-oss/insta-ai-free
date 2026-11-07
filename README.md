# AI Instagram Reel Operator

A robust, production-ready Windows desktop automation system that automates the daily creation and publishing workflow for Instagram Reels using existing authenticated browser sessions.

---

## 📌 Architecture & Design Highlights

1. **Persistent Session & Browser Management**:
   - Reuses the user's existing Chrome session stored in a dedicated persistent browser profile (`data/browser_profile`).
   - Operates in the background without repeatedly opening intrusive windows or stealing keyboard focus.
   - Preserves user logins across reboots without saving raw credentials in plain-text.

2. **Dedicated ChatGPT Conversation Reuse**:
   - Strictly opens and reuses a single dedicated conversation URL designated during setup.
   - Enforces 10-second script constraints (15–22 spoken words, scene breakdown, hook, and on-screen text).
   - If ChatGPT returns malformed JSON, requests corrections inside the **same** conversation rather than spawning new threads.

3. **Fresh Daily Gemini Video Generation**:
   - Creates a **brand new conversation every calendar day** on Google Gemini.
   - Submits structured vertical 9:16 video generation prompts.
   - Accurately checks for native video generation capabilities (Veo / Imagen Video) and halts gracefully if the account lacks video generation permissions, avoiding any false success claims.

4. **Media Validation & Trimming**:
   - Real media validation via `ffprobe` and `ffmpeg` (with automated fallback parser).
   - Enforces duration limits and trims oversized videos to 10 seconds.
   - Sanitized file naming convention: `YYYY-MM-DD_<topic_slug>_reel.mp4`.

5. **Instagram Publishing & Duplicate Prevention**:
   - Uploads to the user's authenticated Instagram account via browser automation or official Graph API.
   - Confirms publication permalink / dialog before marking complete.
   - Enforces a 30-day topic history and duplicate run block in SQLite.

6. **Windows Startup & System Tray**:
   - Windows Task Scheduler integration (`schtasks /Create /SC ONLOGON`) triggers missed workflows after user logon.
   - PySide6 graphical dashboard with system tray minimization, live status, manual "Run Now", "Pause", and direct directory shortcuts.

---

## 📂 Directory Structure

```
Instagram-AI-Operator/
├── app/
│   ├── browser_manager.py      # Persistent Playwright Chrome session management
│   ├── caption_generator.py    # Grounded caption & hashtag generator
│   ├── chatgpt_client.py       # Dedicated ChatGPT conversation automation
│   ├── config_manager.py       # JSON configuration & defaults
│   ├── dashboard.py            # PySide6 desktop GUI & System Tray
│   ├── gemini_client.py        # Daily Gemini video generator
│   ├── instagram_publisher.py  # Instagram upload & confirmation
│   ├── logger.py               # Rotating file & console logging
│   ├── orchestrator.py         # 13-stage master workflow state machine
│   ├── scheduler.py            # Daily timing & missed work triggers
│   ├── state_manager.py        # SQLite persistent database
│   ├── video_manager.py        # Media validation, ffprobe/ffmpeg trimmer
│   └── windows_startup.py      # Windows Task Scheduler registration
├── config/
│   └── settings.json           # Active configuration
├── data/
│   ├── browser_profile/        # Persistent browser cookies & auth
│   └── operator.db             # SQLite workflow database
├── downloads/                  # Raw downloaded media from Gemini
├── ready_to_post/              # Validated 10s reels + metadata JSON
├── posted/                     # Published reels archive
├── history/                    # Accepted scripts & prompt archives
├── logs/
│   └── operator.log            # Rotating application logs
├── scripts/
│   ├── setup_startup.py        # One-click Windows startup installer
│   └── test_diagnostics.py     # Component pre-flight verification script
├── main.py                     # Primary GUI & background entry point
└── README.md
```

---

## 🚀 Quick Start Guide

### 1. Verify Prerequisites
Run the built-in diagnostic test to verify your environment:
```powershell
python scripts/test_diagnostics.py
```

### 2. Initial Browser Authentication
To authorize your accounts (ChatGPT, Google Gemini, Instagram) in the operator's dedicated profile:
1. Launch the operator dashboard:
   ```powershell
   python main.py
   ```
2. In the **Overview & Control** tab, click **"🔑 Open Authentication Browser"**.
3. In the opened browser window:
   - Log into **ChatGPT** and open/create your dedicated Reel conversation. Copy its URL.
   - Log into **Google Gemini** (`https://gemini.google.com/app`).
   - Log into **Instagram** (`https://www.instagram.com/`).
4. Close the browser window. The session tokens and cookies are securely preserved inside `data/browser_profile`.

### 3. Configure Settings
1. In the **Configuration** tab of the dashboard:
   - Paste your **Dedicated ChatGPT Conversation URL**.
   - Set your **Daily Run Time** (default: `09:00`).
   - Choose whether **Automatic Instagram Publication** is enabled (keep unchecked initially to preview reels before publishing).
   - Ensure **Launch Automatically at Windows Login** is checked.
2. Click **Save Configuration**.

### 4. Background Startup
To register the Windows Task Scheduler startup task:
```powershell
python scripts/setup_startup.py
```
This ensures the operator starts automatically in the background whenever you log into Windows.
