"""
get_available_slots 的軟鎖定與跨午夜過濾邏輯測試。
不依賴真正的 KV / Google Calendar：state_service.get_taken_slots
與 calendar_service._get_calendar_service 皆以 mock 取代。
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from app.services import calendar_service as cs


def _next_weekday(target_weekday: int) -> str:
    """回傳未來（不含今天）下一個指定星期幾的日期字串，避免『今天已過去時段』干擾測試。"""
    today = datetime.now(cs.TW_TZ).date()
    d = today + timedelta(days=1)
    while d.weekday() != target_weekday:
        d += timedelta(days=1)
    return d.strftime("%Y-%m-%d")


def test_soft_lock_excludes_taken_slot_without_calendar():
    """未設定 Google Calendar 時，佇列中進行中預約的時段仍應被排除。"""
    monday = _next_weekday(0)
    with patch("app.services.state_service.get_taken_slots", return_value={"19:00"}):
        slots = cs.get_available_slots(monday)
    assert "19:00" not in slots
    assert set(slots) == {"15:00", "16:00", "23:00"}


def test_no_taken_slots_returns_all():
    monday = _next_weekday(0)
    with patch("app.services.state_service.get_taken_slots", return_value=set()):
        slots = cs.get_available_slots(monday)
    assert set(slots) == {"15:00", "16:00", "19:00", "23:00"}


def test_sunday_cross_midnight_slot_not_dropped_as_past():
    """週日隔天 00:00 的時段是未來時間，不應被誤判為『今天已過去』而濾掉。"""
    sunday = _next_weekday(6)
    with patch("app.services.state_service.get_taken_slots", return_value=set()):
        slots = cs.get_available_slots(sunday)
    assert slots == ["20:00", "21:00", "22:00", "23:00", "00:00"]
