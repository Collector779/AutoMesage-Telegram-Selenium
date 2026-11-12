@echo off
rem Instalator dla Windows: biblioteki Pythona + sprawdzenie Chrome.
cd /d "%~dp0"
where python >nul 2>nul || (
  echo Brak Pythona. Instaluje przez winget...
  winget install -e --id Python.Python.3.12 --accept-source-agreements --accept-package-agreements || (
    echo Zainstaluj Pythona recznie z https://www.python.org i zaznacz "Add python.exe to PATH".
    pause & exit /b 1
  )
  echo Zamknij to okno i uruchom install.bat ponownie, aby odswiezyc PATH.
  pause & exit /b 0
)
python -m pip install --upgrade pip
python -m pip install -r requirements.txt || (echo Blad instalacji bibliotek. & pause & exit /b 1)
python -c "from config import find_chrome_binary as f; import sys; sys.exit(0 if f() else 1)" || (
  echo Brak Google Chrome. Instaluje przez winget...
  winget install -e --id Google.Chrome --accept-source-agreements --accept-package-agreements || (
    echo Nie udalo sie zainstalowac Chrome automatycznie. Pobierz go z https://www.google.com/chrome
  )
)
echo.
echo Gotowe. Uruchom run.bat
pause
