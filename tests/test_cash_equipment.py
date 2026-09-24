"""Tests for the cash-equipment (kassa jihozlari) parser."""
import datetime as dt
from pathlib import Path

import openpyxl

from api.core.cash_equipment import (
    cash_equipment_by_branch,
    parse_cash_equipment_xlsx,
    replace_cash_equipment,
)
from api.core.db import bulk_insert_branches, init_db, truncate_branches

HEADERS = [
    "№",
    "Таркибий бўлинма коди (локал код)",
    "Таркибий бўлинма номи",
    "Асосий восита номи",
    "Асосий воситанинг инвентар рақами",
    "Асосий воситанинг тоифа рақами (номер под категории)",
    "Балансга олинган санаси",
    "Фойдаланишга топширилган санаси",
    "Баланс бўйича тиклаш қиймати",
    "Қолдиқ суммаси",
]


def _write_sample(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Mashinka"
    ws.append(["Kassa jihozlari ro'yxati"])
    ws.append(HEADERS)
    ws.append(list(range(1, 11)))  # нумерация колонок под шапкой
    ws.append([1, 11084, "Самарқанд БХО", "Пул санаш машинаси DORS 800", 1001, "0301",
               dt.datetime(2020, 5, 1), "01.06.2020", 12_000_000, 4_500_000.5])
    ws.append([2, "11084", "Самарқанд БХМ", "Пул санаш машинаси DORS 800", 1002, "0301",
               dt.datetime(2021, 1, 10), dt.datetime(2021, 1, 15), 13_000_000, "-"])
    ws.append([3, "99999", "Номаълум", "Детектор", 2001, "0302", None, None, 100, 50])
    ws.append([4, "", "", "Детектор", 2002, "0302", None, None, 1, 1])
    ws2 = wb.create_sheet("Detektor")
    ws2.append([])
    ws2.append(HEADERS)
    ws2.append([1, "18A00", "Самарқанд БХО", "Детектор валюты - Cassida 9900", "2229", 412, None, None, 10, 5])
    wb.save(path)


def test_parse_and_group(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    import api.core.config as cfg
    import api.core.db as dbmod
    monkeypatch.setattr(cfg, "DB_PATH", db_file)
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    init_db()
    truncate_branches()
    bulk_insert_branches([{"local_code": "11084", "region": "Самарқанд", "address": "Самарқанд БХО. 140158 Самарқанд",
                           "lat": 39.65, "lon": 66.96, "incassation": 1}])

    xlsx = tmp_path / "eq.xlsx"
    _write_sample(xlsx)
    parsed = parse_cash_equipment_xlsx(xlsx)
    assert parsed["by_sheet"] == {"Mashinka": 3, "Detektor": 1}
    assert len(parsed["records"]) == 4
    assert len(parsed["errors"]) == 1  # ни кода, ни названия
    assert parsed["records"][3]["kind"] == "Detektor"
    assert parsed["records"][3]["local_code"] == "18A00"
    r0 = parsed["records"][0]
    assert r0["local_code"] == "11084"
    assert r0["balance_date"] == "2020-05-01"
    assert r0["commissioned_date"] == "2020-06-01"
    assert r0["residual_value"] == 4_500_000.5
    assert parsed["records"][1]["residual_value"] is None

    stats = replace_cash_equipment(parsed["records"])
    assert stats == {"saved": 4, "matched": 3, "unmatched": 1, "branches_matched": 1}

    grouped = cash_equipment_by_branch()
    g = next(b for b in grouped["branches"] if b["local_code"] == "11084")
    assert g["count"] == 3 and g["lat"] == 39.65
    assert [i["kind"] for i in g["items"]] == ["Mashinka", "Mashinka", "Detektor"]
    assert grouped["unmatched_branches"] == ["99999 · Номаълум"]


def test_match_by_unit_name():
    """«локал код» в файле — код региона; филиал ищется по названию подразделения."""
    from api.core.cash_equipment import _match_branch, _name_key

    names = {
        _name_key("Xонобод БХМ"): "11087",
        _name_key("Чилонзор БХМ"): "11192",
        _name_key("Tошкент шаҳар БХО"): "11184",
        _name_key("Ўрта бизнес маркази"): "11196",
        _name_key("Premium ofis"): "11186",
    }
    m = lambda code, name: _match_branch({"local_code": code, "unit_name": name}, {}, names)
    assert m("0300", "Хонобод БХМ") == "11087"
    assert m("2600", "Чилонзар БХМ") == "11192"
    assert m("2600", "Тошкент шаҳар минтақавий БХО") == "11184"
    assert m("2600", "ЎРТА БИЗНЕС БХМ") == "11196"
    assert m("2600", '"PREMIUM" БАНКИНГ МАРКАЗИ') == "11186"
    assert m("1000", '"УЗСАНОАТКУРИЛИШБАНКИ" АТБ БОШ ОФИСИ Амалиёт бошқармаси') is None


def test_lifecycle_statuses():
    from datetime import date
    from api.core.cash_equipment import equipment_lifecycle

    today = date(2026, 9, 24)
    # полностью списана
    off = equipment_lifecycle({"commissioned_date": "2006-07-24", "restoration_value": 100, "residual_value": 0}, today)
    assert off["replace_status"] == "written_off" and off["wear_pct"] == 100.0
    # 7-летний срок: введена 2019-10-14, износ ~98.6% → спишется в течение года
    soon = equipment_lifecycle({"commissioned_date": "2019-10-14", "restoration_value": 1000, "residual_value": 14}, today)
    assert soon["replace_status"] == "soon" and not soon["writeoff_estimated"]
    assert "2026-10" <= soon["writeoff_date"] <= "2026-11"
    # новая: износа нет → норматив 7 лет
    new = equipment_lifecycle({"commissioned_date": "2026-06-01", "restoration_value": 1000, "residual_value": 1000}, today)
    assert new["replace_status"] == "ok" and new["writeoff_estimated"] and new["writeoff_date"].startswith("2033-")
