"""
get_available_slots 的手動開放時段、軟鎖定與跨午夜過濾測試。
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from app.services import calendar_service as cs


def _future_date() -> str:
    return (datetime.now(cs.TW_TZ).date() + timedelta(days=7)).strftime("%Y-%m-%d")


def test_soft_lock_excludes_taken_slot_without_calendar():
    date_str = _future_date()
    with patch("app.services.slots_service.get_open_slots", return_value={date_str: ["15:00", "16:00", "20:00"]}), \
         patch("app.services.state_service.get_taken_slots", return_value={"16:00"}):
        slots = cs.get_available_slots(date_str)
    assert slots == ["15:00", "20:00"]


def test_no_open_slots_returns_empty():
    with patch("app.services.slots_service.get_open_slots", return_value={}):
        assert cs.get_available_slots(_future_date()) == []


def test_cross_midnight_slot_not_dropped_as_past():
    date_str = _future_date()
    with patch("app.services.slots_service.get_open_slots", return_value={date_str: ["23:00", "00:00"]}), \
         patch("app.services.state_service.get_taken_slots", return_value=set()):
        slots = cs.get_available_slots(date_str)
    assert slots == ["23:00", "00:00"]
