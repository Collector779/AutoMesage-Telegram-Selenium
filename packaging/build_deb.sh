#!/usr/bin/env bash
# Build dist/telegram-automessage_<version>_all.deb  (run on Debian/Ubuntu, or WSL).
# Needs: python3, python3-venv, dpkg-deb.   Usage:  bash packaging/build_deb.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION="$(cd "$ROOT" && python3 -c 'from config import APP_VERSION; print(APP_VERSION)')"
PKG=telegram-automessage
WORK="$(mktemp -d)"
STAGE="$WORK/${PKG}_${VERSION}_all"
APPDIR="$STAGE/opt/$PKG"
trap 'rm -rf "$WORK"' EXIT

echo "==> Buduję $PKG $VERSION"
mkdir -p "$APPDIR/lib" "$STAGE/DEBIAN" "$STAGE/usr/bin" "$STAGE/usr/share/applications" \
         "$STAGE/usr/share/icons/hicolor/256x256/apps" "$STAGE/usr/share/doc/$PKG"

# --- program
cp "$ROOT"/*.py "$APPDIR/"
cp -r "$ROOT/assets" "$APPDIR/assets"
cp "$ROOT/README.md" "$STAGE/usr/share/doc/$PKG/"

# --- bundled Python libraries (pure Python; Pillow comes from the system package python3-pil)
python3 -m venv "$WORK/venv"
"$WORK/venv/bin/pip" install --quiet --upgrade pip
"$WORK/venv/bin/pip" install --quiet --no-compile --target "$APPDIR/lib" \
    -r "$ROOT/requirements.txt" exceptiongroup
rm -rf "$APPDIR/lib"/PIL "$APPDIR/lib"/pillow* "$APPDIR/lib"/bin
# keep only the Linux selenium-manager binary
rm -rf "$APPDIR/lib/selenium/webdriver/common/windows" "$APPDIR/lib/selenium/webdriver/common/macos"
find "$APPDIR" -name '__pycache__' -prune -exec rm -rf {} +
if find "$APPDIR/lib" -name '*.so' | grep -q .; then
  echo "BLAD: w bibliotekach są pliki binarne .so (paczka nie byłaby 'all'):" >&2
  find "$APPDIR/lib" -name '*.so' >&2
  exit 1
fi

# --- launcher, menu entry, icon
cat > "$STAGE/usr/bin/$PKG" <<'EOF'
#!/bin/sh
export PYTHONPATH="/opt/telegram-automessage/lib${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 /opt/telegram-automessage/main.py "$@"
EOF
cat > "$STAGE/usr/share/applications/$PKG.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Telegram AutoMessage
Comment=Automatyczne wiadomości do grup i kanałów Telegrama
Exec=$PKG
Icon=$PKG
Terminal=false
Categories=Network;InstantMessaging;
EOF
cp "$ROOT/assets/icon-256.png" "$STAGE/usr/share/icons/hicolor/256x256/apps/$PKG.png"

# --- package metadata
SIZE_KB="$(du -sk "$STAGE" | cut -f1)"
cat > "$STAGE/DEBIAN/control" <<EOF
Package: $PKG
Version: $VERSION
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.10), python3-tk, python3-pil (>= 10), python3-pil.imagetk
Recommends: chromium-driver | google-chrome-stable, fonts-noto-color-emoji
Installed-Size: $SIZE_KB
Maintainer: Collector779 <Collector779@users.noreply.github.com>
Homepage: https://github.com/Collector779/AutoMesage-Telegram-Selenium
Description: automatyczne wiadomości do grup i kanałów Telegrama
 Program z okienkiem: logowanie numerem telefonu i kodem, skanowanie grup,
 kanałów i tematów forum, wysyłanie własnej treści lub przekazywanie
 wiadomości według harmonogramu, obsługa proxy i trybu powolnego.
 Działa w tle przez Telegram Web (Chromium / Google Chrome).
EOF
cat > "$STAGE/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q -t /usr/share/icons/hicolor || true
exit 0
EOF
cat > "$STAGE/DEBIAN/postrm" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = "remove" ] || [ "$1" = "purge" ]; then
  rm -rf /opt/telegram-automessage
fi
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true
exit 0
EOF

# --- permissions
find "$STAGE" -type d -exec chmod 755 {} +
find "$STAGE" -type f -exec chmod 644 {} +
chmod 755 "$STAGE/usr/bin/$PKG" "$STAGE/DEBIAN/postinst" "$STAGE/DEBIAN/postrm"
# selenium-manager ships per architecture (linux-x86_64, linux-arm64)
find "$APPDIR/lib/selenium/webdriver/common" -path '*linux*' -name 'selenium-manager' -exec chmod 755 {} +

mkdir -p "$ROOT/dist"
OUT="$ROOT/dist/${PKG}_${VERSION}_all.deb"
dpkg-deb --build --root-owner-group -Zxz "$STAGE" "$OUT" >/dev/null
echo "==> Gotowe: $OUT ($(du -h "$OUT" | cut -f1))"
