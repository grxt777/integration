"""SQB xarid/sotuv kurs Excel parser testlari."""
from pathlib import Path

import openpyxl

from api.core.sqb_rates import (
    latest_rates,
    parse_sqb_rates_xlsx,
    replace_sqb_rates,
    uzs_equivalent,
)
from api.core.db import init_db


def _write_sample(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["21/08/25", None, "Valyuta nomi", "21/08/26", None, "Farq", None])
    ws.append(["Xarid", "Sotuv", "Valyuta nomi", "Xarid", "Sotuv", "Xarid", "Sotuv"])
    ws.append([12410, 12520, "AQSH dollari-840", 11790, 11900, -620, -620])
    ws.append([14200, 14800, "Yevro-978", 13500, 14100, -700, -700])
    ws.append([74, 94, "Yena-392", 64, 84, -10, -10])
    ws.append([136, 163, "Rubl-643", 0, 142, -136, -21])
    wb.save(path)


def test_parse_sqb_rates_table(tmp_path):
    xlsx = tmp_path / "rates.xlsx"
    _write_sample(xlsx)
    parsed = parse_sqb_rates_xlsx(xlsx)
    assert parsed["dates"] == ["2025-08-21", "2026-08-21"]
    usd = [r for r in parsed["records"] if r["iso_num"] == "840"]
    assert len(usd) == 2
    cur = next(r for r in usd if r["rate_date"] == "2026-08-21")
    assert cur["buy"] == 11790
    assert cur["sell"] == 11900


def test_latest_and_equivalent(tmp_path, monkeypatch):
    db_file = tmp_path / "t.db"
    monkeypatch.setenv("DB_PATH", str(db_file))
    import api.core.config as cfg
    import api.core.db as dbmod
    monkeypatch.setattr(cfg, "DB_PATH", db_file)
    monkeypatch.setattr(dbmod, "DB_PATH", db_file)
    init_db()

    xlsx = tmp_path / "rates.xlsx"
    _write_sample(xlsx)
    parsed = parse_sqb_rates_xlsx(xlsx)
    replace_sqb_rates(parsed["records"])
    bundle = latest_rates()
    assert bundle["ok"]
    assert bundle["current_date"] == "2026-08-21"
    usd = next(r for r in bundle["rows"] if r["iso"] == "840")
    assert usd["buy"] == 11790
    assert usd["diff_buy"] == -620
    eq = uzs_equivalent(100.0, "840", bundle["by_iso"])
    assert eq == 1_179_000.0
    # xarid=0 bo'lsa ekvivalent yo'q
    assert uzs_equivalent(50.0, "643", bundle["by_iso"]) is None
