"""
Bank Intelligence Platform — FastAPI Backend
=============================================

Объединяет два продукта в одном приложении и одной базе SQLite:

  ATM Monitor (реестр банкоматов, остатки, инкассация)
    GET   /api/atms                         → список ATM из БД
    GET   /api/atms/stats                   → статистика по областям/филиалам
    GET   /api/atms/{terminal_id}           → детали ATM
    GET   /api/atms/{terminal_id}/cassettes → кассеты + baseline
    POST  /api/atms/import                  → загрузка XLSX реестра ATM
    POST  /api/atms/import/clear            → очистить реестр ATM
    POST  /api/atms/{terminal_id}/balance   → обновить остаток
    POST  /api/atms/balances/bulk           → массовое обновление остатков
    GET   /api/branches                     → список филиалов
    GET   /api/branches/stats               → статистика по филиалам
    GET   /api/branches/{local_code}        → детали филиала
    POST  /api/branches/import              → загрузка XLSX реестра филиалов
    POST  /api/branches/import/clear        → очистить реестр филиалов
    POST  /api/branches/balances/import     → импорт кассовых остатков (отдельный XLSX)
    POST  /api/branches/balances/clear      → очистить кассовые остатки
    GET   /api/branch-balances/analytics    → сводка кассы по регионам
    POST  /api/cash-equipment/import        → импорт списка кассовой техники (XLSX)
    POST  /api/cash-equipment/clear         → очистить кассовую технику
    GET   /api/cash-equipment               → список (фильтр ?local_code=)
    GET   /api/cash-equipment/branches      → техника, сгруппированная по филиалам
    GET   /api/cash-equipment/replacement   → план замены (износ, дата списания)
    GET   /api/alerts                       → ATM в critical/warning
    GET   /api/baseline                     → сводный отчёт по остаткам
    POST  /api/routes/incassation           → региональные маршруты инкассации
    POST  /api/osrm/route                   → геометрия маршрута по дорогам (OSRM)
    GET   /api/incassation/plan             → прогнозный план инкассации

  Cashier Intelligence (аналитика кассиров)
    POST  /api/cashiers/import              → импорт Excel-отчёта KPI кассиров
    POST  /api/cashiers/import-status       → импорт реестра штата и статусов
    GET   /api/cashiers/analytics           → аналитика и структура операций
    GET   /api/cashiers/{report_id}         → углублённая аналитика кассира

Docs: http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import os
import shutil
import sys
import tempfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Гарантируем, что каталог api/ в PYTHONPATH (модули импортируются как core.*)
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # корень проекта: пакет atm_monitor

import uvicorn
from fastapi import Body, Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

import atm_monitor.api as atm_monitor_api
import atm_monitor.scheduler as atm_collector
from core import atm_live, auth
from core.config import BASE_DIR, SECRET_KEY
from core.db import (
    DatabaseUnavailableError,
    bulk_insert_atms,
    bulk_insert_branches,
    bulk_update_balances,
    count_atms,
    count_branches,
    get_atm,
    get_branch,
    init_db,
    list_atms,
    list_branches,
    list_branches_full,
    list_incassation_trips,
    list_regions,
    replace_incassation_trips,
    truncate_atms,
    truncate_branches,
    update_balance,
)
from core.importer import parse_branches_xlsx, parse_xlsx
from core.branch_balance import (
    balances_by_local_code_map,
    branch_cash_analytics,
    clear_branch_balances,
    get_all_branch_forecasts,
    get_branch_balance_by_local_code,
    get_branch_balance_history,
    list_branch_balances,
    parse_branch_balances_xlsx,
    replace_branch_balances,
)
from core.cash_equipment import (
    cash_equipment_by_branch,
    equipment_replacement_plan,
    clear_cash_equipment,
    list_cash_equipment,
    parse_cash_equipment_xlsx,
    replace_cash_equipment,
)
from core.sqb_rates import (
    latest_rates,
    parse_sqb_rates_xlsx,
    replace_sqb_rates,
)
from core.incassation_router import build_regional_routes, hours_to_low_cash, osrm_route_geometry
from core.cashier_analytics import (
    cashier_analytics,
    cashier_detail,
    parse_cashier_status_xlsx,
    parse_cashiers_xlsx,
    save_cashier_import,
    save_cashier_status_import,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
)
log = logging.getLogger(__name__)


# ── Lifespan ─────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("Инициализация БД Bank Intelligence Platform (SQLite)...")
    try:
        init_db()
    except DatabaseUnavailableError as e:
        # Показываем понятную инструкцию вместо сырого traceback драйвера БД
        # и глушим вывод стектрейса Starlette — он здесь ничего не добавляет.
        print(str(e), file=sys.stderr, flush=True)
        logging.getLogger("uvicorn.error").setLevel(logging.CRITICAL)
        os._exit(1)
    log.info("БД готова. ATM в базе: %d, филиалов: %d", count_atms(), count_branches())
    atm_collector.start_background()   # atm_monitor: почасовой опрос BTech в фоне
    yield
    atm_collector.stop_background()
    log.info("Сервер остановлен.")


# ── FastAPI App ──────────────────────────────────────────────

app = FastAPI(
    title="Bank Intelligence Platform API",
    description=(
        "Единая платформа: мониторинг банкоматов и инкассации + "
        "аналитика показателей кассиров"
    ),
    version="3.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(atm_monitor_api.router)

dashboard_dir = BASE_DIR / "dashboard"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")

admin_dir = BASE_DIR / "admin"
if admin_dir.exists():
    app.mount("/admin", StaticFiles(directory=str(admin_dir), html=True), name="admin")


@app.get("/", include_in_schema=False)
async def root():
    return RedirectResponse(url="/dashboard/index.html")


@app.get("/api/health", summary="Проверка живости сервиса")
async def health():
    return {
        "ok": True,
        "atms": count_atms(),
        "branches": count_branches(),
        "modules": ["atm-monitor", "cashier-intelligence"],
    }


@app.get("/api/atm-monitor/status", summary="Статус сборщика atm_monitor (последний опрос BTech)")
async def atm_monitor_status():
    return atm_live.collector_status()


# ═══════════════════════════════════════════════════════════
# АВТОРИЗАЦИЯ / РОЛИ / ДОСТУПЫ
# ═══════════════════════════════════════════════════════════

def _current_user(request: Request) -> Optional[Dict[str, Any]]:
    uid = request.session.get("user_id")
    if not uid:
        return None
    user = auth.get_user_by_id(uid)
    if not user or not user["is_active"]:
        return None
    return user


def _public_user(user: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "username": user["username"],
        "full_name": user["full_name"],
        "role_name": user["role_name"],
        "role_label": user["role_label"],
        "is_admin": user["is_admin"],
        "pages": user["pages"],
    }


def require_admin(request: Request) -> Dict[str, Any]:
    user = _current_user(request)
    if not user:
        raise HTTPException(401, "Не авторизован")
    if not user["is_admin"]:
        raise HTTPException(403, "Требуются права администратора")
    return user


def _no_cache(path: str, response):
    """Страницы/скрипты дашборда браузер должен перепроверять каждый раз,
    иначе после обновления кода показывается старая закэшированная версия."""
    if path.startswith("/dashboard/") or path == "/":
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    """Один гейт перед всем приложением — до любой страницы и любого API-ответа.

    Порядок регистрации middleware важен: SessionMiddleware добавлен НИЖЕ по
    файлу (после этого декоратора), поэтому оборачивает auth_gate снаружи —
    request.session уже заполнен из подписанной cookie к моменту, когда этот
    код его читает (Starlette оборачивает в обратном порядке регистрации)."""
    path = request.url.path

    if path in auth.PUBLIC_PATHS:
        return await call_next(request)

    is_api = path.startswith("/api/")
    user = _current_user(request)

    if not user:
        if is_api:
            return JSONResponse({"detail": "Не авторизован"}, status_code=401)
        return RedirectResponse(url=f"/dashboard/login.html?next={path}", status_code=303)

    if path.startswith("/admin"):
        if not user["is_admin"]:
            if is_api:
                return JSONResponse({"detail": "Доступ запрещён"}, status_code=403)
            return RedirectResponse(url="/dashboard/index.html?denied=1", status_code=303)
        return await call_next(request)

    if user["is_admin"] or path in auth.FREE_HTML_PATHS:
        return _no_cache(path, await call_next(request))

    page_key = auth.resolve_page_key(path)
    if page_key is None:
        # Не размечено (например статический .js/.css) — реальные данные
        # защищены на уровне /api/*, отдачу самого файла не гейтим отдельно.
        return _no_cache(path, await call_next(request))

    if page_key in (user.get("pages") or []):
        return _no_cache(path, await call_next(request))

    if is_api:
        return JSONResponse({"detail": "Доступ запрещён"}, status_code=403)
    return RedirectResponse(url="/dashboard/index.html?denied=1", status_code=303)


app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
    session_cookie="bip_session",
    max_age=60 * 60 * 24 * 7,  # 7 дней
)


class LoginRequest(BaseModel):
    username: str
    password: str


@app.post("/api/auth/login", summary="Вход")
async def login(payload: LoginRequest, request: Request):
    user = auth.authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(401, "Неверный логин или пароль")
    request.session.clear()
    request.session["user_id"] = user["id"]
    return {"ok": True, "user": _public_user(user)}


@app.post("/api/auth/logout", summary="Выход")
async def logout(request: Request):
    request.session.clear()
    return {"ok": True}


@app.get("/api/auth/me", summary="Текущий пользователь")
async def me(request: Request):
    user = _current_user(request)
    if not user:
        raise HTTPException(401, "Не авторизован")
    return _public_user(user)


@app.get("/api/admin/pages", summary="Функциональные блоки для чекбоксов ролей")
async def admin_list_pages(_: Dict[str, Any] = Depends(require_admin)):
    return {"pages": [{"key": p["key"], "label": p["label"]} for p in auth.PAGE_DEFINITIONS]}


@app.get("/api/admin/users", summary="Список пользователей")
async def admin_list_users(_: Dict[str, Any] = Depends(require_admin)):
    return {"users": auth.list_users()}


class CreateUserRequest(BaseModel):
    username: str
    password: str
    full_name: Optional[str] = None
    role_id: int


@app.post("/api/admin/users", summary="Создать пользователя")
async def admin_create_user(payload: CreateUserRequest, _: Dict[str, Any] = Depends(require_admin)):
    try:
        return auth.create_user(payload.username, payload.password, payload.full_name, payload.role_id)
    except ValueError as e:
        raise HTTPException(400, str(e))


class UpdateUserRequest(BaseModel):
    full_name: Optional[str] = None
    role_id: Optional[int] = None
    is_active: Optional[bool] = None
    new_password: Optional[str] = None


@app.patch("/api/admin/users/{user_id}", summary="Изменить пользователя")
async def admin_update_user(user_id: int, payload: UpdateUserRequest, _: Dict[str, Any] = Depends(require_admin)):
    try:
        return auth.update_user(user_id, payload.full_name, payload.role_id, payload.is_active, payload.new_password)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/admin/users/{user_id}", summary="Удалить пользователя")
async def admin_delete_user(user_id: int, _: Dict[str, Any] = Depends(require_admin)):
    try:
        auth.delete_user(user_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


@app.get("/api/admin/roles", summary="Список ролей")
async def admin_list_roles(_: Dict[str, Any] = Depends(require_admin)):
    return {"roles": auth.list_roles()}


class CreateRoleRequest(BaseModel):
    name: str
    label: str
    pages: List[str] = []


@app.post("/api/admin/roles", summary="Создать роль")
async def admin_create_role(payload: CreateRoleRequest, _: Dict[str, Any] = Depends(require_admin)):
    try:
        return auth.create_role(payload.name, payload.label, payload.pages)
    except ValueError as e:
        raise HTTPException(400, str(e))


class UpdateRoleRequest(BaseModel):
    label: Optional[str] = None
    pages: Optional[List[str]] = None


@app.patch("/api/admin/roles/{role_id}", summary="Изменить роль")
async def admin_update_role(role_id: int, payload: UpdateRoleRequest, _: Dict[str, Any] = Depends(require_admin)):
    try:
        return auth.update_role(role_id, payload.label, payload.pages)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.delete("/api/admin/roles/{role_id}", summary="Удалить роль")
async def admin_delete_role(role_id: int, _: Dict[str, Any] = Depends(require_admin)):
    try:
        auth.delete_role(role_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True}


# ═══════════════════════════════════════════════════════════
# ATM — СПИСОК / ДЕТАЛИ
# ═══════════════════════════════════════════════════════════

@app.get("/api/atms", summary="Список ATM (с фильтрами)")
async def get_atms(
    region: Optional[str] = Query(None, description="Область"),
    branch: Optional[str] = Query(None, description="Филиал"),
    status: Optional[str] = Query(None, pattern="^(ok|warning|critical|unknown)$"),
    limit: int = Query(1000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
):
    rows = list_atms(region=region, branch=branch, status=status, limit=limit, offset=offset)
    return {
        "atms": rows,
        "count": len(rows),
        "total_in_db": count_atms(),
        "filters": {"region": region, "branch": branch, "status": status},
    }


@app.get("/api/atms/stats", summary="Статистика по областям/филиалам")
async def get_stats():
    return {
        "total": count_atms(),
        "by_region": list_regions(),
        "by_branch": list_branches(),
    }


@app.get("/api/atms/{terminal_id}", summary="Детали ATM по Terminal ID")
async def get_atm_detail(terminal_id: str):
    atm = get_atm(terminal_id)
    if not atm:
        raise HTTPException(404, f"ATM с terminal_id={terminal_id!r} не найден")
    return atm


# ═══════════════════════════════════════════════════════════
# КАССЕТЫ + BASELINE
# ═══════════════════════════════════════════════════════════

CASSETTE_MAX_COUNT = 2000  # физический потолок купюр на одну кассету (оценка без реальных данных)


@app.get("/api/atms/{terminal_id}/cassettes", summary="Кассеты + рекомендация по загрузке")
async def get_atm_cassettes(terminal_id: str):
    """
    Если ATM опрашивается сборщиком atm_monitor — отдаём реальные кассеты
    (номинал/количество/статус OK-LOW-MISSING на момент последнего опроса).
    Иначе — оценка: текущий остаток разбивается на 4 номинала пропорционально
    типичной доле в обороте (source="estimated", это не измерение).
    """
    atm = get_atm(terminal_id)
    if not atm:
        raise HTTPException(404, f"ATM {terminal_id!r} не найден")

    # get_atm() уже подмешал реальные кассеты (см. core.db._apply_live_state);
    # отдельный запрос к atm_monitor тут не нужен.
    live_cassettes = atm.get("cassettes") or []
    if live_cassettes:
        return {
            "atm_id": terminal_id,
            "address": atm.get("address"),
            "region": atm.get("region"),
            "branch": atm.get("branch"),
            "current_balance": atm.get("balance"),
            "balance_polled_at": atm.get("balance_polled_at"),
            "source": "live",
            "cassettes": live_cassettes,
        }

    balance = atm.get("balance")
    capacity = atm.get("capacity") or 400_000_000

    if balance is None:
        return {
            "atm_id": terminal_id,
            "address": atm.get("address"),
            "region": atm.get("region"),
            "branch": atm.get("branch"),
            "current_balance": None,
            "capacity": capacity,
            "source": "estimated",
            "cassettes": {
                "denominations": [10_000, 50_000, 100_000, 200_000],
                "by_denom": {
                    str(d): {"count": 0, "balance": 0, "capacity": CASSETTE_MAX_COUNT, "fill_pct": 0}
                    for d in (10_000, 50_000, 100_000, 200_000)
                },
                "total_balance": 0,
                "total_fill_pct": 0,
                "value_to_fill": capacity,
            },
            "comment": "Баланс не загружен. Обновите через /api/atms/{id}/balance.",
        }

    # Оценка (нет реальных кассет от atm_monitor): раскладываем известный остаток
    # по 4 номиналам пропорционально типичной доле в обороте, но не больше
    # CASSETTE_MAX_COUNT купюр в одной кассете — это физический потолок реальной
    # кассеты. Итоговый баланс кассет — не сам исходный остаток, а честная сумма
    # «количество купюр × номинал» после этого ограничения.
    share = {10_000: 0.10, 50_000: 0.45, 100_000: 0.30, 200_000: 0.15}
    by_denom: Dict[str, Dict[str, Any]] = {}
    for d, s in share.items():
        alloc = int(balance * s)
        count = min(alloc // d, CASSETTE_MAX_COUNT)
        by_denom[str(d)] = {
            "count": int(count),
            "balance": int(count * d),
            "capacity": CASSETTE_MAX_COUNT,
            "fill_pct": round(count / CASSETTE_MAX_COUNT * 100, 1),
        }

    total_cassette_value = sum(int(c["balance"]) for c in by_denom.values())
    value_to_fill = max(0, capacity - total_cassette_value)

    return {
        "atm_id": terminal_id,
        "address": atm.get("address"),
        "region": atm.get("region"),
        "branch": atm.get("branch"),
        "current_balance": balance,
        "capacity": capacity,
        "balance_pct": atm.get("balance_pct"),
        "status": atm.get("status"),
        "source": "estimated",
        "cassettes": {
            "denominations": [10_000, 50_000, 100_000, 200_000],
            "by_denom": by_denom,
            "total_balance": total_cassette_value,
            "total_fill_pct": round(total_cassette_value / capacity * 100, 1) if capacity else 0,
            "value_to_fill": value_to_fill,
        },
        "refill_needed": value_to_fill,
    }


@app.get("/api/atms/{terminal_id}/history", summary="Реальная история остатка ATM (для прогноза)")
async def get_atm_history(
    terminal_id: str,
    days: int = Query(30, ge=1, le=180, description="Сколько дней истории отдать"),
):
    """
    Реальный почасовой ряд остатка UZS из atm_monitor (сборщик monitoring.btech.uz).
    Пусто, если этот ATM не опрашивается сборщиком или он сейчас недоступен.
    """
    atm = get_atm(terminal_id)
    live_tid = (atm.get("live_tid") if atm else None) or terminal_id
    history = atm_live.balance_history_by_tid(live_tid, days=days)
    return {"terminal_id": terminal_id, "days": days, "history": history, "count": len(history)}


# ═══════════════════════════════════════════════════════════
# ИМПОРТ ATM (XLSX)
# ═══════════════════════════════════════════════════════════

@app.post("/api/atms/import", summary="Импорт ATM из XLSX")
async def import_atms(
    file: UploadFile = File(..., description="XLSX с реестром ATM"),
    replace: bool = Query(False, description="Если True — очистить таблицу перед импортом"),
):
    """
    Ожидаемая структура XLSX:
      A — Номер банкомата, B — Номер по филиалам, C — Локал код, D — Область,
      E — Филиал, F — Модель, G — Тип сети, H — Серийный номер, I — Merchant ID,
      J — Terminal ID, K — Адрес, L — Широта, M — Долгота
    """
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Ожидается .xlsx файл")

    tmp_dir = tempfile.mkdtemp(prefix="atm_import_")
    tmp_path = os.path.join(tmp_dir, file.filename)
    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        try:
            parsed = parse_xlsx(tmp_path)
        except ValueError as e:
            raise HTTPException(400, str(e))

        deleted = truncate_atms() if replace else 0
        stats = bulk_insert_atms(parsed["records"])

        return {
            "ok": True,
            "filename": file.filename,
            "header_row": parsed["header_row"],
            "columns_detected": parsed["columns"],
            "total_rows_in_file": parsed["total_rows"],
            "deleted_before_import": deleted,
            "imported": stats["inserted"],
            "updated": stats["updated"],
            "skipped_no_terminal_id": stats["skipped"],
            "validation_errors": parsed["errors"][:50],
            "validation_errors_count": len(parsed["errors"]),
            "atms_in_db_after": count_atms(),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/atms/import/clear", summary="Очистить все ATM из БД")
async def clear_atms():
    deleted = truncate_atms()
    return {"ok": True, "deleted": deleted, "atms_in_db": count_atms()}


# ═══════════════════════════════════════════════════════════
# ФИЛИАЛЫ
# ═══════════════════════════════════════════════════════════

@app.get("/api/branches", summary="Список филиалов (с фильтрами)")
async def get_branches(
    region: Optional[str] = Query(None, description="Регион"),
    incassation: Optional[int] = Query(None, ge=0, le=1, description="0 — без инкассации, 1 — с инкассацией"),
    limit: int = Query(2000, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    with_balance: bool = Query(True, description="Прикрепить кассовый остаток, если загружен"),
):
    rows = list_branches_full(region=region, incassation=incassation, limit=limit, offset=offset)
    if with_balance:
        bal_map = balances_by_local_code_map()
        forecasts = get_all_branch_forecasts()
        for b in rows:
            code = str(b.get("local_code") or "")
            if code and code in bal_map:
                cash = dict(bal_map[code])
                if code in forecasts:
                    cash["forecast"] = forecasts[code]
                b["cash"] = cash
    return {
        "branches": rows,
        "count": len(rows),
        "total_in_db": count_branches(),
        "filters": {"region": region, "incassation": incassation},
    }


@app.get("/api/branches/stats", summary="Статистика по филиалам")
async def get_branches_stats():
    all_branches = list_branches_full(limit=5000)
    with_inc = sum(1 for b in all_branches if b.get("incassation") == 1)
    regions: Dict[str, int] = {}
    for b in all_branches:
        r = b.get("region") or "Не указан"
        regions[r] = regions.get(r, 0) + 1
    return {
        "total": count_branches(),
        "with_incassation": with_inc,
        "without_incassation": len(all_branches) - with_inc,
        "by_region": [{"region": r, "count": c} for r, c in sorted(regions.items(), key=lambda x: -x[1])],
    }


@app.get("/api/branches/{local_code}", summary="Детали филиала по локал коду")
async def get_branch_detail(local_code: str):
    branch = get_branch(local_code)
    if not branch:
        raise HTTPException(404, f"Филиал с local_code={local_code!r} не найден")
    cash = get_branch_balance_by_local_code(local_code)
    if cash:
        branch["cash"] = cash
    return branch


@app.get("/api/branches/{local_code}/balance", summary="Кассовый остаток филиала")
async def get_branch_cash_balance(local_code: str):
    cash = get_branch_balance_by_local_code(local_code)
    if not cash:
        raise HTTPException(404, f"Остаток для филиала {local_code!r} не найден — загрузите Excel остатков")
    return cash


@app.get("/api/branch-balances", summary="Все загруженные остатки филиалов")
async def get_all_branch_balances():
    rows = list_branch_balances()
    return {"balances": rows, "count": len(rows)}


@app.get("/api/branch-balances/analytics", summary="Сводка кассы: всего и по регионам")
async def get_branch_cash_analytics():
    return branch_cash_analytics()


@app.get("/api/branch-balances/history", summary="История остатков по филиалам (снимок на каждый импорт Excel)")
async def get_branch_balance_history_endpoint(
    local_code: Optional[str] = Query(None, description="Фильтр по коду филиала"),
):
    rows = get_branch_balance_history(local_code)
    return {"history": rows, "count": len(rows)}


@app.get("/api/sqb-rates", summary="SQB xarid/sotuv kurslari")
async def get_sqb_rates():
    return latest_rates()


@app.post("/api/sqb-rates/import", summary="SQB kurslarini Exceldan yuklash (xarid/sotuv)")
async def import_sqb_rates(
    file: UploadFile = File(..., description="XLSX: sana, Valyuta nomi, Xarid, Sotuv"),
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Ожидается .xlsx файл")
    tmp_dir = tempfile.mkdtemp(prefix="sqb_rates_")
    tmp_path = os.path.join(tmp_dir, file.filename)
    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            parsed = parse_sqb_rates_xlsx(tmp_path)
        except ValueError as e:
            raise HTTPException(400, str(e))
        stats = replace_sqb_rates(parsed["records"])
        return {
            "ok": True,
            "filename": file.filename,
            "header_row": parsed["header_row"],
            "dates": parsed["dates"],
            "imported": stats["saved"],
            "validation_errors": parsed["errors"][:50],
            "validation_errors_count": len(parsed["errors"]),
            "current": latest_rates(),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/branches/balances/import", summary="Импорт кассовых остатков филиалов (отдельный XLSX)")
async def import_branch_balances(
    file: UploadFile = File(..., description="XLSX: Код БХМ, номи, Сўм, лимиты, валюты"),
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Ожидается .xlsx файл")

    tmp_dir = tempfile.mkdtemp(prefix="branch_bal_import_")
    tmp_path = os.path.join(tmp_dir, file.filename)
    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            parsed = parse_branch_balances_xlsx(tmp_path)
        except ValueError as e:
            raise HTTPException(400, str(e))
        stats = replace_branch_balances(parsed["records"])
        return {
            "ok": True,
            "filename": file.filename,
            "header_row": parsed["header_row"],
            "columns_detected": parsed["columns"],
            "total_rows_in_file": parsed["total_rows"],
            "imported": stats["saved"],
            "matched_to_branches": stats["matched_to_branches"],
            "unmatched": stats["unmatched"],
            "validation_errors": parsed["errors"][:50],
            "validation_errors_count": len(parsed["errors"]),
            "note": "Отдельный парсер — реестр филиалов (координаты) не изменяется.",
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/branches/balances/clear", summary="Очистить все кассовые остатки филиалов")
async def clear_branch_cash_balances():
    deleted = clear_branch_balances()
    return {"ok": True, "deleted": deleted, "balances_in_db": 0}


@app.get("/api/cash-equipment", summary="Кассовая техника (kassa jihozlari)")
async def get_cash_equipment(local_code: Optional[str] = Query(None, description="Локал код филиала")):
    rows = list_cash_equipment(local_code)
    return {"items": rows, "count": len(rows)}


@app.get("/api/cash-equipment/branches", summary="Кассовая техника по филиалам (для карты)")
async def get_cash_equipment_branches():
    return cash_equipment_by_branch()


@app.get("/api/cash-equipment/replacement", summary="План замены: износ и дата списания техники")
async def get_cash_equipment_replacement(
    kind: Optional[str] = Query("Mashinka", description="Лист Excel (вид техники); пусто — вся техника"),
):
    return equipment_replacement_plan(kind or None)


@app.post("/api/cash-equipment/import", summary="Импорт списка кассовой техники (XLSX)")
async def import_cash_equipment(
    file: UploadFile = File(..., description="XLSX: локал код, бўлинма номи, асосий восита номи, инвентар рақами …"),
):
    if not file.filename or not file.filename.lower().endswith((".xlsx", ".xlsm")):
        raise HTTPException(400, "Ожидается .xlsx файл")
    tmp_dir = tempfile.mkdtemp(prefix="cash_eq_import_")
    tmp_path = os.path.join(tmp_dir, file.filename)
    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        try:
            parsed = parse_cash_equipment_xlsx(tmp_path)
        except ValueError as e:
            raise HTTPException(400, str(e))
        stats = replace_cash_equipment(parsed["records"])
        return {
            "ok": True,
            "filename": file.filename,
            "by_sheet": parsed["by_sheet"],
            "total_rows_in_file": parsed["total_rows"],
            "imported": stats["saved"],
            "matched_to_branches": stats["matched"],
            "unmatched": stats["unmatched"],
            "branches_matched": stats["branches_matched"],
            "validation_errors": parsed["errors"][:50],
            "validation_errors_count": len(parsed["errors"]),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/cash-equipment/clear", summary="Очистить кассовую технику")
async def clear_cash_equipment_endpoint():
    return {"ok": True, "deleted": clear_cash_equipment()}


@app.post("/api/branches/import", summary="Импорт филиалов из XLSX")
async def import_branches(
    file: UploadFile = File(..., description="XLSX с реестром филиалов"),
    replace: bool = Query(False, description="Если True — очистить таблицу перед импортом"),
):
    if not file.filename or not file.filename.lower().endswith(".xlsx"):
        raise HTTPException(400, "Ожидается .xlsx файл")

    tmp_dir = tempfile.mkdtemp(prefix="branch_import_")
    tmp_path = os.path.join(tmp_dir, file.filename)
    try:
        with open(tmp_path, "wb") as f:
            shutil.copyfileobj(file.file, f)

        try:
            parsed = parse_branches_xlsx(tmp_path)
        except ValueError as e:
            raise HTTPException(400, str(e))

        deleted = truncate_branches() if replace else 0
        stats = bulk_insert_branches(parsed["records"])
        without_coordinates = parsed.get("without_coordinates", 0)
        warning = None
        if without_coordinates:
            warning = (
                f"У {without_coordinates} из {len(parsed['records'])} филиалов нет координат "
                "(lat/lon) — на карте они не отобразятся. Проверьте колонки широты и долготы "
                "и загрузите файл снова с галочкой «Очистить таблицу»."
            )

        return {
            "ok": True,
            "filename": file.filename,
            "header_row": parsed["header_row"],
            "columns_detected": parsed["columns"],
            "total_rows_in_file": parsed["total_rows"],
            "deleted_before_import": deleted,
            "imported": stats["inserted"],
            "updated": stats["updated"],
            "skipped_no_local_code": stats["skipped"],
            "without_coordinates": without_coordinates,
            "warning": warning,
            "validation_errors": parsed["errors"][:50],
            "validation_errors_count": len(parsed["errors"]),
            "branches_in_db_after": count_branches(),
        }
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/branches/import/clear", summary="Очистить все филиалы из БД")
async def clear_branches():
    deleted = truncate_branches()
    return {"ok": True, "deleted": deleted, "branches_in_db": count_branches()}


# ═══════════════════════════════════════════════════════════
# БАЛАНСЫ
# ═══════════════════════════════════════════════════════════

class BalanceUpdate(BaseModel):
    balance: int


class BulkBalances(BaseModel):
    updates: List[Dict[str, Any]]   # [{"terminal_id": "...", "balance": 123}, ...]


@app.post("/api/atms/{terminal_id}/balance", summary="Обновить остаток ATM")
async def set_balance(terminal_id: str, payload: BalanceUpdate):
    if payload.balance < 0:
        raise HTTPException(400, "balance должен быть >= 0")
    if not update_balance(terminal_id, payload.balance):
        raise HTTPException(404, f"ATM {terminal_id!r} не найден")
    return {"ok": True, "atm": get_atm(terminal_id)}


@app.post("/api/atms/balances/bulk", summary="Массовое обновление остатков")
async def set_balances_bulk(payload: BulkBalances):
    return {"ok": True, **bulk_update_balances(payload.updates)}


# ═══════════════════════════════════════════════════════════
# ALERTS / BASELINE
# ═══════════════════════════════════════════════════════════

@app.get("/api/alerts", summary="ATM в статусе critical/warning")
async def get_alerts(limit: int = Query(200, ge=1, le=2000)):
    alerts = [a for a in list_atms(limit=limit) if a.get("status") in ("critical", "warning")]
    alerts.sort(key=lambda x: (x.get("balance_pct") or 999))
    return {"alerts": alerts, "count": len(alerts)}


def _aggregate_by_region(atms: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    agg: Dict[str, Dict[str, Any]] = {}
    for a in atms:
        r = a.get("region") or "Не указана"
        bucket = agg.setdefault(r, {
            "region": r, "count": 0, "total_capacity": 0, "total_balance": 0,
            "critical": 0, "warning": 0, "ok": 0, "no_data": 0,
        })
        bucket["count"] += 1
        bucket["total_capacity"] += a.get("capacity") or 0
        bucket["total_balance"] += a.get("balance") or 0
        st = a.get("status")
        if st in ("critical", "warning", "ok"):
            bucket[st] += 1
        else:
            bucket["no_data"] += 1
    out = []
    for r in agg.values():
        r["fill_pct"] = round(r["total_balance"] / (r["total_capacity"] or 1) * 100, 1)
        out.append(r)
    out.sort(key=lambda x: x["count"], reverse=True)
    return out


@app.get("/api/baseline", summary="Сводный отчёт по остаткам")
async def get_baseline():
    all_atms = list_atms(limit=5000)
    total_capacity = sum(a.get("capacity") or 0 for a in all_atms)
    total_balance = sum(a.get("balance") or 0 for a in all_atms)
    return {
        "summary": {
            "total_atms": len(all_atms),
            "total_capacity": total_capacity,
            "total_balance": total_balance,
            "fill_pct": round(total_balance / total_capacity * 100, 1) if total_capacity else 0,
            "no_data": sum(1 for a in all_atms if a.get("balance") is None),
            "critical": sum(1 for a in all_atms if a.get("status") == "critical"),
            "warning": sum(1 for a in all_atms if a.get("status") == "warning"),
            "ok": sum(1 for a in all_atms if a.get("status") == "ok"),
        },
        "by_region": _aggregate_by_region(all_atms),
    }


# ═══════════════════════════════════════════════════════════
# ИНКАССАЦИЯ
# ═══════════════════════════════════════════════════════════

class IncassationRouteRequest(BaseModel):
    persist: bool = True


@app.post("/api/routes/incassation", summary="Маршруты: только ATM ниже нормы, свой вилоят")
async def regional_incassation_route(
    status: str = Query("warning", pattern="^(critical|warning|all)$"),
    speed_kmh: int = Query(30, ge=10, le=80),
    max_stops: int = Query(12, ge=1, le=200),
    snap_roads: bool = Query(True),
    payload: Optional[IncassationRouteRequest] = Body(None),
):
    req = payload or IncassationRouteRequest()
    atms = list_atms(limit=5000)  # уже с реальным балансом из atm_monitor, см. core.db
    branches = list_branches_full(incassation=1, limit=5000)
    result = build_regional_routes(
        atms, branches, status,
        speed_kmh=speed_kmh, max_stops=max_stops, snap_roads=snap_roads,
    )
    if req.persist:
        result["saved_to_calendar"] = replace_incassation_trips(result.get("cars") or [])
    else:
        result["saved_to_calendar"] = 0
    return result


@app.get("/api/incassation/calendar", summary="Сохранённые рейсы инкассации для календаря")
async def incassation_calendar():
    trips = list_incassation_trips()
    events = []
    for t in trips:
        due = f"{t.get('planned_date')}T09:00:00+05:00"
        events.append({
            "id": t.get("id"),
            "due_at": due,
            "planned_date": t.get("planned_date"),
            "region": t.get("region"),
            "address": t.get("label") or t.get("branch_address"),
            "terminal_id": t.get("branch_local_code"),
            "priority": t.get("priority") or "planned",
            "recommended_refill": t.get("refill_total") or 0,
            "stops": t.get("stops") or [],
            "stop_count": len(t.get("stops") or []),
            "distance_km": t.get("distance_km"),
            "est_time_min": t.get("est_time_min"),
            "label": t.get("label"),
            "branch_address": t.get("branch_address"),
            "branch_lat": t.get("branch_lat"),
            "branch_lon": t.get("branch_lon"),
            "geometry": t.get("geometry") or [],
            "type": "route",
        })
    return {"events": events, "count": len(events), "trips": trips}


@app.get("/api/incassation/trips/{trip_id}", summary="Один сохранённый рейс для карты")
async def incassation_trip(trip_id: int):
    for t in list_incassation_trips():
        if int(t.get("id") or 0) == int(trip_id):
            return t
    raise HTTPException(404, f"Рейс {trip_id} не найден")


class OsrmRouteRequest(BaseModel):
    points: List[Dict[str, float]]


@app.post("/api/osrm/route", summary="Геометрия маршрута по дорогам (OSRM)")
async def osrm_route(payload: OsrmRouteRequest):
    geom, dist = osrm_route_geometry(payload.points)
    if not geom:
        raise HTTPException(502, "OSRM недоступен")
    return {"geometry": geom, "distance_km": round(float(dist or 0), 2), "provider": "osrm"}


@app.get("/api/incassation/plan", summary="Прогнозный план инкассации")
async def incassation_plan(days: int = Query(2, ge=1, le=14)):
    atms = list_atms(limit=5000)
    now = datetime.now(timezone.utc)
    planned = []
    for a in atms:
        hours = hours_to_low_cash(a)
        if hours is None or hours > days * 24:
            continue
        cap, bal = a.get("capacity") or 400_000_000, a.get("balance")
        planned.append({
            "terminal_id": a["terminal_id"],
            "address": a.get("address"),
            "region": a.get("region"),
            "due_at": (now + timedelta(hours=hours)).isoformat(),
            "hours_to_low_cash": hours,
            "priority": "critical" if hours < 12 else "high" if hours < 24 else "planned",
            "recommended_refill": round(max(0, cap * 0.8 - (bal or 0))),
        })
    planned.sort(key=lambda x: x["hours_to_low_cash"])
    return {
        "generated_at": now.isoformat(),
        "horizon_days": days,
        "planned_atms": planned,
        "count": len(planned),
        "note": "Оценка по текущему остатку (без истории транзакций). Календарь рейсов — POST /api/routes/incassation.",
    }


# ═══════════════════════════════════════════════════════════
# CASHIER INTELLIGENCE
# ═══════════════════════════════════════════════════════════

@app.post("/api/cashiers/import", summary="Импорт отчёта KPI кассиров из XLSX/CSV")
async def import_cashiers(file: UploadFile = File(..., description="Excel-отчёт кассиров")):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла не указано.")

    tmp_dir = tempfile.mkdtemp(prefix="cashier_import_")
    tmp_path = Path(tmp_dir) / file.filename
    try:
        tmp_path.write_bytes(await file.read())
        try:
            parsed = parse_cashiers_xlsx(tmp_path)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return {"ok": True, "filename": file.filename, **save_cashier_import(file.filename, parsed)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.post("/api/cashiers/import-status", summary="Импорт реестра штата и статусов кассиров")
async def import_cashier_status(file: UploadFile = File(..., description="Excel-реестр штата кассиров")):
    if not file.filename:
        raise HTTPException(status_code=400, detail="Имя файла не указано.")

    tmp_dir = tempfile.mkdtemp(prefix="cashier_status_import_")
    tmp_path = Path(tmp_dir) / file.filename
    try:
        tmp_path.write_bytes(await file.read())
        try:
            parsed = parse_cashier_status_xlsx(tmp_path)
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return {"ok": True, "filename": file.filename, **save_cashier_status_import(file.filename, parsed)}
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


@app.get("/api/cashiers/analytics", summary="KPI и структура операций кассиров")
async def get_cashier_analytics(
    import_id: Optional[int] = Query(None, description="ID импорта KPI (None = последний)"),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=200),
    role: Optional[str] = Query(None, description="Фильтр по роли: back / front / mixed"),
    search: Optional[str] = Query(None, description="Поиск по ФИО/табелю"),
    position: Optional[str] = Query(None, description="Фильтр по лавозим/должности"),
    status: Optional[str] = Query(None, description="Фильтр по статусу (работает/отпуск/больничный...)"),
    branch: Optional[str] = Query(None, description="Фильтр по филиалу/БХМ"),
):
    return cashier_analytics(import_id, page, page_size, role, search, position, status, branch)


@app.get("/api/cashiers/{report_id}", summary="Углублённая аналитика одного кассира")
async def get_cashier_detail(report_id: int):
    item = cashier_detail(report_id)
    if not item:
        raise HTTPException(status_code=404, detail="Запись кассира не найдена.")
    return item


# ═══════════════════════════════════════════════════════════
# GEOJSON
# ═══════════════════════════════════════════════════════════

def _geojson_response(name: str) -> FileResponse:
    geo_path = BASE_DIR / name
    if not geo_path.exists():
        raise HTTPException(404, "GeoJSON не найден")
    return FileResponse(str(geo_path), media_type="application/geo+json")


@app.get("/tashkent_districts.geojson", summary="Границы районов Ташкента")
async def get_tashkent_geojson():
    return _geojson_response("tashkent_districts.geojson")


@app.get("/uzbekistan_regional.geojson", summary="Границы областей Узбекистана")
async def get_uzb_regional_geojson():
    return _geojson_response("uzbekistan_regional.geojson")


@app.get("/uzbekistan.geojson", summary="Граница Узбекистана")
async def get_uzb_geojson():
    return _geojson_response("uzbekistan.geojson")


# ═══════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    uvicorn.run("api.main:app", host="0.0.0.0", port=8000, reload=False, log_level="info")
