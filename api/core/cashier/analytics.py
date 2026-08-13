"""Analytics calculation engine for cashier performance, workload, and report generation."""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from ..db import _connect, dict_cursor
from .helpers import BACK_GROUPS, FRONT_GROUPS, clean_branch_name, norm
from .parsers import _classify_op_group
from .repository import init_cashier_tables


def _build_report_sql_filters(
    role: Optional[str] = None,
    position: Optional[str] = None,
    branch: Optional[str] = None,
    status: Optional[str] = None,
) -> tuple[str, list[Any]]:
    """Build SQL WHERE fragments to pre-filter reports before in-memory enrichment."""
    clauses: list[str] = []
    params: list[Any] = []

    if position and str(position).strip():
        clauses.append("LOWER(TRIM(COALESCE(position, ''))) = LOWER(%s)")
        params.append(str(position).strip())

    if branch and str(branch).strip():
        clauses.append("LOWER(COALESCE(branch_name, '')) LIKE %s")
        params.append(f"%{str(branch).strip().lower()}%")

    r_q = str(role or '').strip().lower()
    if r_q == 'front':
        clauses.append("(front_count > bek_count)")
    elif r_q == 'back':
        clauses.append("(bek_count >= front_count AND (bek_count > 0 OR front_count > 0))")

    st_q = str(status or '').strip().lower()
    if st_q == 'disciplined':
        clauses.append(
            "(NULLIF(TRIM(COALESCE(discipline_type, '')), '') IS NOT NULL "
            "OR NULLIF(TRIM(COALESCE(discipline_date_order, '')), '') IS NOT NULL "
            "OR NULLIF(TRIM(COALESCE(discipline_reason, '')), '') IS NOT NULL)"
        )

    where = " AND ".join(clauses) if clauses else "TRUE"
    return where, params


def cashier_role(row: Dict[str, Any]) -> Optional[str]:
    """Determine cashier role from operation counts. None if the cashier has no ops."""
    b = float(row.get('bek_count', 0) or 0)
    f = float(row.get('front_count', 0) or 0)
    if b == 0 and f == 0:
        return None
    return 'front' if f > b else 'back'


def _is_true_absent(row: Dict[str, Any]) -> bool:
    """Person is on maternity/vacation and did not work — the seat is empty."""
    if row.get('hr_status_code') not in ('maternity', 'vacation'):
        return False
    return float(row.get('operations_count') or 0) <= 0


def is_uncovered_absence(row: Dict[str, Any]) -> bool:
    """Empty seat: absent and no temporary replacement assigned."""
    if not _is_true_absent(row):
        return False
    if row.get('replaced_by_full_name'):
        return False
    return int(row.get('has_replacement') or 0) == 0


def apply_replacement_pairing(rows: List[Dict[str, Any]]) -> None:
    """Pair вакт. temps only to empty seats (0 operations). Mutates rows in place."""
    for x in rows:
        st = x.get('hr_status_code')
        if st == 'temporary':
            x['replacing_full_name'] = None
        elif st in ('maternity', 'vacation'):
            x['replaced_by_full_name'] = None
            x['has_replacement'] = 0

    def pair(temp: Dict[str, Any], absent: Dict[str, Any]) -> None:
        temp['replacing_full_name'] = absent.get('full_name')
        absent['replaced_by_full_name'] = temp.get('full_name')
        absent['has_replacement'] = 1

    ordered = sorted(rows, key=lambda z: (int(z.get('id') or 0), z.get('full_name') or ''))
    for i in range(len(ordered) - 1):
        a, b = ordered[i], ordered[i + 1]
        if (
            a.get('hr_status_code') == 'temporary'
            and _is_true_absent(b)
            and not a.get('replacing_full_name')
            and not b.get('replaced_by_full_name')
        ):
            pair(a, b)
        elif (
            _is_true_absent(a)
            and b.get('hr_status_code') == 'temporary'
            and not a.get('replaced_by_full_name')
            and not b.get('replacing_full_name')
        ):
            pair(b, a)

    def _zip_pair(groups: dict) -> None:
        for lst in groups.values():
            temps = [
                x for x in lst
                if x.get('hr_status_code') == 'temporary' and not x.get('replacing_full_name')
            ]
            absents = [x for x in lst if _is_true_absent(x) and not x.get('replaced_by_full_name')]
            for temp, absent in zip(temps, absents):
                pair(temp, absent)

    by_branch_pos: dict[tuple[str, str], list] = defaultdict(list)
    for x in rows:
        by_branch_pos[
            ((x.get('branch_name') or '').strip(), (x.get('position') or '').strip())
        ].append(x)
    _zip_pair(by_branch_pos)

    by_branch: dict[str, list] = defaultdict(list)
    for x in rows:
        by_branch[(x.get('branch_name') or '').strip()].append(x)
    _zip_pair(by_branch)


