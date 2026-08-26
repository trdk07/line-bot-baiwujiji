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


def test_booking_html_has_loading_error_and_flow_hints(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "bot_basic_id", "@botid")

    res = client.get("/booking.html")

    assert res.status_code == 200
    assert 'id="status"' in res.text          # 載入中/錯誤面板
    assert 'id="statusRetry"' in res.text     # 重新載入按鈕
    assert 'id="legend"' in res.text          # 月曆圖例
    assert 'id="endtime"' in res.text         # 預估結束時間
    assert "送出後會發生什麼" in res.text      # 流程說明
    assert 'id="welcome"' in res.text         # 回頭客歡迎橫幅


def test_api_me_rejects_bad_signature(monkeypatch):
    monkeypatch.setattr("app.routers.api.get_customer_profile", lambda uid: {"n": "Alice", "c": 2, "last": "2026-07-01"})

    res = client.get("/api/me?uid=u1&sig=wrong")

    assert res.status_code == 200
    assert res.json() == {"ok": True, "returning": False}


def test_api_me_returns_profile_with_valid_signature(monkeypatch):
    from app.services.state_service import customer_link_sig

    monkeypatch.setattr("app.routers.api.get_customer_profile", lambda uid: {"n": "Alice", "c": 2, "last": "2026-07-01"})

    res = client.get(f"/api/me?uid=u1&sig={customer_link_sig('u1')}")

    assert res.status_code == 200
    assert res.json() == {"ok": True, "returning": True, "name": "Alice", "count": 2, "last": "2026-07-01"}


def test_api_me_unknown_customer_is_not_returning(monkeypatch):
    from app.services.state_service import customer_link_sig

    monkeypatch.setattr("app.routers.api.get_customer_profile", lambda uid: None)

    res = client.get(f"/api/me?uid=u1&sig={customer_link_sig('u1')}")

    assert res.status_code == 200
    assert res.json() == {"ok": True, "returning": False}


def test_admin_page_is_served():
    res = client.get("/admin.html")

    assert res.status_code == 200
    assert 'id="monthRows"' in res.text
    assert "管理後台" in res.text


def test_api_stats_requires_token(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_page_token", "secret")

    assert client.get("/api/stats?token=wrong").status_code == 403


def test_api_stats_returns_months_and_active_counts(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "admin_page_token", "secret")
    monkeypatch.setattr(
        "app.routers.api.get_monthly_stats",
        lambda months: [{"month": m, "new": 0, "done": 0, "released": 0} for m in months],
    )
    monkeypatch.setattr(
        "app.routers.api.get_all_queue_bookings",
        lambda: [
            {"ref": "u1|1", "user_id": "u1", "booking": {"s": "pending"}},
            {"ref": "u2|2", "user_id": "u2", "booking": {"s": "awaiting_payment"}},
            {"ref": "u3|3", "user_id": "u3", "booking": {"s": "pending"}},
        ],
    )
    monkeypatch.setattr("app.routers.api.get_all_done_bookings", lambda: [{"ref": "u4|4"}])

    res = client.get("/api/stats?token=secret")

    assert res.status_code == 200
    data = res.json()
    assert len(data["months"]) == 6
    assert data["active"] == {"pending": 2, "awaiting_payment": 1, "payment_reported": 0}
    assert data["doneRecent"] == 1
