import json
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


def set_open_slots(month: str, data: dict) -> tuple[bool, list]:
    cleaned = {}
    for date_str, times in data.items():
        if _month_of(date_str) != month:
            continue
        valid = [t for t in times if t in SELECTABLE_TIMES]
        if valid:
            cleaned[date_str] = sorted(set(valid), key=_time_order)

    existing = _load_month(month)
    conflicts = []
    for date_str, old_times in existing.items():
        removed = set(old_times) - set(cleaned.get(date_str, []))
        blocked = sorted(removed & get_taken_slots(date_str), key=_time_order)
        conflicts.extend({"date": date_str, "time": time_str} for time_str in blocked)

    if conflicts:
        return False, conflicts
    return _save_month(month, cleaned), []


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


def get_month_total(month: str) -> int:
    return sum(len(times) for times in _load_month(month).values())
