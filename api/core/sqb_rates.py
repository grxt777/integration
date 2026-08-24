"""SQB valyuta kurslari — xarid / sotuv (Excel jadvali bo'yicha).

Kutilgan Excel:
  sana | Valyuta nomi | sana | Farq
  Xarid | Sotuv | AQSH dollari-840 | Xarid | Sotuv | ...
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import openpyxl

from .db import _connect

log = logging.getLogger(__name__)

ISO_META: Dict[str, Dict[str, str]] = {
    "840": {"code": "USD", "name": "AQSH dollari", "name_ru": "Доллар США"},
    "978": {"code": "EUR", "name": "Yevro", "name_ru": "Евро"},
    "826": {"code": "GBP", "name": "Funt sterling", "name_ru": "Фунт стерлингов"},
    "756": {"code": "CHF", "name": "Shvet. Frank", "name_ru": "Швейцарский франк"},
    "392": {"code": "JPY", "name": "Yena", "name_ru": "Японская иена"},
    "643": {"code": "RUB", "name": "Rubl", "name_ru": "Российский рубль"},
    "156": {"code": "CNY", "name": "Xitoy Yuani", "name_ru": "Юань"},
    "398": {"code": "KZT", "name": "Qozoq tengesi", "name_ru": "Тенге"},
    "972": {"code": "TJS", "name": "Tojikiston Somoni", "name_ru": "Сомони"},
}

# Screenshotdagi SQB jadvali (21/08/25 va 21/08/26)
_SEED: List[Tuple[str, str, Optional[float], Optional[float]]] = [
    ("2025-08-21", "840", 12410, 12520),
    ("2025-08-21", "978", 14200, 14800),
    ("2025-08-21", "826", 16500, 17300),
    ("2025-08-21", "756", 15100, 15700),
    ("2025-08-21", "392", 74, 94),
    ("2025-08-21", "643", 136, 163),
    ("2025-08-21", "156", 1691, 1801),
    ("2025-08-21", "398", 0, 0),
    ("2025-08-21", "972", 0, 0),
    ("2026-08-21", "840", 11790, 11900),
    ("2026-08-21", "978", 13500, 14100),
    ("2026-08-21", "826", 15800, 16400),
    ("2026-08-21", "756", 14500, 15100),
    ("2026-08-21", "392", 64, 84),
    ("2026-08-21", "643", 0, 142),
    ("2026-08-21", "156", 1710, 1810),
    ("2026-08-21", "398", 23, 27),
    ("2026-08-21", "972", 1270, 1470),
]


def init_sqb_rate_tables() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS sqb_rates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                rate_date TEXT NOT NULL,
                iso_num TEXT NOT NULL,
                buy REAL,
                sell REAL,
                source TEXT DEFAULT 'excel',
                imported_at TEXT DEFAULT (datetime('now')),
                UNIQUE(rate_date, iso_num)
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sqb_rates_date ON sqb_rates(rate_date)")
        n = conn.execute("SELECT COUNT(*) AS c FROM sqb_rates").fetchone()["c"]
        if int(n) == 0:
            conn.executemany(
                """
                INSERT INTO sqb_rates (rate_date, iso_num, buy, sell, source)
                VALUES (?, ?, ?, ?, 'seed')
                """,
                _SEED,
            )
            log.info("SQB kurslari seed qilindi: %s qator", len(_SEED))


def _parse_num(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in ("-", "—", "–", "."):
        return None
    s = s.replace("\u00a0", "").replace(" ", "").replace(",", ".")
    s = re.sub(r"[^\d.\-]", "", s)
    if not s or s in ("-", ".", "-."):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_date(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    s = str(value).strip()
    if not s:
        return None
    for fmt in ("%d/%m/%y", "%d/%m/%Y", "%d.%m.%y", "%d.%m.%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})", s)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            return date(y, mo, d).isoformat()
        except ValueError:
            return None
    return None


def _norm(value: Any) -> str:
    if value is None:
        return ""
    s = str(value).strip().lower().replace("ё", "е")
    s = s.replace("ў", "u").replace("‘", "'")
    return re.sub(r"\s+", " ", s)


def _is_buy(text: str) -> bool:
    t = _norm(text)
    return t in ("xarid", "харид", "buy", "покупка", "sotib olish")


def _is_sell(text: str) -> bool:
    t = _norm(text)
    return t in ("sotuv", "сотув", "sell", "продажа", "sotish")


def _is_farq(text: str) -> bool:
    t = _norm(text)
    return t.startswith("farq") or t.startswith("фарк") or t.startswith("разниц")


def _iso_from_name(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value)
    m = re.search(r"(?<!\d)(840|978|826|756|392|643|156|398|972)(?!\d)", s)
    return m.group(1) if m else None


def parse_sqb_rates_xlsx(path: str | Path) -> Dict[str, Any]:
    """Excel: sana + Xarid/Sotuv ustunlari, valyuta nomi (ISO kod bilan)."""
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise ValueError("Excel bo'sh")

    header_idx = None
    for i, row in enumerate(rows[:12]):
        texts = [_norm(c) for c in row]
        if any(_is_buy(t) for t in texts) and any(_is_sell(t) for t in texts):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError("Xarid / Sotuv ustunlari topilmadi")

    date_row = rows[header_idx - 1] if header_idx > 0 else rows[header_idx]
    sub_row = rows[header_idx]
    ncols = max(len(date_row), len(sub_row))

    date_for_col: List[Optional[str]] = [None] * ncols
    last_date = None
    last_was_farq = False
    for c in range(ncols):
        dval = date_row[c] if c < len(date_row) else None
        parsed = _parse_date(dval)
        if parsed:
            last_date = parsed
            last_was_farq = False
        if _is_farq(str(dval or "")) or _is_farq(str(sub_row[c] if c < len(sub_row) else "")):
            last_was_farq = True
            last_date = None
        date_for_col[c] = None if last_was_farq else last_date

    name_col = None
    buy_cols: Dict[str, int] = {}
    sell_cols: Dict[str, int] = {}
    for c in range(ncols):
        cell = sub_row[c] if c < len(sub_row) else None
        t = _norm(cell)
        if "valyuta" in t or "валют" in t or "nomi" in t:
            name_col = c
        dt = date_for_col[c]
        if not dt:
            continue
        if _is_buy(t):
            buy_cols[dt] = c
        elif _is_sell(t):
            sell_cols[dt] = c

    if name_col is None:
        for c in range(ncols):
            hits = 0
            for row in rows[header_idx + 1 : header_idx + 20]:
                if c < len(row) and _iso_from_name(row[c]):
                    hits += 1
            if hits >= 3:
                name_col = c
                break
    if name_col is None:
        raise ValueError("Valyuta nomi ustuni topilmadi")
    if not buy_cols and not sell_cols:
        raise ValueError("Sana bo'yicha Xarid/Sotuv ustunlari topilmadi")

    dates = sorted(set(buy_cols) | set(sell_cols))
    records: List[Dict[str, Any]] = []
    errors: List[str] = []
    for r_i, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        if name_col >= len(row):
            continue
        iso = _iso_from_name(row[name_col])
        if not iso:
            continue
        meta = ISO_META.get(iso, {"code": iso, "name": str(row[name_col])})
        for dt in dates:
            bcol = buy_cols.get(dt)
            scol = sell_cols.get(dt)
            buy = _parse_num(row[bcol]) if bcol is not None and bcol < len(row) else None
            sell = _parse_num(row[scol]) if scol is not None and scol < len(row) else None
            if buy is None and sell is None:
                continue
            records.append({
                "rate_date": dt,
                "iso_num": iso,
                "code": meta["code"],
                "name": meta.get("name"),
                "buy": buy,
                "sell": sell,
            })
        if not any(rec["iso_num"] == iso for rec in records[-len(dates) * 2 :]):
            errors.append(f"Qator {r_i}: {row[name_col]!r} — kurs yo'q")

    if not records:
        raise ValueError("Kurs qatorlari topilmadi")
    return {
        "header_row": header_idx + 1,
        "dates": dates,
        "records": records,
        "errors": errors,
        "total_rows": len(records),
    }


def replace_sqb_rates(records: List[Dict[str, Any]], source: str = "excel") -> Dict[str, int]:
    init_sqb_rate_tables()
    dates = sorted({r["rate_date"] for r in records})
    with _connect() as conn:
        for dt in dates:
            conn.execute("DELETE FROM sqb_rates WHERE rate_date = ?", (dt,))
        for rec in records:
            conn.execute(
                """
                INSERT INTO sqb_rates (rate_date, iso_num, buy, sell, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(rate_date, iso_num) DO UPDATE SET
                    buy = excluded.buy,
                    sell = excluded.sell,
                    source = excluded.source,
                    imported_at = datetime('now')
                """,
                (rec["rate_date"], rec["iso_num"], rec.get("buy"), rec.get("sell"), source),
            )
    return {"saved": len(records), "dates": len(dates)}


def list_rate_dates() -> List[str]:
    init_sqb_rate_tables()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT DISTINCT rate_date FROM sqb_rates ORDER BY rate_date"
        ).fetchall()
    return [r["rate_date"] for r in rows]


def rates_for_date(rate_date: str) -> Dict[str, Dict[str, Any]]:
    init_sqb_rate_tables()
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM sqb_rates WHERE rate_date = ?", (rate_date,)
        ).fetchall()
    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        iso = str(r["iso_num"])
        meta = ISO_META.get(iso, {"code": iso, "name": iso, "name_ru": iso})
        buy = r["buy"]
        sell = r["sell"]
        out[iso] = {
            "iso": iso,
            "code": meta["code"],
            "name": meta["name"],
            "name_ru": meta["name_ru"],
            "buy": buy,
            "sell": sell,
            "rate_uzs": buy if buy and float(buy) > 0 else None,
        }
    return out


def latest_rates() -> Dict[str, Any]:
    """Eng so'nggi sana + oldingi sana (Farq uchun)."""
    dates = list_rate_dates()
    if not dates:
        return {"ok": False, "current_date": None, "prev_date": None, "rows": [], "by_iso": {}}
    current = dates[-1]
    prev = dates[-2] if len(dates) >= 2 else None
    cur_map = rates_for_date(current)
    prev_map = rates_for_date(prev) if prev else {}
    order = list(ISO_META.keys())
    extra = [k for k in cur_map if k not in ISO_META]
    rows = []
    for iso in order + extra:
        cur = cur_map.get(iso)
        if not cur:
            continue
        old = prev_map.get(iso) or {}
        buy = cur.get("buy")
        sell = cur.get("sell")
        pbuy = old.get("buy")
        psell = old.get("sell")
        rows.append({
            **cur,
            "prev_buy": pbuy,
            "prev_sell": psell,
            "diff_buy": None if buy is None or pbuy is None else round(float(buy) - float(pbuy), 4),
            "diff_sell": None if sell is None or psell is None else round(float(sell) - float(psell), 4),
        })
    return {
        "ok": True,
        "current_date": current,
        "prev_date": prev,
        "dates": dates,
        "applied_kind": "sqb_buy",
        "applied_kind_label": "SQB xarid",
        "rows": rows,
        "by_iso": cur_map,
    }


def uzs_equivalent(amount: Optional[float], iso_num: str, by_iso: Optional[Dict[str, Any]] = None) -> Optional[float]:
    if amount is None:
        return None
    bundle = by_iso if by_iso is not None else (latest_rates().get("by_iso") or {})
    row = bundle.get(str(iso_num)) or {}
    buy = row.get("buy")
    if buy is None or float(buy) <= 0:
        return None
    return round(float(amount) * float(buy), 2)
