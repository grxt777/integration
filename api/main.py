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
    GET   /api/alerts                       → ATM в critical/warning
    GET   /api/baseline                     → сводный отчёт по остаткам
    POST  /api/routes/incassation           → региональные маршруты инкассации
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

import uvicorn
from fastapi import Body, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from core.config import BASE_DIR
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
    get_branch_balance_by_local_code,
    list_branch_balances,
    parse_branch_balances_xlsx,
    replace_branch_balances,
)
from core.sqb_rates import (
    latest_rates,
    parse_sqb_rates_xlsx,
    replace_sqb_rates,
)
from core.incassation_router import apply_live_states, build_regional_routes, hours_to_low_cash
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
    yield
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

dashboard_dir = BASE_DIR / "dashboard"
if dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(dashboard_dir), html=True), name="dashboard")


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

@app.get("/api/atms/{terminal_id}/cassettes", summary="Кассеты + рекомендация по загрузке")
async def get_atm_cassettes(terminal_id: str):
    """
    Кассеты — логическая модель: текущий остаток разбивается на 4 номинала
    (10/50/100/200 тыс. UZS) пропорционально доле в обороте.
    """
    atm = get_atm(terminal_id)
    if not atm:
        raise HTTPException(404, f"ATM {terminal_id!r} не найден")

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
            "cassettes": {
                "denominations": [10_000, 50_000, 100_000, 200_000],
                "by_denom": {
                    str(d): {"count": 0, "balance": 0, "fill_pct": 0}
                    for d in (10_000, 50_000, 100_000, 200_000)
                },
                "total_balance": 0,
                "total_fill_pct": 0,
                "value_to_fill": capacity,
            },
            "comment": "Баланс не загружен. Обновите через /api/atms/{id}/balance.",
        }

    share = {10_000: 0.10, 50_000: 0.45, 100_000: 0.30, 200_000: 0.15}
    by_denom: Dict[str, Dict[str, Any]] = {}
    for d, s in share.items():
        alloc = int(balance * s)
        count = alloc // d
        by_denom[str(d)] = {
            "count": int(count),
            "balance": int(count * d),
            "fill_pct": round(count * d / (capacity * s) * 100, 1) if s and capacity else 0,
        }

    total_cassette_value = sum(int(c["balance"]) for c in by_denom.values())
    value_to_fill = max(0, capacity - balance)

    return {
        "atm_id": terminal_id,
        "address": atm.get("address"),
        "region": atm.get("region"),
        "branch": atm.get("branch"),
        "current_balance": balance,
        "capacity": capacity,
        "balance_pct": atm.get("balance_pct"),
        "status": atm.get("status"),
        "cassettes": {
            "denominations": [10_000, 50_000, 100_000, 200_000],
            "by_denom": by_denom,
            "total_balance": total_cassette_value,
            "total_fill_pct": round(balance / capacity * 100, 1) if capacity else 0,
            "value_to_fill": value_to_fill,
        },
        "refill_needed": value_to_fill,
    }


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
        for b in rows:
            code = str(b.get("local_code") or "")
            if code and code in bal_map:
                b["cash"] = bal_map[code]
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

class LiveAtmState(BaseModel):
    terminal_id: str
    balance: Optional[int] = None
    status: Optional[str] = None


class IncassationRouteRequest(BaseModel):
    states: List[LiveAtmState] = []
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
    atms = list_atms(limit=5000)
    if req.states:
        apply_live_states(atms, [s.model_dump() for s in req.states])
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
