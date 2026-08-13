"""
Единый слой доступа к PostgreSQL для Bank Intelligence Platform.

Объединяет два домена в одной базе:
  * atms / branches         — реестр банкоматов и филиалов (портировано с SQLite)
  * cashier_* таблицы       — аналитика кассиров (см. core/cashier/repository.py)
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

import psycopg2
import psycopg2.extras
import psycopg2.pool

from .config import (
    DATABASE_URL,
    POSTGRES_HOST,
    POSTGRES_PORT,
    POSTGRES_USER,
    DEFAULT_CAPACITY,
    LOW_CASH_PCT,
    POSTGRES_ADMIN_URL,
    POSTGRES_DB,
    WARNING_CASH_PCT,
)

log = logging.getLogger(__name__)

_pool: psycopg2.pool.ThreadedConnectionPool | None = None


class DatabaseUnavailableError(RuntimeError):
    """PostgreSQL недоступен или доступ не настроен — с инструкцией для пользователя."""


def _connection_help(error: Exception) -> str:
    """Формирует понятное сообщение вместо сырого traceback psycopg2."""
    text = str(error)

    if "could not connect" in text or "Connection refused" in text or "не удалось" in text.lower():
        reason = (
            f"PostgreSQL не отвечает на {POSTGRES_HOST}:{POSTGRES_PORT} — похоже, сервер не запущен.\n\n"
            "  Как запустить:\n"
            "    macOS (Homebrew):  brew services start postgresql@16\n"
            "    Linux (systemd):   sudo systemctl start postgresql\n"
            "    Docker (всё сразу): docker compose up\n\n"
            "  Если PostgreSQL ещё не установлен:\n"
            "    macOS:  brew install postgresql@16 && brew services start postgresql@16\n"
        )
    elif "password authentication failed" in text or "authentication" in text:
        reason = (
            f"Неверный логин или пароль для пользователя '{POSTGRES_USER}'.\n\n"
            "  Создайте роль и базу одной командой:\n"
            "    ./scripts/setup-postgres.sh\n\n"
            "  Либо поправьте доступы в файле .env\n"
        )
    elif "does not exist" in text and "role" in text:
        reason = (
            f"Роль '{POSTGRES_USER}' не существует в PostgreSQL.\n\n"
            "  Создайте роль и базу одной командой:\n"
            "    ./scripts/setup-postgres.sh\n"
        )
    else:
        reason = (
            "Не удалось подключиться к PostgreSQL.\n\n"
            "  Проверьте, что сервер запущен, и настройте доступ:\n"
            "    ./scripts/setup-postgres.sh\n"
        )

    return (
        "\n"
        "═══════════════════════════════════════════════════════════\n"
        " ❌ НЕТ ПОДКЛЮЧЕНИЯ К БАЗЕ ДАННЫХ\n"
        "═══════════════════════════════════════════════════════════\n\n"
        f"{reason}\n"
        "  Текущие настройки (из .env или значения по умолчанию):\n"
        f"    POSTGRES_HOST={POSTGRES_HOST}\n"
        f"    POSTGRES_PORT={POSTGRES_PORT}\n"
        f"    POSTGRES_DB={POSTGRES_DB}\n"
        f"    POSTGRES_USER={POSTGRES_USER}\n\n"
        f"  Исходная ошибка: {text.strip().splitlines()[0] if text.strip() else error}\n"
        "═══════════════════════════════════════════════════════════"
    )


def _ensure_database_exists() -> None:
    """Создаёт базу данных приложения, если её ещё нет."""
    try:
        conn = psycopg2.connect(POSTGRES_ADMIN_URL)
    except psycopg2.OperationalError as e:
        raise DatabaseUnavailableError(_connection_help(e)) from None

    try:
        conn.autocommit = True
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (POSTGRES_DB,))
        if not cur.fetchone():
            # UTF8 обязателен: реестры содержат кириллицу и узбекскую латиницу.
            cur.execute(f"CREATE DATABASE {POSTGRES_DB} ENCODING 'UTF8' TEMPLATE template0")
            log.info("Создана база данных PostgreSQL: %s", POSTGRES_DB)
        cur.close()
    except psycopg2.Error as e:
        raise DatabaseUnavailableError(_connection_help(e)) from None
    finally:
        conn.close()


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _ensure_database_exists()
        try:
            _pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL)
        except psycopg2.OperationalError as e:
            raise DatabaseUnavailableError(_connection_help(e)) from None
        log.info("Пул соединений PostgreSQL инициализирован.")
    return _pool


@contextmanager
def _connect() -> Iterator[psycopg2.extensions.connection]:
    """Контекстный менеджер: выдаёт соединение из пула с транзакцией."""
    pool = _get_pool()
    conn = pool.getconn()
    try:
        conn.set_client_encoding("UTF8")
        conn.autocommit = False
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


def dict_cursor(conn: psycopg2.extensions.connection) -> psycopg2.extras.RealDictCursor:
    """Курсор, возвращающий строки как словари."""
    return conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)


# ═══════════════════════════════════════════════════════════
# ИНИЦИАЛИЗАЦИЯ СХЕМЫ
# ═══════════════════════════════════════════════════════════

def init_db() -> None:
    """Создаёт таблицы обоих доменов при первом запуске."""
    with _connect() as conn:
        cur = dict_cursor(conn)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS atms (
                id              SERIAL PRIMARY KEY,
                terminal_id     TEXT UNIQUE NOT NULL,
                atm_number      TEXT,
                branch_code     TEXT,
                local_code      TEXT,
                region          TEXT,
                branch          TEXT,
                model           TEXT,
                network_type    TEXT,
                serial          TEXT,
                merchant_id     TEXT,
                address         TEXT,
                lat             DOUBLE PRECISION,
                lon             DOUBLE PRECISION,
                capacity        BIGINT NOT NULL DEFAULT 400000000,
                balance         BIGINT,
                last_balance_at TIMESTAMPTZ,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_atms_region ON atms(region)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_atms_branch ON atms(branch)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_atms_local  ON atms(local_code)")

        cur.execute("""
            CREATE TABLE IF NOT EXISTS branches (
                id              SERIAL PRIMARY KEY,
                number          TEXT,
                local_code      TEXT UNIQUE,
                region          TEXT,
                address         TEXT,
                lat             DOUBLE PRECISION,
                lon             DOUBLE PRECISION,
                incassation     INTEGER NOT NULL DEFAULT 0,
                created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
                updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_branches_region ON branches(region)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_branches_inc    ON branches(incassation)")
        cur.close()

    # Домен кассиров живёт в отдельном модуле, чтобы не смешивать бизнес-логику.
    from .cashier_analytics import init_cashier_tables
    init_cashier_tables()
    log.info("База данных инициализирована (ATM + филиалы + кассиры).")


# ═══════════════════════════════════════════════════════════
# ATM — ЧТЕНИЕ
# ═══════════════════════════════════════════════════════════

def _compute_status(balance: Optional[int], capacity: int) -> str:
    if balance is None:
        return "unknown"
    if capacity <= 0:
        return "ok"
    pct = balance / capacity
    if pct < LOW_CASH_PCT:
        return "critical"
    if pct < WARNING_CASH_PCT:
        return "warning"
    return "ok"


def _decorate_atm(d: Dict[str, Any]) -> Dict[str, Any]:
    cap = d.get("capacity") or DEFAULT_CAPACITY
    bal = d.get("balance")
    d["balance_pct"] = round((bal / cap) * 100, 1) if bal is not None and cap else None
    d["status"] = _compute_status(bal, cap)
    for key in ("created_at", "updated_at", "last_balance_at"):
        if d.get(key) is not None:
            d[key] = d[key].isoformat()
    return d


def count_atms() -> int:
    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute("SELECT COUNT(*) AS c FROM atms")
        n = int(cur.fetchone()["c"])
        cur.close()
        return n


def list_atms(
    region: Optional[str] = None,
    branch: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 1000,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM atms WHERE TRUE"
    params: list[Any] = []
    if region:
        sql += " AND region = %s"
        params.append(region)
    if branch:
        sql += " AND branch = %s"
        params.append(branch)
    sql += " ORDER BY id LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute(sql, params)
        rows = [_decorate_atm(dict(r)) for r in cur.fetchall()]
        cur.close()

    if status:
        rows = [r for r in rows if r["status"] == status]
    return rows


def get_atm(terminal_id: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute("SELECT * FROM atms WHERE terminal_id = %s", (terminal_id,))
        row = cur.fetchone()
        cur.close()
    return _decorate_atm(dict(row)) if row else None


def list_regions() -> List[Dict[str, Any]]:
    """Список областей с количеством ATM."""
    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute("""
            SELECT region, COUNT(*) AS cnt
              FROM atms
             WHERE region IS NOT NULL AND region <> ''
             GROUP BY region
             ORDER BY cnt DESC
        """)
        rows = cur.fetchall()
        cur.close()
    return [{"region": r["region"], "count": int(r["cnt"])} for r in rows]


def list_branches(region: Optional[str] = None) -> List[Dict[str, Any]]:
    """Список филиалов с количеством ATM."""
    sql = """
        SELECT branch, region, COUNT(*) AS cnt
          FROM atms
         WHERE branch IS NOT NULL AND branch <> ''
    """
    params: list[Any] = []
    if region:
        sql += " AND region = %s"
        params.append(region)
    sql += " GROUP BY branch, region ORDER BY cnt DESC"

    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
    return [{"branch": r["branch"], "region": r["region"], "count": int(r["cnt"])} for r in rows]


# ═══════════════════════════════════════════════════════════
# ATM — ЗАПИСЬ
# ═══════════════════════════════════════════════════════════

def truncate_atms() -> int:
    """Удаляет все ATM, возвращает количество удалённых строк."""
    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute("SELECT COUNT(*) AS c FROM atms")
        n = int(cur.fetchone()["c"])
        cur.execute("TRUNCATE TABLE atms RESTART IDENTITY CASCADE")
        cur.close()
    return n


def bulk_insert_atms(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Массовый UPSERT банкоматов по terminal_id."""
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    with _connect() as conn:
        cur = dict_cursor(conn)
        for rec in records:
            terminal_id = (rec.get("terminal_id") or "").strip()
            if not terminal_id:
                stats["skipped"] += 1
                continue

            cur.execute("""
                INSERT INTO atms (
                    terminal_id, atm_number, branch_code, local_code, region, branch,
                    model, network_type, serial, merchant_id, address, lat, lon, capacity
                ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (terminal_id) DO UPDATE SET
                    atm_number   = EXCLUDED.atm_number,
                    branch_code  = EXCLUDED.branch_code,
                    local_code   = EXCLUDED.local_code,
                    region       = EXCLUDED.region,
                    branch       = EXCLUDED.branch,
                    model        = EXCLUDED.model,
                    network_type = EXCLUDED.network_type,
                    serial       = EXCLUDED.serial,
                    merchant_id  = EXCLUDED.merchant_id,
                    address      = EXCLUDED.address,
                    lat          = EXCLUDED.lat,
                    lon          = EXCLUDED.lon,
                    capacity     = EXCLUDED.capacity,
                    updated_at   = now()
                RETURNING (xmax = 0) AS inserted
            """, (
                terminal_id,
                rec.get("atm_number"), rec.get("branch_code"), rec.get("local_code"),
                rec.get("region"), rec.get("branch"), rec.get("model"),
                rec.get("network_type"), rec.get("serial"), rec.get("merchant_id"),
                rec.get("address"), rec.get("lat"), rec.get("lon"),
                rec.get("capacity") or DEFAULT_CAPACITY,
            ))
            if cur.fetchone()["inserted"]:
                stats["inserted"] += 1
            else:
                stats["updated"] += 1
        cur.close()
    return stats


def update_balance(terminal_id: str, balance: int) -> bool:
    """Обновляет остаток одного ATM."""
    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute("""
            UPDATE atms
               SET balance = %s, last_balance_at = now(), updated_at = now()
             WHERE terminal_id = %s
        """, (int(balance), terminal_id))
        ok = cur.rowcount > 0
        cur.close()
    return ok


def bulk_update_balances(updates: List[Dict[str, Any]]) -> Dict[str, int]:
    """Массовое обновление остатков: [{terminal_id, balance}, ...]"""
    ok, fail = 0, 0
    with _connect() as conn:
        cur = dict_cursor(conn)
        for u in updates:
            tid, bal = u.get("terminal_id"), u.get("balance")
            if not tid or bal is None:
                fail += 1
                continue
            cur.execute("""
                UPDATE atms
                   SET balance = %s, last_balance_at = now(), updated_at = now()
                 WHERE terminal_id = %s
            """, (int(bal), tid))
            if cur.rowcount:
                ok += 1
            else:
                fail += 1
        cur.close()
    return {"updated": ok, "failed": fail}


# ═══════════════════════════════════════════════════════════
# ФИЛИАЛЫ
# ═══════════════════════════════════════════════════════════

def _decorate_branch(d: Dict[str, Any]) -> Dict[str, Any]:
    for key in ("created_at", "updated_at"):
        if d.get(key) is not None:
            d[key] = d[key].isoformat()
    return d


def count_branches() -> int:
    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute("SELECT COUNT(*) AS c FROM branches")
        n = int(cur.fetchone()["c"])
        cur.close()
    return n


def list_branches_full(
    region: Optional[str] = None,
    incassation: Optional[int] = None,
    limit: int = 5000,
    offset: int = 0,
) -> List[Dict[str, Any]]:
    sql = "SELECT * FROM branches WHERE TRUE"
    params: list[Any] = []
    if region:
        sql += " AND region = %s"
        params.append(region)
    if incassation is not None:
        sql += " AND incassation = %s"
        params.append(int(incassation))
    sql += " ORDER BY id LIMIT %s OFFSET %s"
    params.extend([limit, offset])

    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute(sql, params)
        rows = [_decorate_branch(dict(r)) for r in cur.fetchall()]
        cur.close()
    return rows


def get_branch(local_code: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute("SELECT * FROM branches WHERE local_code = %s", (local_code,))
        row = cur.fetchone()
        cur.close()
    return _decorate_branch(dict(row)) if row else None


def truncate_branches() -> int:
    with _connect() as conn:
        cur = dict_cursor(conn)
        cur.execute("SELECT COUNT(*) AS c FROM branches")
        n = int(cur.fetchone()["c"])
        cur.execute("TRUNCATE TABLE branches RESTART IDENTITY CASCADE")
        cur.close()
    return n


def bulk_insert_branches(records: List[Dict[str, Any]]) -> Dict[str, int]:
    """Массовый UPSERT филиалов по local_code."""
    stats = {"inserted": 0, "updated": 0, "skipped": 0}
    with _connect() as conn:
        cur = dict_cursor(conn)
        for rec in records:
            local_code = (rec.get("local_code") or "").strip() or None
            values = (
                rec.get("number"), rec.get("region"), rec.get("address"),
                rec.get("lat"), rec.get("lon"), int(rec.get("incassation") or 0),
            )

            if local_code:
                cur.execute("""
                    INSERT INTO branches (number, local_code, region, address, lat, lon, incassation)
                    VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (local_code) DO UPDATE SET
                        number      = EXCLUDED.number,
                        region      = EXCLUDED.region,
                        address     = EXCLUDED.address,
                        lat         = EXCLUDED.lat,
                        lon         = EXCLUDED.lon,
                        incassation = EXCLUDED.incassation,
                        updated_at  = now()
                    RETURNING (xmax = 0) AS inserted
                """, (values[0], local_code, *values[1:]))
                if cur.fetchone()["inserted"]:
                    stats["inserted"] += 1
                else:
                    stats["updated"] += 1
            else:
                cur.execute("""
                    INSERT INTO branches (number, local_code, region, address, lat, lon, incassation)
                    VALUES (%s, NULL, %s,%s,%s,%s,%s)
                """, values)
                stats["inserted"] += 1
        cur.close()
    return stats
