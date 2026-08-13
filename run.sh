#!/bin/bash
# Bank Intelligence Platform — Startup Script
#
# Скрипт делает всё сам:
#   1. ставит зависимости Python
#   2. находит / запускает PostgreSQL (при необходимости ставит через Homebrew)
#   3. создаёт роль и базу
#   4. освобождает порт 8000 и запускает сервер
#
# Пропустить работу с базой:  SKIP_DB_SETUP=1 ./run.sh

set -e
cd "$(dirname "$0")"

echo "🚀 Starting Bank Intelligence Platform..."

if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

DB_HOST="${POSTGRES_HOST:-localhost}"
DB_PORT="${POSTGRES_PORT:-5432}"
DB_NAME="${POSTGRES_DB:-bank_db}"
DB_USER="${POSTGRES_USER:-bank}"
DB_PASS="${POSTGRES_PASSWORD:-bank}"
APP_PORT="${APP_PORT:-8000}"

echo "📦 Installing dependencies..."
python3 -m pip install -q -r requirements.txt 2>&1 | grep -Ev "already satisfied|WARNING: You are using pip|You should consider upgrading|Defaulting to user installation" || true

# ── Проверка доступности PostgreSQL ──────────────────────────
db_is_up() {
  python3 - "$DB_HOST" "$DB_PORT" <<'PY' 2>/dev/null
import socket, sys
s = socket.socket()
s.settimeout(2)
try:
    s.connect((sys.argv[1], int(sys.argv[2])))
    sys.exit(0)
except Exception:
    sys.exit(1)
finally:
    s.close()
PY
}

if [ "$SKIP_DB_SETUP" != "1" ] && ! db_is_up; then
  echo ""
  echo "🔍 PostgreSQL не отвечает на $DB_HOST:$DB_PORT — пробую запустить..."

  if [ "$DB_HOST" != "localhost" ] && [ "$DB_HOST" != "127.0.0.1" ]; then
    echo "❌ База настроена на удалённый хост $DB_HOST — запустить её отсюда нельзя."
    exit 1
  fi

  STARTED=0

  # macOS + Homebrew
  if command -v brew >/dev/null 2>&1; then
    FORMULA="$(brew list --formula 2>/dev/null | grep -E '^postgresql(@[0-9]+)?$' | tail -1 || true)"

    if [ -z "$FORMULA" ]; then
      echo "📥 PostgreSQL не установлен. Устанавливаю postgresql@16 через Homebrew..."
      echo "   (это займёт пару минут)"
      brew install postgresql@16
      FORMULA="postgresql@16"
    fi

    echo "▶️  brew services start $FORMULA"
    brew services start "$FORMULA" >/dev/null 2>&1 || true

    # Homebrew не всегда кладёт psql в PATH — добавляем сами
    for prefix in "$(brew --prefix "$FORMULA" 2>/dev/null)" "$(brew --prefix 2>/dev/null)"; do
      [ -n "$prefix" ] && [ -d "$prefix/bin" ] && export PATH="$prefix/bin:$PATH"
    done
    STARTED=1

  # Linux + systemd
  elif command -v systemctl >/dev/null 2>&1; then
    echo "▶️  sudo systemctl start postgresql"
    sudo systemctl start postgresql >/dev/null 2>&1 || true
    STARTED=1

  # Linux без systemd
  elif command -v pg_ctlcluster >/dev/null 2>&1; then
    sudo pg_ctlcluster "$(ls /etc/postgresql | head -1)" main start >/dev/null 2>&1 || true
    STARTED=1
  fi

  if [ "$STARTED" = "1" ]; then
    printf "⏳ Жду готовности базы"
    for _ in $(seq 1 30); do
      if db_is_up; then break; fi
      printf "."
      sleep 1
    done
    echo ""
  fi

  if ! db_is_up; then
    echo ""
    echo "❌ Не удалось запустить PostgreSQL автоматически."
    echo ""
    echo "   Запустите вручную одной из команд:"
    echo "     macOS:   brew install postgresql@16 && brew services start postgresql@16"
    echo "     Linux:   sudo systemctl start postgresql"
    echo "     Docker:  docker compose up      # поднимет базу и приложение целиком"
    exit 1
  fi
  echo "✅ PostgreSQL доступен на $DB_HOST:$DB_PORT"
fi

# ── Роль и база ──────────────────────────────────────────────
if [ "$SKIP_DB_SETUP" != "1" ] && command -v psql >/dev/null 2>&1; then
  if ! PGPASSWORD="$DB_PASS" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c '\q' >/dev/null 2>&1; then
    echo "🔧 Настраиваю роль '$DB_USER' и базу '$DB_NAME'..."
    CALLED_FROM_RUN_SH=1 ./scripts/setup-postgres.sh || {
      echo "⚠️  Автонастройка не удалась — приложение попробует создать базу само."
    }
  fi
fi

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
echo "🌐 Starting FastAPI server on http://localhost:$APP_PORT"
echo "   Главная:        http://localhost:$APP_PORT/dashboard/index.html"
echo "   Карта ATM:      http://localhost:$APP_PORT/dashboard/map.html"
echo "   Кассиры:        http://localhost:$APP_PORT/dashboard/cashiers.html"
echo "   Swagger:        http://localhost:$APP_PORT/docs"
echo "================================================"

python3 -m uvicorn api.main:app --host 0.0.0.0 --port "$APP_PORT" --reload
