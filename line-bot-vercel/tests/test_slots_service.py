from app.services.slots_service import parse_open_lines


def test_parse_open_lines_mixed_valid_and_invalid():
    entries, errors = parse_open_lines("/open\n7/12 15 16:00 00\n7/x 25")
    assert len(entries) == 1
    assert entries[0][1] == ["15:00", "16:00", "00:00"]
    assert errors


def test_parse_open_lines_rejects_unselectable_time():
    entries, errors = parse_open_lines("/open\n7/12 12")
    assert entries == []
    assert "時段無效" in errors[0]
