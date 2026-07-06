from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app


client = TestClient(app)


def test_booking_html_injects_bot_basic_id_and_has_no_liff(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_basic_id", "@botid")

    res = client.get("/booking.html?token=test")

    assert res.status_code == 200
    assert "const BOT_BASIC_ID = \"@botid\"" in res.text
    assert "liff" not in res.text.lower()
    assert "line.me/R/oaMessage" in res.text


def test_get_slots_is_public(monkeypatch):
    monkeypatch.setattr("app.routers.api.get_open_slots", lambda month: {"2026-07-12": ["15:00"]})
    monkeypatch.setattr("app.services.calendar_service.get_busy_map", lambda start, end: {"2026-07-12": ["15:00"]})

    res = client.get("/api/slots?month=2026-07")

    assert res.status_code == 200
    assert res.json()["open"] == {"2026-07-12": ["15:00"]}
    assert res.json()["taken"] == {"2026-07-12": ["15:00"]}


def test_post_slots_requires_admin_page_token(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_page_token", "secret")

    res = client.post("/api/slots", json={"month": "2026-07", "data": {}, "token": "wrong"})

    assert res.status_code == 403


def test_post_slots_saves_with_valid_token(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_page_token", "secret")
    monkeypatch.setattr("app.routers.api.set_open_slots", lambda month, data: (True, []))

    res = client.post("/api/slots", json={"month": "2026-07", "data": {"2026-07-12": ["15:00"]}, "token": "secret"})

    assert res.status_code == 200
    assert res.json() == {"ok": True}


def test_post_slots_conflict_returns_409(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_page_token", "secret")
    monkeypatch.setattr("app.routers.api.set_open_slots", lambda month, data: (False, [{"date": "2026-07-12", "time": "15:00"}]))

    res = client.post("/api/slots", json={"month": "2026-07", "data": {}, "token": "secret"})

    assert res.status_code == 409
    assert res.json()["detail"]["conflicts"] == [{"date": "2026-07-12", "time": "15:00"}]
