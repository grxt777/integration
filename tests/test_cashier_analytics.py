"""Unit tests for refactored cashier analytics modules."""
from __future__ import annotations

import pytest

from api.core.cashier.helpers import clean_branch_name, norm, num, parse_hr_status, sval
from api.core.cashier.analytics import (
    _build_report_sql_filters,
    _build_top_lists,
    _top_metric_value,
    apply_replacement_pairing,
    cashier_role,
    is_uncovered_absence,
    _enrich,
)
from api.core.cashier.parsers import _classify_op_group


def test_helpers_normalization():
    assert norm("  Ф.И.Ш  ") == "ф и ш"
    assert norm("Қабул") == "кабул"
    assert num("123,45") == 123.45
    assert num(" - ") == 0.0
    assert sval("  'test'  ") == "test"


def test_clean_branch_name():
    raw = '00123 - "O\'zsanoatqurilishbank" ATB Yunusobod BXM'
    cleaned = clean_branch_name(raw)
    assert "00123" not in cleaned
    assert "O'zsanoatqurilishbank" not in cleaned
    assert "Yunusobod" in cleaned


def test_parse_hr_status():
    st_vacant = parse_hr_status("вакант ставка")
    assert st_vacant["status_code"] == "vacant"

    st_dekret = parse_hr_status("декрет татили")
    assert st_dekret["status_code"] == "maternity"

    st_active = parse_hr_status("ишламокда")
    assert st_active["status_code"] == "active"


def test_cashier_role():
    assert cashier_role({"bek_count": 10, "front_count": 50}) == "front"
    assert cashier_role({"bek_count": 50, "front_count": 10}) == "back"
    assert cashier_role({"bek_count": 0, "front_count": 0}) is None


def test_enrich_uses_excel_load_and_std_days():
    row = {
        "operations_count": 100,
        "operations_minutes": 480,
        "days_worked": 23,
        "std_days": 22,
        "bek_count": 70,
        "front_count": 30,
        "load_percent": 85.5,
        "load_difference": 1.2,
        "employee_number": "42",
        "metrics_json": "{}",
        "branch_name": "",
    }
    enriched, _ = _enrich(row)
    assert enriched["load_percent"] == 85.5
    assert enriched["days_worked_pct"] == 104.5
    assert enriched["bek_pct"] == 70.0
    assert enriched["front_pct"] == 30.0
    assert enriched["employee_number"] == "42"
    assert "efficiency_score" not in enriched


def test_enrich_recomputes_load_when_missing():
    row = {
        "operations_count": 10,
        "operations_minutes": 240,
        "days_worked": 10,
        "std_days": 22,
        "bek_count": 10,
        "front_count": 0,
        "load_percent": 0,
        "metrics_json": "{}",
        "branch_name": "",
    }
    enriched, _ = _enrich(row)
    # 240 / (22 * 480) * 100 = 2.3
    assert enriched["load_percent"] == 2.3


def test_classify_op_group():
    assert _classify_op_group("Банкоматга пул қўйиш") == "back"
    assert _classify_op_group("Пластик карта тарқатиш") == "front"
    assert _classify_op_group("Жами БЕК") == "summary"


def test_sql_filters_empty():
    where, params = _build_report_sql_filters()
    assert where == "TRUE"
    assert params == []


def test_sql_filters_role_front():
    where, params = _build_report_sql_filters(role="front")
    assert "front_count > bek_count" in where
    assert "bek_count = 0" not in where
    assert params == []


def test_sql_filters_role_back_excludes_zero_ops():
    where, params = _build_report_sql_filters(role="back")
    assert "bek_count >= front_count" in where
    assert "bek_count > 0" in where
    assert params == []


def test_sql_filters_position_and_branch():
    where, params = _build_report_sql_filters(position="Кассир", branch="Yunusobod")
    assert "position" in where
    assert "branch_name" in where
    assert params == ["Кассир", "%yunusobod%"]


def test_sql_filters_disciplined():
    where, params = _build_report_sql_filters(status="disciplined")
    assert "discipline_type" in where
    assert params == []


def test_top_metric_value_by_role():
    row = {"operations_count": 100, "bek_count": 70, "front_count": 30}
    assert _top_metric_value(row, None) == 100
    assert _top_metric_value(row, "back") == 70
    assert _top_metric_value(row, "front") == 30


def test_build_top_lists_role_aware():
    rows = [
        {"full_name": "A", "position": "Universal kassir", "operations_count": 100, "bek_count": 90, "front_count": 10},
        {"full_name": "B", "position": "Universal kassir", "operations_count": 80, "bek_count": 20, "front_count": 60},
        {"full_name": "C", "position": "Nazoratchi kassir", "operations_count": 50, "bek_count": 50, "front_count": 0},
        {"full_name": "D", "position": "Universal kassir", "operations_count": 0, "bek_count": 0, "front_count": 0},
    ]
    top_all, by_pos = _build_top_lists(rows, None)
    assert [x["full_name"] for x in top_all] == ["A", "B", "C"]

    top_front, _ = _build_top_lists(rows, "front")
    assert [x["full_name"] for x in top_front] == ["B", "A"]

    top_back, by_pos_back = _build_top_lists(rows, "back")
    assert [x["full_name"] for x in top_back] == ["A", "C", "B"]
    assert [x["full_name"] for x in by_pos_back["Universal kassir"]] == ["A", "B"]


def test_uncovered_absence_requires_empty_seat():
    empty = {
        "hr_status_code": "maternity",
        "operations_count": 0,
        "has_replacement": 0,
        "replaced_by_full_name": None,
    }
    worked = {
        "hr_status_code": "vacation",
        "operations_count": 11090,
        "has_replacement": 0,
        "replaced_by_full_name": None,
    }
    covered = {
        "hr_status_code": "maternity",
        "operations_count": 0,
        "has_replacement": 1,
        "replaced_by_full_name": "TEMP",
    }
    assert is_uncovered_absence(empty) is True
    assert is_uncovered_absence(worked) is False
    assert is_uncovered_absence(covered) is False


def test_replacement_pairing_skips_working_leave():
    rows = [
        {"id": 1, "full_name": "TEMP A", "hr_status_code": "temporary",
         "operations_count": 100, "branch_name": "BXM-1", "position": "Kassir"},
        {"id": 2, "full_name": "LEAVE WORKED", "hr_status_code": "vacation",
         "operations_count": 5000, "branch_name": "BXM-1", "position": "Kassir"},
        {"id": 3, "full_name": "DEKRET EMPTY", "hr_status_code": "maternity",
         "operations_count": 0, "branch_name": "BXM-1", "position": "Kassir"},
        {"id": 4, "full_name": "DEKRET NO TEMP", "hr_status_code": "maternity",
         "operations_count": 0, "branch_name": "BXM-2", "position": "Kassir"},
    ]
    apply_replacement_pairing(rows)
    by_name = {r["full_name"]: r for r in rows}
    assert by_name["TEMP A"]["replacing_full_name"] == "DEKRET EMPTY"
    assert by_name["DEKRET EMPTY"]["has_replacement"] == 1
    assert by_name["LEAVE WORKED"]["has_replacement"] == 0
    assert is_uncovered_absence(by_name["LEAVE WORKED"]) is False
    assert is_uncovered_absence(by_name["DEKRET EMPTY"]) is False
    assert is_uncovered_absence(by_name["DEKRET NO TEMP"]) is True
