"""Build dist/TelegramAutoMessage-<version>-windows.exe (single file, no console) with PyInstaller.

Usage (Windows):  python packaging/build_exe.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from config import APP_VERSION  # noqa: E402

DIST = ROOT / "dist"
WORK = ROOT / "build" / "pyinstaller"
NAME = f"TelegramAutoMessage-{APP_VERSION}-windows"


def main():
    if sys.platform != "win32":
        sys.exit("Plik .exe buduje się na Windowsie.")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "-r",
                           str(ROOT / "requirements.txt"), "pyinstaller>=6.10"])
    shutil.rmtree(WORK, ignore_errors=True)
    sep = ";"
    args = [
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--onefile", "--windowed",
        "--name", NAME,
        "--icon", str(ROOT / "assets" / "icon.ico"),
        "--add-data", f"{ROOT / 'assets'}{sep}assets",
        "--collect-all", "ttkbootstrap",   # themes, images, locales
        "--collect-all", "selenium",       # includes selenium-manager.exe (driver + browser download)
        "--distpath", str(DIST),
        "--workpath", str(WORK),
        "--specpath", str(WORK),
        str(ROOT / "main.py"),
    ]
    subprocess.check_call(args, cwd=ROOT)
    exe = DIST / f"{NAME}.exe"
    print(f"\nGotowe: {exe}  ({exe.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
