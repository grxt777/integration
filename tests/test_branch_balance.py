"""Tests for isolated branch cash-balance parser."""
from pathlib import Path

import openpyxl

from api.core.branch_balance import (
    _parse_amount,
    parse_branch_balances_xlsx,
    replace_branch_balances,
)
from api.core.db import bulk_insert_branches, init_db, truncate_branches


def _write_sample(path: Path, code_header: str = "Код БХМ") -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append([
        code_header,
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


def test_parse_latin_bxm_header(tmp_path):
    """Excel often has «Код БXM» with Latin X — must still detect bxm_code."""
    xlsx = tmp_path / "bal_latin.xlsx"
    _write_sample(xlsx, code_header="Код БXM")
    parsed = parse_branch_balances_xlsx(xlsx)
    assert "bxm_code" in parsed["columns"].values()
    assert parsed["records"][0]["bxm_code"] == "11084"


def test_analytics_region_sum(tmp_path, monkeypatch):
    db_file = tmp_path / "t3.db"
    import api.core.config as cfg
    import api.core.db as dbmod
    monkeypatch.setattr(cfg, "DB_PATH", db_file)
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    init_db()
    truncate_branches()
    bulk_insert_branches([
        {"local_code": "11084", "region": "Самарқанд шаҳри", "address": "A", "lat": 39.6, "lon": 66.9, "incassation": 1},
        {"local_code": "11091", "region": "Самарқанд шаҳри", "address": "B", "lat": 39.7, "lon": 66.8, "incassation": 1},
        {"local_code": "11204", "region": "Жиззах шаҳри", "address": "C", "lat": 40.1, "lon": 67.8, "incassation": 1},
    ])
    replace_branch_balances([
        {"bxm_code": "11084", "branch_name": "S1", "balance_uzs": 100.0, "limit_uzs": 200.0, "limit_usd": 10.0,
         "currencies": {"840": 5.0}},
        {"bxm_code": "11091", "branch_name": "S2", "balance_uzs": 50.0, "limit_uzs": 80.0, "limit_usd": 8.0,
         "currencies": {"840": 2.0}},
        {"bxm_code": "11204", "branch_name": "J1", "balance_uzs": 30.0, "limit_uzs": 40.0, "limit_usd": 3.0,
         "currencies": {}},
    ])
    from api.core.branch_balance import branch_cash_analytics
    a = branch_cash_analytics()
    assert a["warehouse_branches"] == 3
    assert a["overall"]["balance_uzs"] == 180.0
    assert a["overall"]["usd_amount"] == 7.0
    assert a["math_check"]["regions_sum_equals_overall_uzs"] is True
    sam = next(r for r in a["by_region"] if "Самарқанд" in r["region"])
    assert sam["balance_uzs"] == 150.0
    assert sam["branches"] == 2


def test_match_only_by_bxm_not_by_name(tmp_path, monkeypatch):
    db_file = tmp_path / "t2.db"
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
    # Same name as branch address, but WRONG bxm code → must NOT match
    records = [{
        "bxm_code": "99999",
        "branch_name": "Самарқанд БХМ",
        "balance_uzs": 100.0,
        "limit_uzs": 200.0,
        "limit_usd": 10.0,
        "currencies": {},
    }]
    stats = replace_branch_balances(records)
    assert stats["matched_to_branches"] == 0
    assert stats["unmatched"] == 1


def test_clear_branch_balances(tmp_path, monkeypatch):
    db_file = tmp_path / "clear.db"
    import api.core.config as cfg
    import api.core.db as dbmod
    monkeypatch.setattr(cfg, "DB_PATH", db_file)
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    init_db()
    truncate_branches()
    bulk_insert_branches([{
        "local_code": "11084",
        "region": "Самарқанд",
        "address": "A",
        "lat": 39.65,
        "lon": 66.96,
        "incassation": 1,
    }])
    replace_branch_balances([{
        "bxm_code": "11084",
        "branch_name": "T",
        "balance_uzs": 1.0,
        "limit_uzs": 2.0,
        "limit_usd": 3.0,
        "currencies": {},
    }])
    from api.core.branch_balance import clear_branch_balances, list_branch_balances
    assert len(list_branch_balances()) == 1
    assert clear_branch_balances() == 1
    assert list_branch_balances() == []
