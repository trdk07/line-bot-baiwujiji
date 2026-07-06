"""
calendar/slots 純函式測試：手動開放時段、跨午夜與日期標籤。
"""

from datetime import datetime, timedelta
from unittest.mock import patch

from app.services.calendar_service import format_date_label
from app.services.slots_service import TW_TZ, slot_datetime


def test_slot_datetime_crosses_midnight():
    dt = slot_datetime("2026-07-12", "00:00")
    assert dt.strftime("%Y-%m-%d %H:%M") == "2026-07-13 00:00"


def test_slot_datetime_regular_time_same_day():
    dt = slot_datetime("2026-07-12", "20:00")
    assert dt.strftime("%Y-%m-%d %H:%M") == "2026-07-12 20:00"


def test_get_next_available_dates_delegates_open_dates():
    from app.services.calendar_service import get_next_available_dates

    with patch("app.services.slots_service.get_open_dates", return_value=["2026-07-12"]):
        assert get_next_available_dates() == ["2026-07-12"]


def test_format_date_label_weekday_names():
    assert format_date_label("2026-01-05") == "1/5（一）"
    assert format_date_label("2026-01-11") == "1/11（日）"
