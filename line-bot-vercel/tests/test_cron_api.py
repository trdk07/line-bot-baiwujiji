from datetime import date

from app.routers.api import due_notifications


def test_due_notifications_open_reminder_on_25th():
    assert "open_next_month" in due_notifications(date(2026, 7, 25), False, [])


def test_due_notifications_monthly_summary_on_first():
    assert "monthly_summary" in due_notifications(date(2026, 8, 1), True, [])


def test_due_notifications_tomorrow_bookings():
    notices = due_notifications(date(2026, 7, 6), True, [{"booking": {}}])
    assert "tomorrow_customer" in notices
    assert "tomorrow_admin" in notices
