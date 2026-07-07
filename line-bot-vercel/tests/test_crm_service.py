import httpx

import app.services.crm_service as crm
from app.services.crm_service import parse_birth_date


def test_parse_birth_date_western_year():
    assert parse_birth_date("1990/5/15 早上八點") == "1990-05-15"


def test_parse_birth_date_roc_year():
    assert parse_birth_date("民國79年5月15日") == "1990-05-15"


def test_parse_birth_date_unparseable():
    assert parse_birth_date("屬馬的") is None


class _Resp:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


def _payload():
    return {"u": "U1", "n": "王小明", "b": "1990-01-01 08:00", "q": "想問感情", "d": "2026-07-12", "t": "15:00"}


def test_find_customer_by_line_id_distinguishes_not_found_and_error(monkeypatch):
    monkeypatch.setattr(crm.get_settings(), "notion_api_key", "secret")

    def fake_not_found(url, headers=None, json=None, timeout=None):
        return _Resp(200, {"results": []})

    monkeypatch.setattr(httpx, "post", fake_not_found)
    result = crm.find_customer_by_line_id("U1")
    assert result.not_found is True
    assert result.customer is None

    def fake_404(url, headers=None, json=None, timeout=None):
        return _Resp(404, {"message": "Could not find data source"}, "not found")

    monkeypatch.setattr(httpx, "post", fake_404)
    result = crm.find_customer_by_line_id("U1")
    assert result.failed is True
    assert "HTTP 404" in result.error
    assert "share 給 integration" in result.error


def test_sync_query_error_does_not_create_customer(monkeypatch):
    monkeypatch.setattr(crm.get_settings(), "notion_api_key", "secret")
    created = False

    def fake_post(url, headers=None, json=None, timeout=None):
        return _Resp(404, {"message": "Could not find data source"}, "not found")

    def fake_create(payload):
        nonlocal created
        created = True
        return "page-id"

    monkeypatch.setattr(httpx, "post", fake_post)
    monkeypatch.setattr(crm, "create_customer", fake_create)

    ok, msg = crm.sync_booking_to_crm(_payload())

    assert ok is False
    assert "HTTP 404" in msg
    assert created is False


def test_sync_can_retry_successfully_after_lookup_error(monkeypatch):
    monkeypatch.setattr(crm.get_settings(), "notion_api_key", "secret")
    calls = []

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append(url)
        if len(calls) == 1:
            return _Resp(404, {"message": "Could not find data source"}, "not found")
        if url.endswith("/query"):
            return _Resp(200, {"results": []})
        return _Resp(200, {"id": "page-id"})

    monkeypatch.setattr(httpx, "post", fake_post)

    ok, msg = crm.sync_booking_to_crm(_payload())
    assert ok is False
    assert "HTTP 404" in msg

    ok, msg = crm.sync_booking_to_crm(_payload())
    assert ok is True
    assert msg == "新客戶建檔"
