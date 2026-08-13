"""Helper utilities and constants for cashier analytics and data parsing."""
from __future__ import annotations

import re
from typing import Any, Dict


def clean_branch_name(raw_branch: str) -> str:
    """Clean up MFO numbers and bank prefixes from branch names."""
    if not raw_branch:
        return ''
    s = str(raw_branch).strip()
    s = re.sub(r'^\d{5}\s*-\s*[0-9A-Za-z]{4,5}\s*', '', s)
    s = re.sub(r'^[0-9A-Za-z]{4,5}\s*-\s*', '', s)
    s = re.sub(r'^\d{5}\s*', '', s)
    s = re.sub(r'["\']O[^\s]*zsanoatqurilishbank["\']?\s*ATB\s*', '', s, flags=re.IGNORECASE)
    s = re.sub(r'ATB\s*', '', s, flags=re.IGNORECASE)
    s = s.strip(' -"\'' + '\xa0')
    s = re.sub(r'bank\s+xizmatlar[i]?\s+markaz[i]?', 'ЦБУ', s, flags=re.IGNORECASE)
    s = re.sub(r'bank\s+xizmatlar[i]?\s+ofis[i]?', 'ОБУ', s, flags=re.IGNORECASE)
    s = re.sub(r'центр\s+банковских\s+услуг', 'ЦБУ', s, flags=re.IGNORECASE)
    s = re.sub(r'офис\s+банковских\s+услуг', 'ОБУ', s, flags=re.IGNORECASE)
    return s.strip()


def norm(v: Any) -> str:
    """Normalise a cell value to a lowercase, ASCII-friendly string for matching."""
    if v is None:
        return ''
    s = str(v).lower().strip()
    # Cyrillic digraphs that appear in Uzbek sources
    cyr_map = {'қ': 'к', 'ў': 'у', 'ғ': 'г', 'ҳ': 'х', 'ё': 'е', 'ҷ': 'ч', 'ӣ': 'и'}
    for src, dst in cyr_map.items():
        s = s.replace(src, dst)
    s = re.sub(r"['`′ʼʻʼ]", '', s)
    s = re.sub(r'[^\w]+', ' ', s, flags=re.UNICODE)
    return s.strip()


def num(v: Any) -> float:
    """Safely convert any cell value to a float."""
    if v is None:
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s or s in ('-', '—', '- ', ' - ', 'None', 'null', 'nan'):
        return 0.0
    # Strip Excel non-breaking spaces and similar artefacts
    s = s.replace('\xa0', '').replace('\u202f', '')
    try:
        return float(s)
    except ValueError:
        cleaned = re.sub(r'[^0-9,.\-]', '', s).replace(',', '.')
        if not cleaned or cleaned in ('-', '.', '-.'):
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return 0.0


def sval(v: Any) -> str:
    """Safely convert a cell value to a stripped string, removing Excel artefacts."""
    if v is None:
        return ''
    s = str(v).strip().replace('\xa0', ' ').replace('\u202f', ' ')
    # Remove leading/trailing apostrophes that openpyxl sometimes prepends
    s = s.strip("'")
    return s.strip()


# Keywords used to classify operation names into BEK (back-office) or FRONT groups.
# "банкомат" — kassirning BEK operatsiyasi (Excel ustun nomi), ATM monitoring emas.
BACK_KEYWORDS = (
    'амалга оширилган операциялар сони',
    'банкомат',
    'касса мудири',
    'кечки кассир',
    'назоратчи',
    'купюра санаш',
)
FRONT_KEYWORDS = (
    'ваш', 'валюта', 'коммунал', 'пластик', 'накд', 'кирим чиким хужжати',
)
SUMMARY_KEYWORDS = (
    'жами бек', 'jami bek', 'жами фронт', 'jami front',
    'жами амалиетлар', 'jami amaliyotlar',
    'бек фарк', 'фронт фарк', 'bek fark', 'front fark',
)

# Canonical display names for recognised operation types (used in metrics_json)
BACK_GROUPS = {
    'Амалга оширилган операциялар сони (кирим-чиқим)',
    'Банкоматга пул қўйиш',
    'Касса мудири',
    'Кечки кассир',
    'Назоратчи кассир ролини бажарганда',
    'Купюра санаш',
}
FRONT_GROUPS = {
    'Кирим, чиқим ҳужжатини текшириш, расмийлаштириш',
    'ВАЛЮТА 100$',
    'ВАЛЮТА 100,01–1000$',
    'ВАЛЮТА 1000,01–5000$',
    'ВАЛЮТА 10000$',
    'ВАЛЮТА 5000,01–10000$',
    'Коммунал тўловлар (кирим-чиқим)',
    'Пластик карта тарқатиш',
    'Пластикдан нақд пул ечиш',
}
EXCLUDED_GROUPS = {
    'БЕК фарқ', 'ФРОНТ фарқ', 'Жами (БЕК)', 'Жами (ФРОНТ)',
    'Жами амалиётлар', 'Жами',
    'БЕК фарк', 'ФРОНТ фарк', 'Жами БЕК', 'Жами ФРОНТ',
    'Жами (Бек офис)', 'Жами (Фронт офис)',
    'Бек офис', 'Фронт офис',
}


def parse_hr_status(raw_note: str, position: str = '', full_name: str = '') -> Dict[str, Any]:
    """Parse HR status code and label from raw note string, position, and full_name."""
    raw_note = str(raw_note or '').strip()
    position = str(position or '').strip()
    full_name = str(full_name or '').strip()
    n_str = norm(f"{raw_note} {position} {full_name}").replace(' ', '')

    if any(w in n_str for w in ('vacant', 'вакант', 'вакансия', 'свобод', 'vakant', 'vakansiya', 'bosh', 'bush', 'бош', 'буш')):
        code, label = 'vacant', '⚪ Вакансия (Свободная ставка)'
    elif any(w in n_str for w in ('dekret', 'декрет')):
        code, label = 'maternity', '🟣 В декрете'
    elif any(w in n_str for w in ('mexnat', 'мехнат', 'отпуск', 'tatil', 'татил')):
        code, label = 'vacation', '🔵 В отпуске (Трудовой отпуск)'
    elif any(w in n_str for w in ('vakt', 'вакт', 'вактинча', 'замещ', 'вактинчалик', 'zamesh')):
        code, label = 'temporary', '🟡 Временный сотрудник'
    elif any(w in n_str for w in ('kasal', 'касал', 'больн')):
        code, label = 'sick', '🔴 Болен (Больничный)'
    else:
        code, label = 'active', '🟢 Работает'

    return {
        'status_code': code,
        'status_label': label,
        'has_replacement': 1 if code == 'active' else 0,
        'replacing_full_name': None,
        'replaced_by_full_name': None,
        'raw_note': raw_note,
    }
