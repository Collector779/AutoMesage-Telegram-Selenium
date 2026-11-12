@echo off
cd /d "%~dp0"
python -c "import selenium, ttkbootstrap" 2>nul || call install.bat
start "" pythonw main.py