def _top_metric_value(row: Dict[str, Any], role: Optional[str] = None) -> float:
    """Value used for Top-10 ranking: BEK / FRONT count, or total ops."""
    r = str(role or '').strip().lower()
    if r == 'back':
        return float(row.get('bek_count', 0) or 0)
    if r == 'front':
        return float(row.get('front_count', 0) or 0)
    return float(row.get('operations_count', 0) or 0)


def _build_top_lists(
    rows: List[Dict[str, Any]],
    role: Optional[str] = None,
    limit: int = 10,
) -> tuple[list[Dict[str, Any]], dict[str, list]]:
    """Build global Top-N and per-position Top-N using the role-aware metric."""
    ranked = sorted(rows, key=lambda z: _top_metric_value(z, role), reverse=True)
    top_cashiers = [x for x in ranked if _top_metric_value(x, role) > 0][:limit]

    pos_groups: dict[str, list] = {}
    for x in rows:
        pos = (x.get('position') or '').strip() or 'Прочее'
        pos_groups.setdefault(pos, []).append(x)

    top_by_position = {
        p: [
            x for x in sorted(lst, key=lambda z: _top_metric_value(z, role), reverse=True)
            if _top_metric_value(x, role) > 0
        ][:limit]
        for p, lst in pos_groups.items()
    }
    return top_cashiers, top_by_position


_NORM_DAYS_FALLBACK = 22.0
_MINUTES_PER_DAY = 480.0


