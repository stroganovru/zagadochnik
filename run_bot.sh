#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi
if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]]; then
  echo "Задайте TELEGRAM_BOT_TOKEN (BotFather → /newbot) в .env или в окружении."
  exit 1
fi
exec python3 bot.py
