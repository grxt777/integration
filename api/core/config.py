"""
Единая конфигурация Bank Intelligence Platform.

Объединяет настройки двух доменов:
  * Cashier Intelligence — аналитика кассиров (PostgreSQL)
  * ATM Monitor         — реестр банкоматов, остатки, инкассация

Все пути, пороги и параметры подключения берутся отсюда.
"""

import os
from pathlib import Path

# ── Пути ────────────────────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parents[2]   # корень проекта
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# ── PostgreSQL Connection Settings ───────────────────────────
POSTGRES_HOST     = os.getenv("POSTGRES_HOST",     "localhost")
POSTGRES_PORT     = int(os.getenv("POSTGRES_PORT", "5432"))
POSTGRES_DB       = os.getenv("POSTGRES_DB",       "bank_db")
POSTGRES_USER     = os.getenv("POSTGRES_USER",     "bank")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "bank")

DATABASE_URL = (
    f"host={POSTGRES_HOST} "
    f"port={POSTGRES_PORT} "
    f"dbname={POSTGRES_DB} "
    f"user={POSTGRES_USER} "
    f"password={POSTGRES_PASSWORD} "
    # Явная кодировка клиента: реестры содержат кириллицу и узбекскую латиницу,
    # без неё psycopg2 падает на серверах, поднятых с локалью SQL_ASCII/C.
    f"options='-c client_encoding=UTF8'"
)

# DSN для создания самой базы (подключаемся к служебной БД 'postgres')
POSTGRES_ADMIN_URL = (
    f"host={POSTGRES_HOST} "
    f"port={POSTGRES_PORT} "
    f"dbname=postgres "
    f"user={POSTGRES_USER} "
    f"password={POSTGRES_PASSWORD}"
)

# ── Бизнес-пороги ATM ────────────────────────────────────────
LOW_CASH_PCT      = float(os.getenv("LOW_CASH_PCT", "0.20"))      # критичный уровень (cash-out)
WARNING_CASH_PCT  = float(os.getenv("WARNING_CASH_PCT", "0.40"))  # уровень предупреждения
DEFAULT_CAPACITY  = int(os.getenv("DEFAULT_CAPACITY", "400000000"))  # ёмкость ATM по умолчанию, UZS

# ── Геометрия / маршруты инкассации ─────────────────────────
DEPOT = {"lat": 41.3111, "lon": 69.2797, "name": "Центральный депо (Ташкент)"}
ROAD_FACTOR = 1.35      # коэффициент дорожной сети к прямому расстоянию
AVG_SPEED_KMH = 30      # средняя скорость инкассаторской машины
