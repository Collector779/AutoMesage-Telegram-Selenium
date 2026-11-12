"""Telegram AutoMessage: start the window application."""
import sys


def main():
    missing = []
    for module, hint in (("tkinter", "python3-tk"), ("selenium", "selenium"), ("ttkbootstrap", "ttkbootstrap")):
        try:
            __import__(module)
        except ImportError:
            missing.append(hint)
    if missing:
        script = "install.bat" if sys.platform.startswith("win") else "bash install.sh"
        sys.exit(f"Brakuje: {', '.join(missing)}.\nUruchom instalator: {script}")
    from gui import run
    run()


if __name__ == "__main__":
    main()
