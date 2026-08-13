"""Region-first incassation routes.

ATM of a viloyat are served only by incassation branches of the same viloyat.
Example: Samarkand ATMs → only Samarkand branches, never Jizzakh.

Each eligible branch gets the ATMs nearest to it; each tour is NN + 2-opt.
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from math import asin, cos, radians, sin, sqrt
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .config import AVG_SPEED_KMH, DEFAULT_CAPACITY, LOW_CASH_PCT, ROAD_FACTOR, WARNING_CASH_PCT

log = logging.getLogger(__name__)
OSRM_BASE = os.getenv("OSRM_URL", "https://router.project-osrm.org").rstrip("/")
_TASHKENT_TZ = timezone(timedelta(hours=5))

# ── Canonical viloyat names (same spelling as ATM registry) ──

CANONICAL_REGIONS = (
    "Тошкент шаҳри",
    "Тошкент вилояти",
    "Андижон вилояти",
    "Бухоро вилояти",
    "Жиззах вилояти",
    "Қашқадарё вилояти",
    "Навоий вилояти",
    "Наманган вилояти",
    "Самарқанд вилояти",
    "Сирдарё вилояти",
    "Сурхондарё вилояти",
    "Фарғона вилояти",
    "Хоразм вилояти",
    "Қорақалпоғистон Республикаси",
)

# Readable Cyrillic/Latin keys; they are passed through `_norm` at import.
_EXPLICIT_RAW: Tuple[Tuple[str, str], ...] = (
    ("қорақалпоғистон республикаси", "Қорақалпоғистон Республикаси"),
    ("қорақалпоғистон", "Қорақалпоғистон Республикаси"),
    ("каракалпакстан", "Қорақалпоғистон Республикаси"),
    ("тошкент шаҳри", "Тошкент шаҳри"),
    ("тошкент шахри", "Тошкент шаҳри"),
    ("tashkent city", "Тошкент шаҳри"),
    ("тошкент вилояти", "Тошкент вилояти"),
    ("андижон вилояти", "Андижон вилояти"),
    ("бухоро вилояти", "Бухоро вилояти"),
    ("жиззах вилояти", "Жиззах вилояти"),
    ("қашқадарё вилояти", "Қашқадарё вилояти"),
    ("кашкадарья вилояти", "Қашқадарё вилояти"),
    ("навоий вилояти", "Навоий вилояти"),
    ("наманган вилояти", "Наманган вилояти"),
    ("самарқанд вилояти", "Самарқанд вилояти"),
    ("самарканд вилояти", "Самарқанд вилояти"),
    ("сирдарё вилояти", "Сирдарё вилояти"),
    ("сурхондарё вилояти", "Сурхондарё вилояти"),
    ("фарғона вилояти", "Фарғона вилояти"),
    ("фергана вилояти", "Фарғона вилояти"),
    ("хоразм вилояти", "Хоразм вилояти"),
    ("андижон", "Андижон вилояти"),
    ("бухоро", "Бухоро вилояти"),
    ("жиззах", "Жиззах вилояти"),
    ("қашқадарё", "Қашқадарё вилояти"),
    ("навоий", "Навоий вилояти"),
    ("наманган", "Наманган вилояти"),
    ("самарқанд", "Самарқанд вилояти"),
    ("самарканд", "Самарқанд вилояти"),
    ("сирдарё", "Сирдарё вилояти"),
    ("сурхондарё", "Сурхондарё вилояти"),
    ("фарғона", "Фарғона вилояти"),
    ("хоразм", "Хоразм вилояти"),
)

# District / city → viloyat when the string has no explicit "вилояти".
_PLACE_RAW: Dict[str, str] = {
    # Toshkent shahri
    "yunusobod": "Тошкент шаҳри",
    "chilonzor": "Тошкент шаҳри",
    "uchtepa": "Тошкент шаҳри",
    "mirzoulugbek": "Тошкент шаҳри",
    "mirobod": "Тошкент шаҳри",
    "olmazor": "Тошкент шаҳри",
    "sergeli": "Тошкент шаҳри",
    "yakkasaroy": "Тошкент шаҳри",
    "yangihayot": "Тошкент шаҳри",
    "bektemir": "Тошкент шаҳри",
    "shayxontohur": "Тошкент шаҳри",
    "yashnobod": "Тошкент шаҳри",
    # Toshkent viloyati
    "angren": "Тошкент вилояти",
    "chirchiq": "Тошкент вилояти",
    "bekobod": "Тошкент вилояти",
    "olmaliq": "Тошкент вилояти",
    "nurafshon": "Тошкент вилояти",
    "buka": "Тошкент вилояти",
    "pskent": "Тошкент вилояти",
    "qibray": "Тошкент вилояти",
    "yangiyol": "Тошкент вилояти",
    "gazalkent": "Тошкент вилояти",
    "ohangaron": "Тошкент вилояти",
    "parkent": "Тошкент вилояти",
    "zangiota": "Тошкент вилояти",
    "bostanliq": "Тошкент вилояти",
    "quyichirchiq": "Тошкент вилояти",
    "yuqorichirchiq": "Тошкент вилояти",
    # Samarqand (never Jizzakh)
    "narpay": "Самарқанд вилояти",
    "urgut": "Самарқанд вилояти",
    "kattaqorgon": "Самарқанд вилояти",
    "payariq": "Самарқанд вилояти",
    "ishtixon": "Самарқанд вилояти",
    "pastdargom": "Самарқанд вилояти",
    "nurobod": "Самарқанд вилояти",
    "qushrabot": "Самарқанд вилояти",
    "bulungur": "Самарқанд вилояти",
    "toyloq": "Самарқанд вилояти",
    "oqdaryo": "Самарқанд вилояти",
    "jambay": "Самарқанд вилояти",
    # Jizzakh
    "gallaorol": "Жиззах вилояти",
    "zaamin": "Жиззах вилояти",
    "zomin": "Жиззах вилояти",
    "dustlik": "Жиззах вилояти",
    "paxtakor": "Жиззах вилояти",
    "baxmal": "Жиззах вилояти",
    "mirzachol": "Жиззах вилояти",
    "arnasoy": "Жиззах вилояти",
    # Qashqadaryo
    "shahrisabz": "Қашқадарё вилояти",
    "qarshi": "Қашқадарё вилояти",
    "koson": "Қашқадарё вилояти",
    "muborak": "Қашқадарё вилояти",
    "guzor": "Қашқадарё вилояти",
    "kitob": "Қашқадарё вилояти",
    "chiroqchi": "Қашқадарё вилояти",
    "yakkabog": "Қашқадарё вилояти",
    "qorovulbozor": "Бухоро вилояти",
    "kogon": "Бухоро вилояти",
    "gijduvon": "Бухоро вилояти",
    # Sirdaryo (Yangier is NOT Jizzakh)
    "guliston": "Сирдарё вилояти",
    "yangier": "Сирдарё вилояти",
    "baxt": "Сирдарё вилояти",
    "sardoba": "Сирдарё вилояти",
    "xovos": "Сирдарё вилояти",
    # Fargona
    "qokon": "Фарғона вилояти",
    "margilon": "Фарғона вилояти",
    "rishton": "Фарғона вилояти",
    "quva": "Фарғона вилояти",
    # Surxondaryo
    "termiz": "Сурхондарё вилояти",
    "sariosiyo": "Сурхондарё вилояти",
    "denov": "Сурхондарё вилояти",
    "jarqorgon": "Сурхондарё вилояти",
    # Namangan
    "yangiqorgon": "Наманган вилояти",
    "chust": "Наманган вилояти",
    # Xorazm
    "urganch": "Хоразм вилояти",
    "xiva": "Хоразм вилояти",
    "topraqqala": "Хоразм вилояти",
    # Qoraqalpogiston
    "nukus": "Қорақалпоғистон Республикаси",
    "taxiatosh": "Қорақалпоғистон Республикаси",
    "qongirot": "Қорақалпоғистон Республикаси",
    "qonlikol": "Қорақалпоғистон Республикаси",
    "ellikqala": "Қорақалпоғистон Республикаси",
    # Andijon
    "xonobod": "Андижон вилояти",
    "asaka": "Андижон вилояти",
    "асака": "Андижон вилояти",
    # Navoiy
    "zarafshon": "Навоий вилояти",
    "uchquduq": "Навоий вилояти",
    # Cyrillic duplicates for жойлашуви
    "юнусобод": "Тошкент шаҳри",
    "чилонзор": "Тошкент шаҳри",
    "учтепа": "Тошкент шаҳри",
    "мирзо улуғбек": "Тошкент шаҳри",
    "миробод": "Тошкент шаҳри",
    "олмазор": "Тошкент шаҳри",
    "сергели": "Тошкент шаҳри",
    "яккасарой": "Тошкент шаҳри",
    "ангрен": "Тошкент вилояти",
    "чирчиқ": "Тошкент вилояти",
    "бекобод": "Тошкент вилояти",
    "олмалиқ": "Тошкент вилояти",
    "нурафшон": "Тошкент вилояти",
    "нарпай": "Самарқанд вилояти",
    "шаҳрисабз": "Қашқадарё вилояти",
    "қарши": "Қашқадарё вилояти",
    "косон": "Қашқадарё вилояти",
    "янгиер": "Сирдарё вилояти",
    "гулистон": "Сирдарё вилояти",
    "қўқон": "Фарғона вилояти",
    "марғилон": "Фарғона вилояти",
    "термиз": "Сурхондарё вилояти",
    "сариосиё": "Сурхондарё вилояти",
    "денов": "Сурхондарё вилояти",
    "урганч": "Хоразм вилояти",
    "хива": "Хоразм вилояти",
    "нукус": "Қорақалпоғистон Республикаси",
    "хонобод": "Андижон вилояти",
}


def _norm(value: Any) -> str:
    text = str(value or "").lower()
    repl = {
        "ё": "е", "ў": "у", "қ": "к", "ғ": "г", "ҳ": "х",
        "'": "", "`": "", "’": "", "ʻ": "",
    }
    for src, dst in repl.items():
        text = text.replace(src, dst)
    return "".join(ch for ch in text if ch.isalnum())


_EXPLICIT_PHRASES: Tuple[Tuple[str, str], ...] = tuple(
    (_norm(key), name) for key, name in _EXPLICIT_RAW
)
_PLACE_TO_REGION: Dict[str, str] = {_norm(key): name for key, name in _PLACE_RAW.items()}


def canonical_region(*parts: Any) -> Optional[str]:
    """Map any region / city / address blob to one of 14 canonical viloyats."""
    blob = _norm(" ".join(str(p) for p in parts if p))
    if not blob:
        return None

    # Toshkent shahri vs viloyati must be decided before the generic "тошкент" token.
    if "тошкентшахри" in blob or "тошкентшахр" in blob:
        return "Тошкент шаҳри"
    if "тошкентвилояти" in blob or "тошкентвилоят" in blob:
        return "Тошкент вилояти"

    for phrase, name in _EXPLICIT_PHRASES:
        if phrase in blob:
            return name

    # City / tuman fallback. Prefer longer keys.
    for place in sorted(_PLACE_TO_REGION, key=len, reverse=True):
        if place in blob:
            return _PLACE_TO_REGION[place]

    if "тошкент" in blob:
        return "Тошкент шаҳри"
    return None


def km(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    dlat = radians(b["lat"] - a["lat"])
    dlon = radians(b["lon"] - a["lon"])
    x = (
        sin(dlat / 2) ** 2
        + cos(radians(a["lat"])) * cos(radians(b["lat"])) * sin(dlon / 2) ** 2
    )
    return 6371 * 2 * asin(sqrt(min(1.0, x)))


def _closed_length(depot: Dict[str, Any], stops: Sequence[Dict[str, Any]]) -> float:
    if not stops:
        return 0.0
    dist = km(depot, stops[0])
    for i in range(len(stops) - 1):
        dist += km(stops[i], stops[i + 1])
    dist += km(stops[-1], depot)
    return dist


def nearest_neighbor(depot: Dict[str, Any], points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    remaining = list(points)
    out: List[Dict[str, Any]] = []
    cur = depot
    while remaining:
        nxt = min(remaining, key=lambda x: km(cur, x))
        remaining.remove(nxt)
        out.append(nxt)
        cur = nxt
    return out


def two_opt(depot: Dict[str, Any], stops: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """2-opt improvement of a closed tour depot → stops → depot."""
    if len(stops) < 4:
        return stops
    route = list(stops)
    improved = True
    while improved:
        improved = False
        best = _closed_length(depot, route)
        for i in range(len(route) - 1):
            for j in range(i + 2, len(route)):
                candidate = route[:i] + list(reversed(route[i:j])) + route[j:]
                length = _closed_length(depot, candidate)
                if length + 1e-9 < best:
                    route = candidate
                    best = length
                    improved = True
                    break
            if improved:
                break
    return route


def optimize_tour(depot: Dict[str, Any], points: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return two_opt(depot, nearest_neighbor(depot, points))


def _split_by_capacity(
    depot: Dict[str, Any],
    points: List[Dict[str, Any]],
    max_stops: int,
) -> List[List[Dict[str, Any]]]:
    if max_stops <= 0 or len(points) <= max_stops:
        return [points] if points else []
    remaining = list(points)
    groups: List[List[Dict[str, Any]]] = []
    while remaining:
        seed = max(remaining, key=lambda p: km(depot, p))
        remaining.remove(seed)
        group = [seed]
        while remaining and len(group) < max_stops:
            last = group[-1]
            nxt = min(remaining, key=lambda p: km(last, p))
            remaining.remove(nxt)
            group.append(nxt)
        groups.append(group)
    return groups


def _item_region(item: Dict[str, Any]) -> Optional[str]:
    return canonical_region(
        item.get("region"),
        item.get("address"),
        item.get("branch"),
    )


def _stop_payload(atm: Dict[str, Any]) -> Dict[str, Any]:
    cap = atm.get("capacity") or 400_000_000
    bal = atm.get("balance")
    refill = 0
    if bal is None:
        refill = int(cap * 0.8)
    else:
        refill = max(0, int(cap * 0.8 - bal))
    return {
        "terminal_id": atm.get("terminal_id"),
        "atm_id": atm.get("terminal_id"),
        "name": atm.get("atm_number") or atm.get("terminal_id"),
        "bank": atm.get("branch") or "",
        "address": atm.get("address") or "",
        "lat": atm["lat"],
        "lon": atm["lon"],
        "status": atm.get("status") or "unknown",
        "balance": bal if bal is not None else 0,
        "balance_pct": atm.get("balance_pct") or 0,
        "refill_amount": refill,
    }


def build_regional_routes(
    atms: List[Dict[str, Any]],
    branches: List[Dict[str, Any]],
    status: str = "warning",
    speed_kmh: float = AVG_SPEED_KMH,
    max_stops: int = 12,
    snap_roads: bool = True,
) -> Dict[str, Any]:
    speed = speed_kmh or AVG_SPEED_KMH
    valid = [
        b for b in branches
        if int(b.get("incassation") or 0) == 1
        and b.get("lat") is not None
        and b.get("lon") is not None
    ]
    eligible = [a for a in atms if a.get("lat") is not None and a.get("lon") is not None]

    if status == "critical":
        targets = [a for a in eligible if a.get("status") == "critical"]
    elif status == "warning":
        targets = [a for a in eligible if a.get("status") in ("critical", "warning")]
    else:
        targets = list(eligible)

    # Норма / нет баланса → не заправляем. Никакого fallback на все ATM.

    depots_by_region: Dict[str, List[Dict[str, Any]]] = {}
    for b in valid:
        region = _item_region(b)
        if not region:
            continue
        b = dict(b)
        b["_canon_region"] = region
        depots_by_region.setdefault(region, []).append(b)

    groups: Dict[str, List[Dict[str, Any]]] = {}
    unmatched_region_atms: List[str] = []
    for a in targets:
        region = _item_region(a)
        if not region:
            unmatched_region_atms.append(str(a.get("terminal_id")))
            continue
        groups.setdefault(region, []).append(a)

    cars: List[Dict[str, Any]] = []
    unserved: List[Dict[str, Any]] = []

    for region, region_atms in groups.items():
        depots = depots_by_region.get(region) or []
        if not depots:
            unserved.append({
                "region": region,
                "atms": [a["terminal_id"] for a in region_atms],
                "reason": "В этом вилояте нет филиала с «Инкассация = 1»",
            })
            continue

        assignments: Dict[str, Dict[str, Any]] = {
            str(b.get("id") or b.get("local_code")): {"branch": b, "atms": []}
            for b in depots
        }
        for atm in region_atms:
            depot = min(depots, key=lambda d: km(d, atm))
            key = str(depot.get("id") or depot.get("local_code"))
            assignments[key]["atms"].append(atm)

        for part in assignments.values():
            branch, pts = part["branch"], part["atms"]
            if not pts:
                continue
            for chunk_i, chunk in enumerate(_split_by_capacity(branch, pts, max_stops)):
                seq = optimize_tour(branch, chunk)
                route_pts = [branch, *seq, branch]
                raw_km = sum(km(route_pts[i], route_pts[i + 1]) for i in range(len(route_pts) - 1))
                road_km = raw_km * ROAD_FACTOR
                minutes = round(road_km / speed * 60)
                stops = [_stop_payload(a) for a in seq]
                refill_total = sum(s["refill_amount"] for s in stops)
                code = branch.get("local_code") or branch.get("number") or ""
                label = f"{region} · {code}"
                if chunk_i:
                    label += f" · рейс {chunk_i + 1}"
                cars.append({
                    "region": region,
                    "label": label,
                    "departure_branch": {
                        "local_code": branch.get("local_code"),
                        "address": branch.get("address"),
                        "name": f"Филиал {code}",
                        "lat": branch["lat"],
                        "lon": branch["lon"],
                    },
                    "stops": stops,
                    "geometry": [{"lat": p["lat"], "lon": p["lon"]} for p in route_pts],
                    "distance_km": round(road_km, 2),
                    "total_dist_km": round(road_km, 2),
                    "est_time_min": minutes,
                    "refill_total": refill_total,
                })

    if unmatched_region_atms:
        unserved.append({
            "region": "Не указан",
            "atms": unmatched_region_atms,
            "reason": "Не удалось определить вилоят ATM",
        })

    cars.sort(key=lambda c: (c["region"], c["label"]))
    if snap_roads and cars:
        _snap_cars_to_roads(cars, speed)

    assign_calendar_dates(cars)

    return {
        "strategy": "Только ATM ниже нормы → свой вилоят → ближайший филиал → NN+2-opt → дороги OSRM → календарь",
        "cars": cars,
        "unserved_regions": unserved,
        "fallback_unknown_balances": False,
        "diagnostics": {
            "atms_total": len(atms),
            "atms_with_coordinates": len(eligible),
            "eligible_branches": len(valid),
            "target_atms": len(targets),
            "skipped_ok": sum(1 for a in eligible if a.get("status") == "ok"),
            "regions_with_targets": len(groups),
            "regions_with_depots": len(depots_by_region),
            "matched_regions": sorted(set(groups) & set(depots_by_region)),
        },
        "total_stops": sum(len(c["stops"]) for c in cars),
        "total_dist_km": round(sum(c["distance_km"] for c in cars), 2),
        "est_time_min": sum(c["est_time_min"] for c in cars),
    }


def apply_live_states(atms: List[Dict[str, Any]], states: Sequence[Dict[str, Any]]) -> None:
    """Overlay live/simulation balances onto ATM rows (in-memory)."""
    by_id = {str(s.get("terminal_id")): s for s in states if s.get("terminal_id")}
    for atm in atms:
        st = by_id.get(str(atm.get("terminal_id")))
        if not st:
            continue
        cap = atm.get("capacity") or DEFAULT_CAPACITY
        if st.get("balance") is not None:
            try:
                bal = int(st["balance"])
            except (TypeError, ValueError):
                bal = atm.get("balance")
            atm["balance"] = bal
            atm["balance_pct"] = round(bal / cap * 100, 1) if cap and bal is not None else None
        status = st.get("status")
        if status in ("ok", "warning", "critical", "unknown"):
            atm["status"] = status
        elif atm.get("balance") is not None and cap:
            pct = atm["balance"] / cap
            if pct < LOW_CASH_PCT:
                atm["status"] = "critical"
            elif pct < WARNING_CASH_PCT:
                atm["status"] = "warning"
            else:
                atm["status"] = "ok"


def assign_calendar_dates(cars: List[Dict[str, Any]], workday_min: int = 8 * 60) -> None:
    """Pack each viloyat's trips into working days starting today (UTC+5)."""
    today = datetime.now(_TASHKENT_TZ).date()
    by_region: Dict[str, List[Dict[str, Any]]] = {}
    for car in cars:
        by_region.setdefault(car["region"], []).append(car)

    for group in by_region.values():
        group.sort(key=lambda c: (
            0 if any(s.get("status") == "critical" for s in c["stops"]) else 1,
            -len(c["stops"]),
        ))
        day_offset = 0
        used = 0
        for car in group:
            dur = int(car.get("est_time_min") or 45)
            if used and used + dur > workday_min:
                day_offset += 1
                used = 0
            planned = today + timedelta(days=day_offset)
            car["planned_date"] = planned.isoformat()
            if any(s.get("status") == "critical" for s in car["stops"]):
                car["priority"] = "critical"
            elif any(s.get("status") == "warning" for s in car["stops"]):
                car["priority"] = "high"
            else:
                car["priority"] = "planned"
            used += dur


