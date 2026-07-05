"""
calendar_service 純函式測試：時段產生、可預約日期、日期標籤格式化。
重點涵蓋跨午夜時段（週日 20:00-01:00）的邊界情況。
"""

from datetime import datetime, timedelta

from app.services.calendar_service import (
    _generate_slot_times,
    get_next_available_dates,
    format_date_label,
    WEEKLY_SLOTS,
    TW_TZ,
)


def test_generate_slot_times_monday():
    """週一 15:00-17:00, 19:00-20:00, 23:00-00:00(隔天) → 4 個時段。"""
    monday = datetime.strptime("2026-01-05", "%Y-%m-%d")  # 週一
    assert monday.weekday() == 0
    slots = _generate_slot_times(monday)
    times = [s.strftime("%H:%M") for s in slots]
    assert times == ["15:00", "16:00", "19:00", "23:00"]


def test_generate_slot_times_sunday_crosses_midnight():
    """週日 20:00-01:00（隔天）→ 5 個時段，最後一個是隔天 00:00。"""
    sunday = datetime.strptime("2026-01-11", "%Y-%m-%d")  # 週日
    assert sunday.weekday() == 6
    slots = _generate_slot_times(sunday)
    times = [s.strftime("%H:%M") for s in slots]
    assert times == ["20:00", "21:00", "22:00", "23:00", "00:00"]
    # 最後一個時段（00:00）實際日期應為隔天，而非週日當天
    assert slots[-1].date() == sunday.date() + timedelta(days=1)


def test_generate_slot_times_no_business_day():
    """週三沒有營業時段（WEEKLY_SLOTS 未定義）→ 回傳空清單。"""
    wednesday = datetime.strptime("2026-01-07", "%Y-%m-%d")
    assert wednesday.weekday() == 2
    assert wednesday.weekday() not in WEEKLY_SLOTS
    assert _generate_slot_times(wednesday) == []


def test_get_next_available_dates_only_business_weekdays():
    dates = get_next_available_dates()
    assert len(dates) <= 6
    assert len(dates) == len(set(dates))  # 無重複

    today = datetime.now(TW_TZ).date()
    parsed = [datetime.strptime(d, "%Y-%m-%d").date() for d in dates]

    for d in parsed:
        assert d > today  # 只給明天以後的日期
        assert d.weekday() in WEEKLY_SLOTS  # 只給有營業時段的星期

    assert parsed == sorted(parsed)  # 按時間先後排序


def test_format_date_label_weekday_names():
    assert format_date_label("2026-01-05") == "1/5（一）"  # 週一
    assert format_date_label("2026-01-11") == "1/11（日）"  # 週日
