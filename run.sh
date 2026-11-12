#!/usr/bin/env bash
# Uruchamia Telegram AutoMessage. Przy pierwszym uruchomieniu sam odpala instalator.
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$APP_DIR"
if [ ! -x .venv/bin/python ]; then
  echo "Pierwsze uruchomienie - instaluje wymagane pakiety..."
  bash ./install.sh || exit 1
fi
exec .venv/bin/python main.py "$@"
