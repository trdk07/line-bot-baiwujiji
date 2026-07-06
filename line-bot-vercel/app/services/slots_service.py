import json
import re
from datetime import datetime, timedelta, timezone

from app.services.state_service import kv_cmd, kv_get, get_taken_slots

TW_TZ = timezone(timedelta(hours=8))
SELECTABLE_TIMES = [f"{h:02d}:00" for h in range(13, 24)] + ["00:00"]
OPEN_TTL = 100 * 24 * 60 * 60


def _month_key(month: str) -> str:
    return f"open:{month}"


def _month_of(date_str: str) -> str:
    return date_str[:7]


def _load_month(month: str) -> dict:
    raw = kv_get(_month_key(month))
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return {d: sorted(set(times), key=_time_order) for d, times in data.items() if times}
    except (json.JSONDecodeError, TypeError):
        return {}


def _save_month(month: str, data: dict) -> bool:
    cleaned = {d: sorted(set(times), key=_time_order) for d, times in data.items() if times}
    return kv_cmd("SET", _month_key(month), json.dumps(cleaned, ensure_ascii=False), "EX", OPEN_TTL) == "OK"


def _time_order(time_str: str) -> int:
    return 24 if time_str == "00:00" else int(time_str[:2])


def get_open_slots(month: str) -> dict:
    return _load_month(month)


def add_open_slots(entries: list) -> bool:
    grouped = {}
    for date_str, times in entries:
        grouped.setdefault(_month_of(date_str), {}).setdefault(date_str, set()).update(times)
    ok = True
    for month, dates in grouped.items():
        data = _load_month(month)
        for date_str, times in dates.items():
            data.setdefault(date_str, [])
            data[date_str] = sorted(set(data[date_str]) | set(times), key=_time_order)
        ok = _save_month(month, data) and ok
    return ok


def remove_open_slots(date_str: str, times: list | None) -> tuple[bool, list]:
    data = _load_month(_month_of(date_str))
    existing = set(data.get(date_str, []))
    if not existing:
        return True, []
    targets = existing if times is None else set(times)
    blocked = sorted(targets & get_taken_slots(date_str), key=_time_order)
    removable = targets - set(blocked)
    remaining = sorted(existing - removable, key=_time_order)
    if remaining:
        data[date_str] = remaining
    else:
        data.pop(date_str, None)
    return _save_month(_month_of(date_str), data), blocked


def get_open_dates(days: int = 30) -> list:
    today = datetime.now(TW_TZ).date()
    months = sorted({(today + timedelta(days=i)).strftime("%Y-%m") for i in range(1, days + 1)})
    data = {}
    for month in months:
        data.update(_load_month(month))
    dates = []
    for i in range(1, days + 1):
        date_str = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        if data.get(date_str):
            dates.append(date_str)
        if len(dates) >= 6:
            break
    return dates


def slot_datetime(date_str: str, time_str: str) -> datetime:
    base = datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M").replace(tzinfo=TW_TZ)
    return base + timedelta(days=1) if time_str == "00:00" else base


def _normalize_time(token: str) -> str | None:
    if re.fullmatch(r"\d{1,2}", token):
        token = f"{int(token):02d}:00"
    elif re.fullmatch(r"\d{1,2}:00", token):
        token = f"{int(token.split(':')[0]):02d}:00"
    else:
        return None
    return token if token in SELECTABLE_TIMES else None


def _infer_year(month: int, day: int) -> int:
    today = datetime.now(TW_TZ).date()
    year = today.year
    candidate = datetime(year, month, day).date()
    return year + 1 if candidate < today else year


def parse_open_lines(text: str) -> tuple[list, list]:
    entries, errors = [], []
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and lines[0].lower().startswith("/open"):
        lines = lines[1:]
    for idx, line in enumerate(lines, 1):
        parts = line.split()
        if len(parts) < 2 or not re.fullmatch(r"\d{1,2}/\d{1,2}", parts[0]):
            errors.append(f"第 {idx} 行看不懂：`{line}`")
            continue
        month, day = [int(x) for x in parts[0].split("/")]
        try:
            date_str = datetime(_infer_year(month, day), month, day).strftime("%Y-%m-%d")
        except ValueError:
            errors.append(f"第 {idx} 行日期無效：`{line}`")
            continue
        times = [_normalize_time(p) for p in parts[1:]]
        if not times or any(t is None for t in times):
            errors.append(f"第 {idx} 行時段無效：`{line}`")
            continue
        entries.append((date_str, sorted(set(times), key=_time_order)))
    return entries, errors


def get_month_total(month: str) -> int:
    return sum(len(times) for times in _load_month(month).values())
