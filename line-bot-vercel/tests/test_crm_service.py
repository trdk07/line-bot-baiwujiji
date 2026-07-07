import app.services.crm_service as crm
from app.services.crm_service import parse_birth_date


def test_parse_birth_date_western_year():
    assert parse_birth_date("1990/5/15 早上八點") == "1990-05-15"


def test_parse_birth_date_roc_year():
    assert parse_birth_date("民國79年5月15日") == "1990-05-15"


def test_parse_birth_date_unparseable():
    assert parse_birth_date("屬馬的") is None


def test_record_error_includes_notion_message_and_404_hint():
    crm._record_error(404, '{"code": "object_not_found", "message": "Could not find data source"}')
    detail = crm.get_last_error()
    assert "HTTP 404" in detail
    assert "object_not_found" in detail
    assert "連接" in detail  # 404 附上分享 integration 的提示


def test_record_error_non_json_body():
    crm._record_error(500, "Internal Server Error")
    assert "HTTP 500 Internal Server Error" in crm.get_last_error()


def test_fail_appends_last_error():
    crm._record_error(404, '{"code": "object_not_found", "message": "x"}')
    ok, msg = crm._fail("客戶檔案建立/查詢失敗")
    assert ok is False
    assert msg.startswith("客戶檔案建立/查詢失敗（HTTP 404")


def test_sync_without_api_key_reports_missing_config(monkeypatch):
    from app import config
    monkeypatch.setattr(crm, "get_settings", lambda: config.Settings(
        line_channel_secret="x", line_channel_access_token="x", notion_api_key=""
    ))
    ok, msg = crm.sync_booking_to_crm({"u": "U123", "n": "測試"})
    assert ok is False
    assert msg == "NOTION_API_KEY 未設定"


def _fake_settings(monkeypatch):
    from app import config
    monkeypatch.setattr(crm, "get_settings", lambda: config.Settings(
        line_channel_secret="x", line_channel_access_token="x", notion_api_key="secret"
    ))


def test_sync_existing_customer_updates_status(monkeypatch):
    _fake_settings(monkeypatch)
    monkeypatch.setattr(crm, "find_customer_by_line_id",
                        lambda uid: crm.CustomerLookup("found", customer={"id": "page-1"}))
    calls = {}
    monkeypatch.setattr(crm, "update_customer_status",
                        lambda pid, status: calls.setdefault("status", (pid, status)) or True)
    monkeypatch.setattr(crm, "create_comm_record", lambda payload, pid: True)
    ok, msg = crm.sync_booking_to_crm({"u": "U1", "n": "老客戶"})
    assert ok is True
    assert msg == "老客戶補記錄"
    assert calls["status"] == ("page-1", "服务中")


def test_sync_new_customer_creates_profile(monkeypatch):
    _fake_settings(monkeypatch)
    monkeypatch.setattr(crm, "find_customer_by_line_id",
                        lambda uid: crm.CustomerLookup("not_found"))
    monkeypatch.setattr(crm, "create_customer", lambda payload: "page-new")
    monkeypatch.setattr(crm, "create_comm_record", lambda payload, pid: True)
    ok, msg = crm.sync_booking_to_crm({"u": "U2", "n": "新客戶"})
    assert ok is True
    assert msg == "新客戶建檔"


def test_sync_reports_lookup_failure(monkeypatch):
    _fake_settings(monkeypatch)
    monkeypatch.setattr(crm, "find_customer_by_line_id",
                        lambda uid: crm.CustomerLookup("error", error="HTTP 404 …"))
    ok, msg = crm.sync_booking_to_crm({"u": "U3", "n": "查不到"})
    assert ok is False
    assert "客戶檔案查詢失敗" in msg
    assert "HTTP 404" in msg


def test_find_customer_returns_error_when_post_returns_none(monkeypatch):
    _fake_settings(monkeypatch)
    crm._record_error(404, '{"code": "object_not_found", "message": "x"}')
    monkeypatch.setattr(crm, "_post", lambda *a, **k: None)
    lookup = crm.find_customer_by_line_id("U4")
    assert lookup.failed is True
    assert "HTTP 404" in lookup.error
