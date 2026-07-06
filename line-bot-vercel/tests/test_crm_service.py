from app.services.crm_service import parse_birth_date


def test_parse_birth_date_western_year():
    assert parse_birth_date("1990/5/15 早上八點") == "1990-05-15"


def test_parse_birth_date_roc_year():
    assert parse_birth_date("民國79年5月15日") == "1990-05-15"


def test_parse_birth_date_unparseable():
    assert parse_birth_date("屬馬的") is None
