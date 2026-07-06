from unittest.mock import patch

from app.services import slots_service as ss


def test_set_open_slots_filters_invalid_times():
    saved = {}

    with patch.object(ss, "_load_month", return_value={}), \
         patch.object(ss, "_save_month", side_effect=lambda month, data: saved.update(data) or True):
        ok, conflicts = ss.set_open_slots("2026-07", {"2026-07-12": ["12:00", "15:00", "00:00"]})

    assert ok is True
    assert conflicts == []
    assert saved == {"2026-07-12": ["15:00", "00:00"]}


def test_set_open_slots_blocks_removing_taken_slot():
    existing = {"2026-07-12": ["15:00", "16:00"]}
    with patch.object(ss, "_load_month", return_value=existing), \
         patch("app.services.slots_service.get_taken_slots", return_value={"16:00"}), \
         patch.object(ss, "_save_month") as save:
        ok, conflicts = ss.set_open_slots("2026-07", {"2026-07-12": ["15:00"]})

    assert ok is False
    assert conflicts == [{"date": "2026-07-12", "time": "16:00"}]
    save.assert_not_called()
