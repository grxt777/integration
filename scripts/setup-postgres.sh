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

# Определяем суперпользователя, под которым можно создать роль.
# В Homebrew это текущий пользователь macOS, в Linux/Docker — postgres.
SUPERUSER=""
for candidate in "$USER" postgres; do
  if psql -h "$DB_HOST" -p "$DB_PORT" -U "$candidate" -d postgres -c '\q' >/dev/null 2>&1; then
    SUPERUSER="$candidate"
    break
  fi
done

if [ -z "$SUPERUSER" ]; then
  echo "❌ Не удалось подключиться к PostgreSQL под '$USER' или 'postgres'."
  echo "   Убедитесь, что сервер запущен:  brew services start postgresql@16"
  exit 1
fi

echo "✅ Подключение установлено под суперпользователем '$SUPERUSER'"

PSQL="psql -h $DB_HOST -p $DB_PORT -U $SUPERUSER -d postgres -v ON_ERROR_STOP=1"

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
echo "🎉 Готово. Теперь запустите приложение:  ./run.sh"
