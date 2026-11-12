#!/usr/bin/env bash
# Instalator dla Debiana / Ubuntu / Mint: pakiety systemowe, przegladarka, srodowisko Pythona, skrot w menu.
# Uzycie:  bash install.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$APP_DIR/.venv"
cd "$APP_DIR"

info()  { printf '\033[1;34m==>\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m OK\033[0m %s\n' "$*"; }
fail()  { printf '\033[1;31mBLAD:\033[0m %s\n' "$*" >&2; exit 1; }

command -v apt-get >/dev/null || fail "Ten instalator obsluguje systemy z apt (Debian, Ubuntu, Mint)."

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else
  command -v sudo >/dev/null || fail "Brak sudo. Uruchom jako root: su -c 'bash install.sh'"
  SUDO="sudo"
fi

. /etc/os-release 2>/dev/null || true
DISTRO="${ID:-debian}"
ARCH="$(dpkg --print-architecture)"

# ---------------------------------------------------------------- pakiety systemowe
info "Instaluje pakiety systemowe (Python, Tkinter, czcionki z emoji)..."
$SUDO apt-get update -y
$SUDO apt-get install -y python3 python3-venv python3-pip python3-tk \
  fonts-noto-color-emoji fonts-dejavu-core ca-certificates wget xdg-utils
ok "Pakiety systemowe"

# ---------------------------------------------------------------- przegladarka
have_browser() {
  command -v google-chrome >/dev/null || command -v google-chrome-stable >/dev/null ||
  { command -v chromium >/dev/null && command -v chromedriver >/dev/null; } ||
  { [ -x /usr/bin/chromium ] && [ -x /usr/bin/chromedriver ]; }
}

if have_browser; then
  ok "Przegladarka juz jest"
elif [ "$DISTRO" = "debian" ]; then
  info "Instaluje Chromium i chromedriver z repozytorium Debiana..."
  $SUDO apt-get install -y chromium chromium-driver
  ok "Chromium"
elif [ "$ARCH" = "amd64" ]; then
  # Ubuntu/Mint: chromium z apt to paczka snap, ktora zle wspolpracuje z Selenium -> oficjalny Google Chrome
  info "Instaluje Google Chrome (oficjalna paczka .deb od Google)..."
  TMP_DEB="$(mktemp --suffix=.deb)"
  wget -q -O "$TMP_DEB" https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  $SUDO apt-get install -y "$TMP_DEB"
  rm -f "$TMP_DEB"
  ok "Google Chrome"
else
  info "Architektura $ARCH: probuje Chromium z apt..."
  $SUDO apt-get install -y chromium chromium-driver || $SUDO apt-get install -y chromium-browser chromium-chromedriver
fi

# ---------------------------------------------------------------- Python
info "Tworze srodowisko Pythona w $VENV ..."
python3 -m venv "$VENV"
"$VENV/bin/python" -m pip install --upgrade pip >/dev/null
"$VENV/bin/python" -m pip install -r "$APP_DIR/requirements.txt"
ok "Biblioteki Pythona"

# ---------------------------------------------------------------- skrot w menu
chmod +x "$APP_DIR/run.sh"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
mkdir -p "$DESKTOP_DIR"
cat > "$DESKTOP_DIR/telegram-automessage.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Telegram AutoMessage
Comment=Automatyczne wiadomosci do grup i kanalow Telegrama
Exec="$APP_DIR/run.sh"
Path=$APP_DIR
Icon=mail-send
Terminal=false
Categories=Network;
EOF
ok "Skrot w menu aplikacji: Telegram AutoMessage"

# ---------------------------------------------------------------- test
info "Sprawdzam instalacje..."
"$VENV/bin/python" - <<'PY'
import tkinter, selenium, ttkbootstrap
from config import find_chrome_binary
print("  Python OK, selenium", selenium.__version__, "| przegladarka:", find_chrome_binary() or "(Selenium Manager)")
PY

echo
ok "Gotowe. Uruchom:  ./run.sh   albo z menu aplikacji: Telegram AutoMessage"
