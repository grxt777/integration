#!/bin/bash
# Bank Intelligence Platform — Startup Script
#
# Никаких серверов баз данных: используется SQLite (файл data/bank.db).
# Скрипт ставит зависимости, освобождает порт и запускает сервер.
#
# Полезные переменные:
#   APP_PORT=8001 ./run.sh     — другой порт
#   DB_PATH=/tmp/bank.db ./run.sh — другой файл базы

set -e
cd "$(dirname "$0")"

echo "🚀 Starting Bank Intelligence Platform..."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

APP_PORT="${APP_PORT:-8000}"

echo "📦 Installing dependencies..."
python3 -m pip install -q -r requirements.txt 2>&1 | grep -Ev "already satisfied|WARNING: You are using pip|You should consider upgrading|Defaulting to user installation" || true

# ── Освобождаем порт приложения ──────────────────────────────
port_busy() {
  python3 - "$APP_PORT" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket()
s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try:
    s.bind(("0.0.0.0", int(sys.argv[1])))
    sys.exit(1)   # порт свободен
except OSError:
    sys.exit(0)   # порт занят
finally:
    s.close()
PY
}

if port_busy; then
  OLD_PID=""
  if command -v lsof >/dev/null 2>&1; then
    OLD_PID="$(lsof -ti:"$APP_PORT" 2>/dev/null || true)"
  elif command -v fuser >/dev/null 2>&1; then
    OLD_PID="$(fuser "$APP_PORT"/tcp 2>/dev/null | tr -d ' ' || true)"
  fi

  if [ -n "$OLD_PID" ]; then
    echo "♻️  Порт $APP_PORT занят (PID $OLD_PID) — останавливаю старый процесс."
    # shellcheck disable=SC2086
    kill -9 $OLD_PID 2>/dev/null || true
    sleep 1
  else
    echo "⚠️  Порт $APP_PORT занят другим процессом."
    echo "   Освободите его:  lsof -ti:$APP_PORT | xargs kill -9"
    echo "   Или запустите на другом порту:  APP_PORT=8001 ./run.sh"
    exit 1
  fi
fi

export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$(pwd)/api"

echo ""
echo "🗄️  База данных: SQLite — ${DB_PATH:-data/bank.db}"
echo "🌐 Starting FastAPI server on http://localhost:$APP_PORT"
echo "   Главная:        http://localhost:$APP_PORT/dashboard/index.html"
echo "   Карта ATM:      http://localhost:$APP_PORT/dashboard/map.html"
echo "   Кассиры:        http://localhost:$APP_PORT/dashboard/cashiers.html"
echo "   Swagger:        http://localhost:$APP_PORT/docs"
echo "================================================"

python3 -m uvicorn api.main:app --host 0.0.0.0 --port "$APP_PORT" --reload