def _enrich(x: dict, detail: bool = False):
    """Enrich a cashier report row in-place and return (x, ops_dict)."""
    ops_cnt = float(x.get('operations_count', 0) or 0)
    ops_min = float(x.get('operations_minutes', 0) or 0)
    days = float(x.get('days_worked', 0) or 0)
    std_days = float(x.get('std_days', 0) or 0)
    norm_days = std_days or _NORM_DAYS_FALLBACK

    x['avg_seconds_per_operation'] = round(ops_min * 60 / ops_cnt, 1) if ops_cnt else 0
    x['operations_per_day'] = round(ops_cnt / days, 1) if days else 0

    raw = json.loads(x.get('metrics_json') or '{}')
    ops = raw.get('operations') if isinstance(raw, dict) and 'operations' in raw else (raw if isinstance(raw, dict) else {})
    if not x.get('employee_number'):
        x['employee_number'] = raw.get('employee_number', '') if isinstance(raw, dict) else ''
    x['branch_name'] = clean_branch_name(x.get('branch_name', ''))

    # Prefer Excel load_percent persisted on the row; recompute only if missing.
    lp = float(x.get('load_percent') or 0)
    if 0 < lp <= 1.0:
        lp = round(lp * 100, 1)
    if lp == 0 and days > 0 and ops_min > 0:
        denom = std_days or days
        lp = round((ops_min / (denom * _MINUTES_PER_DAY)) * 100, 1)
    x['load_percent'] = round(lp, 1)
    x['load_difference'] = float(x.get('load_difference') or 0)
    x['std_days'] = std_days

    x['cashier_type'] = cashier_role(x)

    bek_cnt = float(x.get('bek_count', 0) or 0)
    front_cnt = float(x.get('front_count', 0) or 0)
    split_total = bek_cnt + front_cnt
    x['bek_pct'] = round((bek_cnt / split_total) * 100, 1) if split_total else 0.0
    x['front_pct'] = round(100.0 - x['bek_pct'], 1) if split_total else 0.0
    x['days_worked_pct'] = round((days / norm_days) * 100, 1) if days else 0.0

    x['hours_worked'] = round(ops_min / 60, 1)
    mins = int(ops_min)
    x['hours_str'] = f"{mins // 60} ч {mins % 60} мин"

    _EXCLUDE_KEYWORDS = ('жамибек', 'jamibek', 'жамифронт', 'jamfront',
                          'жамиамали', 'bekfark', 'frontfark', 'жами')
    real_metrics = {
        n: v for n, v in ops.items()
        if isinstance(v, dict) and not any(k in norm(n).replace(' ', '') for k in _EXCLUDE_KEYWORDS)
    }
    real_ops_total = sum(v.get('count', 0) for v in real_metrics.values()) or ops_cnt or 1

    x['metrics'] = [
        {
            'name': n,
            'section': ('БЭК-операции' if _classify_op_group(n) == 'back' else 'ФРОНТ-операции'),
            'count': v.get('count', 0),
            'minutes': v.get('minutes', 0),
            'pct': round(v.get('count', 0) / real_ops_total * 100, 1),
        }
        for n, v in real_metrics.items()
    ]
    x['metrics'].sort(key=lambda m: m['count'], reverse=True)
    x['top_direction'] = x['metrics'][0]['name'] if x['metrics'] else '—'

    # Discipline / punishment data (pass-through from DB)
    x['discipline_type'] = x.get('discipline_type') or None
    x['discipline_date_order'] = x.get('discipline_date_order') or None
    x['discipline_reason'] = x.get('discipline_reason') or None
    x['has_discipline'] = bool(x['discipline_type'] or x['discipline_date_order'] or x['discipline_reason'])

    return x, ops


