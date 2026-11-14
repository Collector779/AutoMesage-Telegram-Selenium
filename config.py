"""Paths, defaults and persistent settings (Windows + Debian/Linux)."""
import json
import os
import shutil
import sys
from pathlib import Path

APP_NAME = "TelegramAutoMessage"
APP_VERSION = "1.0.1"
# PyInstaller (.exe) unpacks bundled files to sys._MEIPASS; from source / .deb they sit next to this file
ASSETS_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)) / "assets"
TELEGRAM_WEB_URL = "https://web.telegram.org/k/"

# Leave empty to auto-detect Chrome/Chromium; set a path to force a specific binary.
CHROME_BINARY = ""

DEFAULT_SETTINGS = {
    "message": "Hello from Python!",
    "first_delay_min_s": 60,
    "first_delay_max_s": 300,
    "interval_min_min": 70,
    "interval_max_min": 164,
    "retry_after_error_min": 30,
    "headless": True,
    "theme": "tokyo-night-dark",
    # type: http | https | socks5 | socks4. Login/password work for http/https only (Chrome limitation).
    "proxy": {"enabled": False, "type": "http", "host": "", "port": "", "username": "", "password": ""},
    "mode": "text",     # "text" = own message, "forward" = forward a chosen message
    "forward": {},      # {from_peer_id, from_name, mid, preview, date, drop_author}
    "show_unavailable": False,
    "selected": [],     # target keys: "peer_id" or "peer_id_thread_id"
    "scan": {},         # last scan result: {groups: [...], privates: [...], my_id}
}


def app_data_dir() -> Path:
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    path = base / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def profile_dir() -> Path:
    """Chrome profile kept between runs, so the Telegram login survives restarts."""
    return app_data_dir() / "chrome-profile"


def settings_path() -> Path:
    return app_data_dir() / "settings.json"


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(settings_path(), "r", encoding="utf-8") as fh:
            settings.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings: dict) -> None:
    tmp = settings_path().with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(settings, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, settings_path())


def find_chrome_binary():
    """Return a Chrome/Chromium executable path, or None to let Selenium Manager decide."""
    if CHROME_BINARY and Path(CHROME_BINARY).exists():
        return CHROME_BINARY
    if sys.platform.startswith("win"):
        candidates = [
            Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Google/Chrome/Application/chrome.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        ]
        for cand in candidates:
            if cand.exists():
                return str(cand)
        return None
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            return found
    return None


def find_chromedriver_for(binary):
    """Debian's chromium needs its matching distro chromedriver (package chromium-driver)."""
    if binary and "chromium" in Path(binary).name:
        for cand in ("/usr/bin/chromedriver", "/usr/lib/chromium/chromedriver"):
            if Path(cand).exists():
                return cand
    return None
