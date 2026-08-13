#!/bin/bash
# Bank Intelligence Platform — создание роли и базы данных в локальном PostgreSQL.
#
# Скрипт подключается к PostgreSQL под текущим суперпользователем и создаёт
# роль и базу, указанные в .env (или значения по умолчанию: bank / bank_db).
#
# Использование:
#   ./scripts/setup-postgres.sh

set -e

cd "$(dirname "$0")/.."

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

echo "🔧 Настройка PostgreSQL: роль '$DB_USER', база '$DB_NAME' на $DB_HOST:$DB_PORT"

# psql часто лежит вне PATH: Homebrew на Apple Silicon (/opt/homebrew) и Intel
# (/usr/local), Postgres.app и EDB-инсталлятор используют свои каталоги.
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

# Homebrew ставит postgresql в отдельный префикс и не всегда добавляет его в PATH.
if ! command -v psql >/dev/null 2>&1 && command -v brew >/dev/null 2>&1; then
  for formula in $(brew list --formula 2>/dev/null | grep -E '^postgresql(@[0-9]+)?$'); do
    prefix="$(brew --prefix "$formula" 2>/dev/null)"
    if [ -n "$prefix" ] && [ -x "$prefix/bin/psql" ]; then
      export PATH="$prefix/bin:$PATH"
      break
    fi
  done
fi

if ! command -v psql >/dev/null 2>&1; then
  echo "❌ Утилита psql не найдена."
  echo "   macOS:  brew install postgresql@16"
  echo "   Linux:  sudo apt install postgresql-client"
  exit 1
fi

# Определяем, как подключиться с правами суперпользователя.
# macOS/Homebrew — текущий пользователь по TCP; Linux — обычно только
# локальный сокет под системным пользователем postgres (peer-аутентификация).
PSQL=""
for candidate in "$USER" postgres; do
  if psql -h "$DB_HOST" -p "$DB_PORT" -U "$candidate" -d postgres -c '\q' >/dev/null 2>&1; then
    PSQL="psql -h $DB_HOST -p $DB_PORT -U $candidate -d postgres -v ON_ERROR_STOP=1"
    echo "✅ Подключение установлено под суперпользователем '$candidate'"
    break
  fi
done

if [ -z "$PSQL" ] && command -v sudo >/dev/null 2>&1; then
  if sudo -n -u postgres psql -d postgres -c '\q' >/dev/null 2>&1; then
    PSQL="sudo -n -u postgres psql -d postgres -v ON_ERROR_STOP=1"
    echo "✅ Подключение установлено через sudo -u postgres (локальный сокет)"
  elif sudo -u postgres psql -d postgres -c '\q' >/dev/null 2>&1; then
    PSQL="sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1"
    echo "✅ Подключение установлено через sudo -u postgres (локальный сокет)"
  fi
fi

if [ -z "$PSQL" ]; then
  echo "❌ Не удалось подключиться к PostgreSQL с правами суперпользователя."
  echo "   Пробовал: пользователь '$USER', 'postgres' по TCP и sudo -u postgres."
  echo ""
  echo "   Убедитесь, что сервер запущен:"
  echo "     macOS:  brew services start postgresql@16"
  echo "     Linux:  sudo systemctl start postgresql"
  exit 1
fi

# Роль
if $PSQL -tAc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1; then
  echo "ℹ️  Роль '$DB_USER' уже существует — обновляю пароль."
  $PSQL -c "ALTER ROLE \"$DB_USER\" WITH LOGIN CREATEDB PASSWORD '$DB_PASS';" >/dev/null
else
  echo "➕ Создаю роль '$DB_USER'."
  $PSQL -c "CREATE ROLE \"$DB_USER\" WITH LOGIN CREATEDB PASSWORD '$DB_PASS';" >/dev/null
fi

# База (обязательно UTF8 — реестры содержат кириллицу и узбекскую латиницу)
if $PSQL -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  echo "ℹ️  База '$DB_NAME' уже существует."
else
  echo "➕ Создаю базу '$DB_NAME' (ENCODING UTF8)."
  $PSQL -c "CREATE DATABASE \"$DB_NAME\" OWNER \"$DB_USER\" ENCODING 'UTF8' TEMPLATE template0;" >/dev/null
fi

$PSQL -c "GRANT ALL PRIVILEGES ON DATABASE \"$DB_NAME\" TO \"$DB_USER\";" >/dev/null

echo ""
if [ "$CALLED_FROM_RUN_SH" = "1" ]; then
  echo "🎉 База готова."
else
  echo "🎉 Готово. Теперь запустите приложение:  ./run.sh"
fi