def _osrm_geometry(points: Sequence[Dict[str, Any]], timeout: int = 12) -> Tuple[Optional[List[Dict[str, float]]], Optional[float]]:
    if len(points) < 2:
        return None, None
    coords = ";".join(f"{p['lon']},{p['lat']}" for p in points)
    url = f"{OSRM_BASE}/route/v1/driving/{coords}?overview=full&geometries=geojson&steps=false"
    try:
        import ssl
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except Exception:
            ctx = ssl._create_unverified_context()
        req = urllib.request.Request(url, headers={"User-Agent": "bank-intelligence/1.0"})
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        log.warning("OSRM unavailable: %s", exc)
        return None, None
    if payload.get("code") != "Ok" or not payload.get("routes"):
        return None, None
    route = payload["routes"][0]
    geometry = [
        {"lat": lat, "lon": lon}
        for lon, lat in route["geometry"]["coordinates"]
    ]
    return geometry, route.get("distance", 0) / 1000.0


def _snap_cars_to_roads(cars: List[Dict[str, Any]], speed_kmh: float) -> None:
    speed = speed_kmh or AVG_SPEED_KMH

    def _job(car: Dict[str, Any]):
        geom, dist = _osrm_geometry(car.get("geometry") or [])
        return car, geom, dist

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(_job, car) for car in cars]
        for fut in as_completed(futures):
            car, geom, dist = fut.result()
            if not geom or not dist:
                car["routing_provider"] = "straight"
                continue
            car["geometry"] = geom
            car["distance_km"] = round(dist, 2)
            car["total_dist_km"] = round(dist, 2)
            car["est_time_min"] = round(dist / speed * 60)
            car["routing_provider"] = "osrm"
