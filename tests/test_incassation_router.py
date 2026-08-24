from api.core.incassation_router import (
    build_regional_routes,
    canonical_region,
    hours_to_low_cash,
    km,
    nearest_neighbor,
    optimize_tour,
)


def test_canonical_region_viloyat_and_city():
    assert canonical_region("Самарқанд вилояти") == "Самарқанд вилояти"
    assert canonical_region("Самарқанд шаҳри") == "Самарқанд вилояти"
    assert canonical_region("Нарпай тумани", "140100 Самарқанд вилояти, Нарпай тумани") == "Самарқанд вилояти"
    assert canonical_region("Жиззах шаҳри") == "Жиззах вилояти"
    assert canonical_region("Янгиер шаҳри") == "Сирдарё вилояти"
    assert canonical_region("Юнусобод тумани", "100000 Тошкент шаҳри, Юнусобод тумани") == "Тошкент шаҳри"
    assert canonical_region("Чирчиқ шаҳар", "110700 Тошкент вилояти, Чирчиқ шаҳар") == "Тошкент вилояти"
    assert canonical_region("Шаҳрисабз шаҳри", "181300 Қашқадарё вилояти, Шаҳрисабз шаҳри") == "Қашқадарё вилояти"


def test_samarkand_not_served_from_jizzakh():
    sam_branch = {
        "id": 1, "local_code": "S1", "incassation": 1,
        "region": "Самарқанд шаҳри",
        "address": "140100 Самарқанд вилояти, Самарқанд шаҳри",
        "lat": 39.6542, "lon": 66.9597,
    }
    jiz_branch = {
        "id": 2, "local_code": "J1", "incassation": 1,
        "region": "Жиззах шаҳри",
        "address": "130100 Жиззах вилояти, Жиззах шаҳри",
        "lat": 40.1158, "lon": 67.8422,
    }
    atms = [
        {"terminal_id": "A1", "region": "Самарқанд вилояти", "lat": 39.66, "lon": 66.96, "status": "unknown"},
        {"terminal_id": "A2", "region": "Самарқанд вилояти", "lat": 39.67, "lon": 66.97, "status": "unknown"},
        {"terminal_id": "A3", "region": "Самарқанд вилояти", "lat": 39.64, "lon": 66.94, "status": "unknown"},
        {"terminal_id": "B1", "region": "Жиззах вилояти", "lat": 40.12, "lon": 67.84, "status": "unknown"},
    ]
    result = build_regional_routes(atms, [sam_branch, jiz_branch], status="all", snap_roads=False)
    by_region = {}
    for car in result["cars"]:
        by_region.setdefault(car["region"], []).append(car)
        codes = {s["terminal_id"] for s in car["stops"]}
        if car["region"] == "Самарқанд вилояти":
            assert car["departure_branch"]["local_code"] == "S1"
            assert codes <= {"A1", "A2", "A3"}
            assert "B1" not in codes
        if car["region"] == "Жиззах вилояти":
            assert car["departure_branch"]["local_code"] == "J1"
            assert codes == {"B1"}
    assert "Самарқанд вилояти" in by_region
    assert "Жиззах вилояти" in by_region


def test_three_samarkand_branches_only_cover_samarkand_atms():
    branches = [
        {"id": i, "local_code": f"S{i}", "incassation": 1,
         "region": "Самарқанд шаҳри",
         "address": "Самарқанд вилояти, Самарқанд шаҳри",
         "lat": 39.65 + i * 0.01, "lon": 66.95 + i * 0.01}
        for i in range(1, 4)
    ]
    atms = [
        {"terminal_id": f"ATM{i}", "region": "Самарқанд вилояти",
         "lat": 39.655 + i * 0.008, "lon": 66.955 + i * 0.008, "status": "unknown"}
        for i in range(5)
    ]
    # neighbouring viloyat must not steal these ATMs
    branches.append({
        "id": 99, "local_code": "JZ", "incassation": 1,
        "region": "Жиззах шаҳри", "address": "Жиззах вилояти",
        "lat": 39.70, "lon": 67.10,
    })
    result = build_regional_routes(atms, branches, status="all", snap_roads=False)
    codes = {c["departure_branch"]["local_code"] for c in result["cars"]}
    assert "JZ" not in codes
    assert codes <= {"S1", "S2", "S3"}
    served = {s["terminal_id"] for c in result["cars"] for s in c["stops"]}
    assert served == {f"ATM{i}" for i in range(5)}


def test_two_opt_not_worse_than_nn():
    depot = {"lat": 41.3, "lon": 69.28}
    points = [
        {"lat": 41.31, "lon": 69.30},
        {"lat": 41.35, "lon": 69.22},
        {"lat": 41.28, "lon": 69.35},
        {"lat": 41.33, "lon": 69.25},
        {"lat": 41.27, "lon": 69.27},
    ]
    nn = nearest_neighbor(depot, points)
    opt = optimize_tour(depot, points)

    def closed(seq):
        d = km(depot, seq[0])
        for i in range(len(seq) - 1):
            d += km(seq[i], seq[i + 1])
        return d + km(seq[-1], depot)

    assert closed(opt) <= closed(nn) + 1e-6


def test_warning_skips_ok_and_unknown():
    branch = {
        "id": 1, "local_code": "S1", "incassation": 1,
        "region": "Самарқанд вилояти", "address": "Самарқанд вилояти",
        "lat": 39.65, "lon": 66.96,
    }
    atms = [
        {"terminal_id": "OK1", "region": "Самарқанд вилояти", "lat": 39.66, "lon": 66.96, "status": "ok"},
        {"terminal_id": "W1", "region": "Самарқанд вилояти", "lat": 39.67, "lon": 66.97, "status": "warning"},
        {"terminal_id": "C1", "region": "Самарқанд вилояти", "lat": 39.64, "lon": 66.94, "status": "critical"},
        {"terminal_id": "U1", "region": "Самарқанд вилояти", "lat": 39.63, "lon": 66.93, "status": "unknown"},
    ]
    result = build_regional_routes(atms, [branch], status="warning", snap_roads=False)
    served = {s["terminal_id"] for c in result["cars"] for s in c["stops"]}
    assert served == {"W1", "C1"}
    assert result["diagnostics"]["target_atms"] == 2


def test_hours_to_low_cash_none_without_balance():
    assert hours_to_low_cash({"capacity": 400_000_000}) is None


def test_hours_to_low_cash_critical_is_zero():
    hours = hours_to_low_cash({"capacity": 400_000_000, "balance": 40_000_000})
    assert hours == 0.0