def cashier_analytics(
    import_id: Optional[int] = None,
    page: int = 1,
    page_size: int = 25,
    role: Optional[str] = None,
    search: Optional[str] = None,
    position: Optional[str] = None,
    status: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Retrieve filtered, paginated analytics summary for cashiers."""
    init_cashier_tables()
    with _connect() as c:
        cur = dict_cursor(c)
        if import_id is None:
            cur.execute('SELECT id FROM cashier_imports ORDER BY imported_at DESC, id DESC LIMIT 1')
            q = cur.fetchone()
            import_id = q['id'] if q else None

        info = None
        rows = []
        if import_id:
            cur.execute('SELECT * FROM cashier_imports WHERE id=%s', (import_id,))
            info_row = cur.fetchone()
            if info_row:
                info = dict(info_row)
                where_sql, where_params = _build_report_sql_filters(role, position, branch, status)
                cur.execute(
                    f'SELECT * FROM cashier_reports WHERE import_id=%s AND {where_sql} '
                    f'ORDER BY operations_count DESC',
                    [import_id, *where_params],
                )
                rows = [dict(z) for z in cur.fetchall()]

        # Fetch latest cashier statuses
        cur.execute('SELECT id, filename, imported_at FROM cashier_status_imports ORDER BY id DESC LIMIT 1')
        st_import = cur.fetchone()
        status_map = {}
        status_map_2word = {}
        unmatched_statuses = []
        if st_import:
            if not info:
                info = {
                    'id': 0, 'filename': st_import['filename'],
                    'imported_at': st_import['imported_at'], 'rows_count': 0,
                }
            cur.execute('SELECT * FROM cashier_statuses WHERE import_id=%s', (st_import['id'],))
            st_rows = cur.fetchall()
            for s in st_rows:
                s_dict = dict(s)
                n_fn = norm(s_dict['full_name'])
                status_map[n_fn] = s_dict
                words = n_fn.split()
                if len(words) >= 2:
                    status_map_2word[f"{words[0]} {words[1]}"] = s_dict
                unmatched_statuses.append(s_dict)
        cur.close()

        if not info:
            return {
                'summary': {}, 'cashiers': [], 'top_cashiers': [], 'categories': [], 'positions': [],
                'top_by_position': {}, 'import': None, 'page': 1, 'total_pages': 1, 'total': 0,
            }

    matched_status_names = set()
    vacant_kpi_keys = set()
    VACANT_KEYWORDS = ('вакант', 'вакансия', 'vakant', 'vakansiya', 'бош урин', 'буш урин', 'свобод')
    for x in rows:
        _enrich(x)
        n_fn = norm(x['full_name'])
        words = n_fn.split()

        is_vac_row = any(w in n_fn for w in VACANT_KEYWORDS)
        if is_vac_row:
            x['hr_status_code'] = 'vacant'
            x['hr_status_label'] = '⚪ Вакант (Свободная ставка)'
            x['branch_name'] = clean_branch_name(x.get('branch_name') or '')
            x['full_name'] = f"ВАКАНСИЯ ({x.get('position') or 'Кассир'})"
            v_key = f"{norm(x.get('position') or '')}_{norm(clean_branch_name(x.get('branch_name') or ''))[:6]}"
            vacant_kpi_keys.add(v_key)
        else:
            st = status_map.get(n_fn)
            if not st and len(words) >= 2:
                st = status_map_2word.get(f"{words[0]} {words[1]}")

            if st:
                matched_status_names.add(norm(st['full_name']))
                x['hr_status_code'] = st['status_code']
                x['hr_status_label'] = st['status_label']
                st_b = clean_branch_name(st.get('branch_name') or '')
                x_b = clean_branch_name(x.get('branch_name') or '')
                if st_b and 'не указан' not in st_b.lower():
                    x['branch_name'] = st_b
                elif x_b and 'не указан' not in x_b.lower():
                    x['branch_name'] = x_b
                else:
                    x['branch_name'] = st_b or x_b or 'Не указан'
                x['replacing_full_name'] = st.get('replacing_full_name')
                x['replaced_by_full_name'] = st.get('replaced_by_full_name')
                x['has_replacement'] = st.get('has_replacement', 0)
            else:
                x.setdefault('hr_status_code', 'active')
                x.setdefault('hr_status_label', '🟢 Работает')
                x['branch_name'] = clean_branch_name(x.get('branch_name') or '')

    # Add absent & vacant employees/positions from shtat who have no KPI record.
    # Skip when BEK/FRONT role filter is active — zero-ops dummies break role Top-10.
    role_q = str(role or '').strip().lower()
    KASSIR_KEYWORDS = ('kassir', 'кассир', 'kassa', 'касса', 'gazna', 'g\'azna')
    if role_q not in ('front', 'back'):
        for st in unmatched_statuses:
            st_code = st.get('status_code', 'active')
            if st_code not in ('maternity', 'vacation', 'sick', 'vacant'):
                continue
            st_pos = st.get('position') or ''
            n_pos = norm(st_pos)

            if not any(kw in n_pos for kw in KASSIR_KEYWORDS):
                continue

            if st_code == 'vacant':
                if len(vacant_kpi_keys) > 0:
                    continue
                dummy_row = {
                    'id': 900000 + st['id'],
                    'import_id': import_id,
                    'tab_number': '—',
                    'employee_number': '',
                    'full_name': st['full_name'],
                    'position': st_pos if st_pos else 'Кассир',
                    'days_worked': 0,
                    'std_days': 0,
                    'operations_count': 0,
                    'operations_minutes': 0,
                    'bek_count': 0,
                    'bek_minutes': 0,
                    'front_count': 0,
                    'front_minutes': 0,
                    'load_percent': 0,
                    'load_difference': 0,
                    'metrics_json': '{}',
                    'hr_status_code': 'vacant',
                    'hr_status_label': '⚪ Вакант (Свободная ставка)',
                    'branch_name': clean_branch_name(st.get('branch_name') or ''),
                    'replacing_full_name': st.get('replacing_full_name'),
                    'replaced_by_full_name': st.get('replaced_by_full_name'),
                    'has_replacement': 0,
                    'discipline_type': None,
                    'discipline_date_order': None,
                    'discipline_reason': None,
                }
                _enrich(dummy_row)
                rows.append(dummy_row)
            elif norm(st['full_name']) not in matched_status_names:
                dummy_row = {
                    'id': 900000 + st['id'],
                    'import_id': import_id,
                    'tab_number': '—',
                    'employee_number': '',
                    'full_name': st['full_name'],
                    'position': st_pos if st_pos else 'Кассир',
                    'days_worked': 0,
                    'std_days': 0,
                    'operations_count': 0,
                    'operations_minutes': 0,
                    'bek_count': 0,
                    'bek_minutes': 0,
                    'front_count': 0,
                    'front_minutes': 0,
                    'load_percent': 0,
                    'load_difference': 0,
                    'metrics_json': '{}',
                    'hr_status_code': st_code,
                    'hr_status_label': st['status_label'],
                    'branch_name': clean_branch_name(st.get('branch_name') or ''),
                    'replacing_full_name': st.get('replacing_full_name'),
                    'replaced_by_full_name': st.get('replaced_by_full_name'),
                    'has_replacement': st.get('has_replacement', 0),
                    'discipline_type': None,
                    'discipline_date_order': None,
                    'discipline_reason': None,
                }
                _enrich(dummy_row)
                rows.append(dummy_row)

    apply_replacement_pairing(rows)

    # Re-apply role filter after enrichment (covers any edge cases past SQL pre-filter)
    if role_q in ('front', 'back'):
        rows = [x for x in rows if x.get('cashier_type') == role_q]

    # Snapshot before status/search filters — used for position/branch dropdowns
    all_rows_list = list(rows)
    positions_list = sorted({
        (x.get('position') or '').strip() or 'Прочее' for x in all_rows_list
    })

    # Filters (status/search require HR merge; role/position/branch/disciplined pre-filtered in SQL)
    if status and str(status).strip():
        st_q = str(status).strip().lower()
        if st_q == 'no_replacement':
            rows = [x for x in rows if is_uncovered_absence(x)]
        elif st_q == 'maternity':
            rows = [x for x in rows if x.get('hr_status_code') == 'maternity']
        elif st_q == 'disciplined':
            rows = [x for x in rows if x.get('has_discipline')]
        elif st_q in ('active', 'vacation', 'temporary', 'vacant', 'sick'):
            rows = [x for x in rows if x.get('hr_status_code') == st_q]

    if search and str(search).strip():
        q_words = norm(search).split()
        if q_words:
            rows = [
                x for x in rows
                if all(
                    w in norm(
                        f"{x.get('full_name', '')} {x.get('position', '')} "
                        f"{x.get('tab_number', '')} {x.get('employee_number', '')} "
                        f"{x.get('hr_status_label', '')} {x.get('branch_name', '')} "
                        f"{x.get('raw_note', '')}"
                    )
                    for w in q_words
                )
            ]

    branches_list = sorted({
        (x.get('branch_name') or '').strip()
        for x in all_rows_list if (x.get('branch_name') or '').strip()
    })

    if branch and str(branch).strip():
        b_q = str(branch).strip().lower()
        rows = [x for x in rows if b_q in (x.get('branch_name') or '').strip().lower()]

    # Top-10 after all filters: BEK→bek_count, FRONT→front_count, else→operations_count
    top_cashiers, top_by_position = _build_top_lists(rows, role_q)

    # Keep table order consistent with Top-10 metric
    rows = sorted(rows, key=lambda z: _top_metric_value(z, role_q), reverse=True)

    # Category aggregation
    cats: dict[str, dict] = {}
    allowed = BACK_GROUPS if role_q == 'back' else FRONT_GROUPS if role_q == 'front' else None
    bek_tot = 0.0
    front_tot = 0.0

    for x in rows:
        m_json = json.loads(x.get('metrics_json') or '{}')
        ops_data = m_json.get('operations') if isinstance(m_json, dict) and 'operations' in m_json else (m_json if isinstance(m_json, dict) else {})
        row_has_ops = False
        for n, v in ops_data.items():
            if not isinstance(v, dict):
                continue
            n_norm = norm(n).replace(' ', '')
            if any(k in n_norm for k in ('жамибек', 'jamibek', 'жамифронт', 'jamfront',
                                          'жамиамали', 'beкфарк', 'фронтфарк', 'bekfark',
                                          'frontfark', 'жами')):
                continue
            cnt = float(v.get('count', 0) or 0)
            mins = float(v.get('minutes', 0) or 0)
            op_group = _classify_op_group(n)
            if op_group == 'back':
                bek_tot += cnt
                row_has_ops = True
            elif op_group == 'front':
                front_tot += cnt
                row_has_ops = True
            if allowed is not None and op_group != role_q:
                continue
            a = cats.setdefault(n, {'name': n, 'count': 0, 'minutes': 0})
            a['count'] += cnt
            a['minutes'] += mins

        if not row_has_ops:
            bek_tot += float(x.get('bek_count', 0) or 0)
            front_tot += float(x.get('front_count', 0) or 0)

    tot_cat_count = sum(c['count'] for c in cats.values()) or 1
    categories_list = []
    for c_item in sorted(cats.values(), key=lambda item: item['count'], reverse=True):
        c_item['pct'] = round(c_item['count'] / tot_cat_count * 100, 1)
        categories_list.append(c_item)

    total = len(rows)
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    start = (page - 1) * page_size

    total_ops = bek_tot + front_tot
    total_min = sum(float(x.get('operations_minutes', 0) or 0) for x in rows)
    working = [x for x in rows if float(x.get('operations_count') or 0) > 0]
    tot_load = sum(float(x.get('load_percent', 0) or 0) for x in working)

    summary = {
        'cashiers': total,
        'working_cashiers': len(working),
        'operations': round(total_ops),
        'minutes': round(total_min),
        'hours': round(total_min / 60, 1),
        'avg_seconds_per_operation': round(total_min * 60 / total_ops, 1) if total_ops else 0,
        'avg_load_percent': round(tot_load / len(working), 1) if working else 0,
        'bek_operations': round(bek_tot),
        'bek_pct': round(bek_tot / total_ops * 100, 1) if total_ops else 0,
        'front_operations': round(front_tot),
        'front_pct': round(front_tot / total_ops * 100, 1) if total_ops else 0,
        'back_cashiers': sum(1 for x in rows if x.get('cashier_type') == 'back'),
        'front_cashiers': sum(1 for x in rows if x.get('cashier_type') == 'front'),
        'active_cashiers': sum(1 for x in rows if x.get('hr_status_code') == 'active'),
        'vacation_cashiers': sum(1 for x in rows if x.get('hr_status_code') == 'vacation'),
        'maternity_cashiers': sum(1 for x in rows if x.get('hr_status_code') == 'maternity'),
        'temporary_cashiers': sum(1 for x in rows if x.get('hr_status_code') == 'temporary'),
        'sick_cashiers': sum(1 for x in rows if x.get('hr_status_code') == 'sick'),
        'vacant_positions': sum(1 for x in rows if x.get('hr_status_code') == 'vacant'),
        'no_replacement_cashiers': sum(1 for x in rows if is_uncovered_absence(x)),
        'disciplined_cashiers': sum(1 for x in rows if x.get('has_discipline')),
        'active_filter': role or 'all',
    }

    return {
        'import': info,
        'summary': summary,
        'cashiers': rows[start:start + page_size],
        'top_cashiers': top_cashiers,
        'categories': categories_list,
        'positions': positions_list,
        'branches': branches_list,
        'top_by_position': top_by_position,
        'page': page,
        'page_size': page_size,
        'total': total,
        'total_pages': max(1, (total + page_size - 1) // page_size),
    }


def cashier_detail(report_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve detailed analytics for a single cashier by report_id."""
    init_cashier_tables()
    if report_id >= 900000:
        st_id = report_id - 900000
        with _connect() as c:
            cur = dict_cursor(c)
            cur.execute('SELECT * FROM cashier_statuses WHERE id=%s', (st_id,))
            st = cur.fetchone()
            if not st:
                cur.close()
                return None
            st_info = dict(st)
            cur.close()
            r = {
                'id': report_id,
                'import_id': 0,
                'tab_number': '—',
                'employee_number': '',
                'full_name': st_info['full_name'],
                'position': st_info.get('position') or 'Кассир',
                'days_worked': 0,
                'std_days': 0,
                'operations_count': 0,
                'operations_minutes': 0,
                'bek_count': 0,
                'bek_minutes': 0,
                'front_count': 0,
                'front_minutes': 0,
                'load_percent': 0,
                'load_difference': 0,
                'metrics_json': '{}',
                'filename': 'Реестр штата',
                'imported_at': datetime.now(timezone.utc).isoformat(),
            }
        x, _ = _enrich(dict(r), True)
        x['hr_status_code'] = st_info['status_code']
        x['hr_status_label'] = st_info['status_label']
        x['branch_name'] = st_info.get('branch_name', '')
        x['replacing_full_name'] = st_info.get('replacing_full_name')
        x['replaced_by_full_name'] = st_info.get('replaced_by_full_name')
        x['has_replacement'] = st_info.get('has_replacement', 0)
        return x

    with _connect() as c:
        cur = dict_cursor(c)
        cur.execute(
            'SELECT r.*, i.filename, i.imported_at FROM cashier_reports r '
            'JOIN cashier_imports i ON i.id=r.import_id WHERE r.id=%s',
            (report_id,)
        )
        r = cur.fetchone()
        if not r:
            cur.close()
            return None

        cur.execute('SELECT id FROM cashier_status_imports ORDER BY id DESC LIMIT 1')
        st_import = cur.fetchone()
        st_info = None
        if st_import:
            cur.execute(
                'SELECT * FROM cashier_statuses WHERE import_id=%s AND (full_name=%s OR lower(full_name)=lower(%s))',
                (st_import['id'], r['full_name'], r['full_name'])
            )
            st = cur.fetchone()
            if st:
                st_info = dict(st)
        cur.close()

    x, _ = _enrich(dict(r), True)

    if st_info:
        x['hr_status_code'] = st_info['status_code']
        x['hr_status_label'] = st_info['status_label']
        x['branch_name'] = clean_branch_name(st_info.get('branch_name', ''))
        x['replacing_full_name'] = st_info.get('replacing_full_name')
        x['replaced_by_full_name'] = st_info.get('replaced_by_full_name')
        x['has_replacement'] = st_info.get('has_replacement', 0)
    else:
        x['hr_status_code'] = x.get('hr_status_code') or 'active'
        x['hr_status_label'] = x.get('hr_status_label') or '🟢 Работает'
        x['branch_name'] = clean_branch_name(x.get('branch_name') or '')
        x['replacing_full_name'] = x.get('replacing_full_name')
        x['replaced_by_full_name'] = x.get('replaced_by_full_name')
        x['has_replacement'] = x.get('has_replacement', 1)

    return x
