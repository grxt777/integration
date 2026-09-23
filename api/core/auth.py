"""
Авторизация, роли и постраничные права доступа.

Хранилище — те же таблицы в data/bank.db (SQLite), без внешних сервисов —
как и весь остальной проект. Пароли хэшируются pbkdf2_hmac из стандартной
библиотеки (без bcrypt — не нужна компиляция ради внутреннего инструмента).

Права выдаются не на конкретный HTML-файл, а на «page-key» — функциональный
блок дашборда (карта ATM, касса филиалов, кассиры...). PAGE_DEFINITIONS ниже —
единственное место, где страницы и API привязаны к своему page-key; и админка
(список чекбоксов для роли), и http-гейт в api/main.py читают именно его.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
from typing import Any, Dict, List, Optional

from .db import _connect

log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# PAGE-KEYS — единая карта «путь → функциональный блок»
# ═══════════════════════════════════════════════════════════

PAGE_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "key": "atm_map",
        "label": "Карта ATM и инкассация",
        "html": [
            "/dashboard/map.html",
            "/dashboard/incassation.html",
            "/dashboard/import-atms.html",
            "/dashboard/import-branches.html",
        ],
        "api_prefixes": [
            "/api/atms", "/api/branches", "/api/routes", "/api/incassation", "/api/osrm",
            "/api/alerts", "/api/baseline", "/api/atm-monitor",
        ],
    },
    {
        "key": "atm_analytics",
        "label": "Аналитика ATM",
        "html": ["/dashboard/analytics.html"],
        "api_prefixes": ["/api/analytics", "/api/transactions"],
    },
    {
        "key": "treasury",
        "label": "Касса филиалов",
        "html": [
            "/dashboard/branch-cash.html",
            "/dashboard/import-branch-balances.html",
            "/dashboard/import-sqb-rates.html",
        ],
        "api_prefixes": ["/api/branch-balances", "/api/sqb-rates"],
    },
    {
        "key": "hr_cashiers",
        "label": "Кассиры (HR)",
        "html": [
            "/dashboard/cashiers.html",
            "/dashboard/cashier-detail.html",
            "/dashboard/import-cashiers.html",
        ],
        "api_prefixes": ["/api/cashiers"],
    },
]

PAGE_KEYS = [p["key"] for p in PAGE_DEFINITIONS]

# Доступны любому вошедшему независимо от роли — просто хабы/навигация,
# сами по себе не показывают чужих данных.
FREE_HTML_PATHS = {
    "/",
    "/dashboard/index.html",
    "/dashboard/import.html",
    "/tashkent_districts.geojson",
    "/uzbekistan.geojson",
    "/uzbekistan_regional.geojson",
}

# Доступны вообще без логина.
PUBLIC_PATHS = {"/api/auth/login", "/api/health", "/dashboard/login.html"}


def resolve_page_key(path: str) -> Optional[str]:
    """Путь → page-key, или None (например статический .js/.css — не гейтится
    отдельно, реальные данные защищены на уровне /api/*, не отдачи файла)."""
    for pdef in PAGE_DEFINITIONS:
        if path in pdef["html"]:
            return pdef["key"]
        for prefix in pdef["api_prefixes"]:
            if path == prefix or path.startswith(prefix + "/") or path.startswith(prefix + "?"):
                return pdef["key"]
            if path.rstrip("/") == prefix:
                return pdef["key"]
    return None


# ═══════════════════════════════════════════════════════════
# ПАРОЛИ
# ═══════════════════════════════════════════════════════════

_PBKDF2_ITERATIONS = 200_000


def _hash_password(password: str, salt: Optional[str] = None) -> Dict[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), _PBKDF2_ITERATIONS)
    return {"salt": salt, "hash": digest.hex()}


def _verify_password(password: str, salt: str, expected_hash: str) -> bool:
    candidate = _hash_password(password, salt)["hash"]
    return secrets.compare_digest(candidate, expected_hash)


def generate_password(length: int = 12) -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
    return "".join(secrets.choice(alphabet) for _ in range(length))


# ═══════════════════════════════════════════════════════════
# ИНИЦИАЛИЗАЦИЯ + СИДИРОВАНИЕ
# ═══════════════════════════════════════════════════════════

_DEFAULT_ROLES = [
    # (name, label, is_admin, pages)
    ("admin", "Администратор", 1, PAGE_KEYS),
    ("atm_manager", "Инкассация", 0, ["atm_map", "atm_analytics"]),
    ("treasury", "Казначейство", 0, ["treasury"]),
    ("hr_analyst", "HR / Кассиры", 0, ["hr_cashiers"]),
    ("viewer", "Наблюдатель", 0, []),
]


def init_auth_tables() -> None:
    """Создаёт таблицы и (при первом запуске) сеет роли + пользователя admin.

    Файл с паролем пишется ТОЛЬКО после того, как `with _connect()` уже
    полностью завершился (значит транзакция реально закоммичена) — если писать
    его изнутри блока, а процесс убьют раньше commit (например, `--reload`
    перезапускает воркер на файловое изменение прямо во время старта), запись
    в БД откатится, а файл с паролем, который ей уже не соответствует, всё
    равно останется на диске — путаница ровно в духе «в файле один пароль,
    в базе другой»."""
    import json as _json

    seeded_password: Optional[str] = None
    creds_path = None

    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                name       TEXT UNIQUE NOT NULL,
                label      TEXT NOT NULL,
                is_admin   INTEGER NOT NULL DEFAULT 0,
                pages_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                username      TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                password_salt TEXT NOT NULL,
                full_name     TEXT,
                role_id       INTEGER NOT NULL REFERENCES roles(id),
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL DEFAULT (datetime('now'))
            )
        """)

        n_roles = int(conn.execute("SELECT COUNT(*) AS c FROM roles").fetchone()["c"])
        if n_roles == 0:
            for name, label, is_admin, pages in _DEFAULT_ROLES:
                conn.execute(
                    "INSERT INTO roles (name, label, is_admin, pages_json) VALUES (?,?,?,?)",
                    (name, label, is_admin, _json.dumps(pages)),
                )
            log.info("Роли по умолчанию созданы: %s", ", ".join(r[0] for r in _DEFAULT_ROLES))

        n_users = int(conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"])
        if n_users == 0:
            admin_role = conn.execute("SELECT id FROM roles WHERE name = 'admin'").fetchone()
            seeded_password = generate_password()
            creds = _hash_password(seeded_password)
            conn.execute(
                """INSERT INTO users (username, password_hash, password_salt, full_name, role_id, is_active)
                   VALUES ('admin', ?, ?, 'Администратор', ?, 1)""",
                (creds["hash"], creds["salt"], admin_role["id"]),
            )

    # Мы здесь только если `with` выше завершился без исключения — значит
    # commit уже произошёл, и файл будет соответствовать тому, что реально в БД.
    if seeded_password:
        from .config import DATA_DIR
        creds_path = DATA_DIR / "admin_credentials.txt"
        creds_path.write_text(
            f"Логин: admin\nПароль: {seeded_password}\n\n"
            "Смените пароль после первого входа (админ-панель → Пользователи).\n",
            encoding="utf-8",
        )
        log.warning(
            "Создан первый пользователь admin. Пароль сохранён в %s и напечатан ниже — "
            "смените его после первого входа: %s",
            creds_path, seeded_password,
        )


# ═══════════════════════════════════════════════════════════
# ПОЛЬЗОВАТЕЛИ
# ═══════════════════════════════════════════════════════════

def _row_to_user(row: Dict[str, Any]) -> Dict[str, Any]:
    import json as _json
    pages = _json.loads(row.get("pages_json") or "[]")
    return {
        "id": row["id"],
        "username": row["username"],
        "full_name": row.get("full_name"),
        "is_active": bool(row["is_active"]),
        "role_id": row["role_id"],
        "role_name": row.get("role_name"),
        "role_label": row.get("role_label"),
        "is_admin": bool(row.get("is_admin")),
        "pages": pages,
    }


_USER_SELECT = """
    SELECT u.id, u.username, u.full_name, u.is_active, u.role_id,
           r.name AS role_name, r.label AS role_label, r.is_admin, r.pages_json
    FROM users u JOIN roles r ON r.id = u.role_id
"""


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(f"{_USER_SELECT} WHERE u.id = ?", (user_id,)).fetchone()
    return _row_to_user(dict(row)) if row else None


def authenticate(username: str, password: str) -> Optional[Dict[str, Any]]:
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, password_hash, password_salt, is_active FROM users WHERE username = ?",
            (username,),
        ).fetchone()
    if not row or not row["is_active"]:
        return None
    if not _verify_password(password, row["password_salt"], row["password_hash"]):
        return None
    return get_user_by_id(row["id"])


def list_users() -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(f"{_USER_SELECT} ORDER BY u.username").fetchall()
    return [_row_to_user(dict(r)) for r in rows]


def create_user(username: str, password: str, full_name: Optional[str], role_id: int) -> Dict[str, Any]:
    username = username.strip()
    if not username:
        raise ValueError("Логин не может быть пустым")
    if not password or len(password) < 6:
        raise ValueError("Пароль должен быть не короче 6 символов")
    creds = _hash_password(password)
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone()
        if exists:
            raise ValueError(f"Логин {username!r} уже занят")
        role = conn.execute("SELECT id FROM roles WHERE id = ?", (role_id,)).fetchone()
        if not role:
            raise ValueError("Роль не найдена")
        cur = conn.execute(
            """INSERT INTO users (username, password_hash, password_salt, full_name, role_id, is_active)
               VALUES (?,?,?,?,?,1)""",
            (username, creds["hash"], creds["salt"], full_name, role_id),
        )
        new_id = cur.lastrowid
    return get_user_by_id(new_id)


def update_user(
    user_id: int,
    full_name: Optional[str] = None,
    role_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    new_password: Optional[str] = None,
) -> Dict[str, Any]:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise ValueError("Пользователь не найден")
        if full_name is not None:
            conn.execute("UPDATE users SET full_name = ? WHERE id = ?", (full_name, user_id))
        if role_id is not None:
            role = conn.execute("SELECT id FROM roles WHERE id = ?", (role_id,)).fetchone()
            if not role:
                raise ValueError("Роль не найдена")
            conn.execute("UPDATE users SET role_id = ? WHERE id = ?", (role_id, user_id))
        if is_active is not None:
            conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(is_active), user_id))
        if new_password:
            if len(new_password) < 6:
                raise ValueError("Пароль должен быть не короче 6 символов")
            creds = _hash_password(new_password)
            conn.execute(
                "UPDATE users SET password_hash = ?, password_salt = ? WHERE id = ?",
                (creds["hash"], creds["salt"], user_id),
            )
    return get_user_by_id(user_id)


def delete_user(user_id: int) -> None:
    with _connect() as conn:
        remaining_admins = conn.execute(
            """SELECT COUNT(*) AS c FROM users u JOIN roles r ON r.id = u.role_id
               WHERE r.is_admin = 1 AND u.id != ? AND u.is_active = 1""",
            (user_id,),
        ).fetchone()["c"]
        target = conn.execute(
            """SELECT r.is_admin FROM users u JOIN roles r ON r.id = u.role_id WHERE u.id = ?""",
            (user_id,),
        ).fetchone()
        if target and target["is_admin"] and remaining_admins == 0:
            raise ValueError("Нельзя удалить последнего администратора")
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))


# ═══════════════════════════════════════════════════════════
# РОЛИ
# ═══════════════════════════════════════════════════════════

def _row_to_role(row: Dict[str, Any]) -> Dict[str, Any]:
    import json as _json
    return {
        "id": row["id"],
        "name": row["name"],
        "label": row["label"],
        "is_admin": bool(row["is_admin"]),
        "pages": _json.loads(row.get("pages_json") or "[]"),
    }


def list_roles() -> List[Dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute("SELECT * FROM roles ORDER BY id").fetchall()
    return [_row_to_role(dict(r)) for r in rows]


def create_role(name: str, label: str, pages: List[str]) -> Dict[str, Any]:
    import json as _json
    name = name.strip()
    if not name:
        raise ValueError("Имя роли не может быть пустым")
    pages = [p for p in pages if p in PAGE_KEYS]
    with _connect() as conn:
        exists = conn.execute("SELECT 1 FROM roles WHERE name = ?", (name,)).fetchone()
        if exists:
            raise ValueError(f"Роль {name!r} уже существует")
        cur = conn.execute(
            "INSERT INTO roles (name, label, is_admin, pages_json) VALUES (?,?,0,?)",
            (name, label or name, _json.dumps(pages)),
        )
        new_id = cur.lastrowid
    return _row_to_role(_connect_fetch_role(new_id))


def _connect_fetch_role(role_id: int) -> Dict[str, Any]:
    with _connect() as conn:
        return dict(conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone())


def update_role(role_id: int, label: Optional[str] = None, pages: Optional[List[str]] = None) -> Dict[str, Any]:
    import json as _json
    with _connect() as conn:
        row = conn.execute("SELECT * FROM roles WHERE id = ?", (role_id,)).fetchone()
        if not row:
            raise ValueError("Роль не найдена")
        if row["is_admin"] and pages is not None:
            raise ValueError("У роли администратора список страниц не редактируется — у неё всегда полный доступ")
        if label is not None:
            conn.execute("UPDATE roles SET label = ? WHERE id = ?", (label, role_id))
        if pages is not None:
            pages = [p for p in pages if p in PAGE_KEYS]
            conn.execute("UPDATE roles SET pages_json = ? WHERE id = ?", (_json.dumps(pages), role_id))
    return _row_to_role(_connect_fetch_role(role_id))


def delete_role(role_id: int) -> None:
    with _connect() as conn:
        row = conn.execute("SELECT is_admin FROM roles WHERE id = ?", (role_id,)).fetchone()
        if not row:
            raise ValueError("Роль не найдена")
        if row["is_admin"]:
            raise ValueError("Роль администратора нельзя удалить")
        in_use = conn.execute("SELECT COUNT(*) AS c FROM users WHERE role_id = ?", (role_id,)).fetchone()["c"]
        if in_use:
            raise ValueError(f"На эту роль назначено пользователей: {in_use} — сначала переназначьте их")
        conn.execute("DELETE FROM roles WHERE id = ?", (role_id,))
