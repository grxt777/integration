"""Tests for isolated branch cash-balance parser."""
from pathlib import Path

import openpyxl

from api.core.branch_balance import (
    _parse_amount,
    parse_branch_balances_xlsx,
    replace_branch_balances,
)
from api.core.db import bulk_insert_branches, init_db, truncate_branches


def _write_sample(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        "Код БХМ",
        "Филиал (БХМ) номи",
        "Сўм",
        "Лимит сўм",
        "Лимит доллар",
        "АҚШ доллари 840",
        "Йена 392",
        "Россия рубли 643",
        "Швейцария франки 756",
        "Фунт стерлинг 826",
        "Евро 978",
        "Тенге 398",
        "Юан 156",
        "Сомони 972",
    ])
    ws.append([
        "11084", "Самарқанд БХМ", 1_500_000_000, 2_000_000_000, 150_000,
        12000, "-", 0, None, "", 5000, "-", 100, 0,
    ])
    ws.append([
        "99999", "Номаълум филиал", 100, 200, 10,
        "-", "-", "-", "-", "-", "-", "-", "-", "-",
    ])
    wb.save(path)


def test_parse_amount_empty_dash_zero():
    assert _parse_amount(None) is None
    assert _parse_amount("-") is None
    assert _parse_amount("") is None
    assert _parse_amount("—") is None
    assert _parse_amount(0) == 0.0
    assert _parse_amount("0") == 0.0
    assert _parse_amount("1 200,5") == 1200.5


def test_parse_and_match(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    # re-bind config path used by db
    import api.core.config as cfg
    import api.core.db as dbmod
    monkeypatch.setattr(cfg, "DB_PATH", db_file)
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)

    init_db()
    truncate_branches()
    bulk_insert_branches([{
        "local_code": "11084",
        "region": "Самарқанд",
        "address": "Самарқанд БХМ, центр",
        "lat": 39.65,
        "lon": 66.96,
        "incassation": 1,
    }])

    xlsx = tmp_path / "bal.xlsx"
    _write_sample(xlsx)
    parsed = parse_branch_balances_xlsx(xlsx)
    assert len(parsed["records"]) == 2
    r0 = parsed["records"][0]
    assert r0["bxm_code"] == "11084"
    assert r0["balance_uzs"] == 1_500_000_000
    assert r0["currencies"]["840"] == 12000
    assert r0["currencies"]["392"] is None  # "-"
    assert r0["currencies"]["643"] == 0.0
    assert r0["currencies"]["978"] == 5000

    stats = replace_branch_balances(parsed["records"])
    assert stats["saved"] == 2
    assert stats["matched_to_branches"] == 1
    assert stats["unmatched"] == 1
