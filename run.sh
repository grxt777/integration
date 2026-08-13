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

  # Дополняем PATH типичными путями macOS/Linux: Homebrew на Apple Silicon
  # (/opt/homebrew) и Intel (/usr/local) не всегда есть в PATH у неинтерактивных
  # шеллов, а Postgres.app и EDB-инсталлятор кладут бинарники в свои каталоги.
  for candidate in \
    /opt/homebrew/bin \
    /usr/local/bin \
    /opt/homebrew/opt/postgresql@17/bin \
    /opt/homebrew/opt/postgresql@16/bin \
    /opt/homebrew/opt/postgresql@15/bin \
    /usr/local/opt/postgresql@17/bin \
    /usr/local/opt/postgresql@16/bin \
    /usr/local/opt/postgresql@15/bin \
    /Applications/Postgres.app/Contents/Versions/latest/bin \
    /Library/PostgreSQL/17/bin \
    /Library/PostgreSQL/16/bin
  do
    if [ -d "$candidate" ]; then
      case ":$PATH:" in
        *":$candidate:"*) ;;
        *) PATH="$candidate:$PATH" ;;
      esac
    fi
  done
  export PATH

  STARTED=0

  # macOS + Homebrew
  if command -v brew >/dev/null 2>&1; then
    FORMULA="$(brew list --formula 2>/dev/null | grep -E '^postgresql(@[0-9]+)?$' | tail -1 || true)"

    if [ -z "$FORMULA" ]; then
      echo "📥 PostgreSQL не установлен. Устанавливаю postgresql@16 через Homebrew..."
      echo "   (это займёт пару минут)"
      brew install postgresql@16 || true
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

  # Фолбэк: поднимаем базу в Docker — работает без Homebrew и прав администратора
  if ! db_is_up && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "🐳 Homebrew недоступен — поднимаю PostgreSQL в Docker..."
    if docker compose version >/dev/null 2>&1; then
      docker compose up -d db >/dev/null 2>&1 || true
    else
      docker-compose up -d db >/dev/null 2>&1 || true
    fi
    printf "⏳ Жду готовности контейнера с базой"
    for _ in $(seq 1 60); do
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
    if ! command -v brew >/dev/null 2>&1 && [ "$(uname)" = "Darwin" ]; then
      echo "   Homebrew не найден. Варианты:"
      echo ""
      echo "   1) Поднять всё в Docker (проще всего, ничего ставить не нужно):"
      echo "        docker compose up"
      echo ""
      echo "   2) Установить Homebrew, затем PostgreSQL:"
      echo '        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
      echo "        brew install postgresql@16 && brew services start postgresql@16"
      echo ""
      echo "   3) Установить Postgres.app: https://postgresapp.com"
      echo ""
      echo "   Если PostgreSQL уже установлен, но лежит в нестандартном месте —"
      echo "   укажите его порт/хост в файле .env"
    else
      echo "   Запустите вручную одной из команд:"
      echo "     macOS:   brew install postgresql@16 && brew services start postgresql@16"
      echo "     Linux:   sudo systemctl start postgresql"
      echo "     Docker:  docker compose up      # поднимет базу и приложение целиком"
    fi
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
