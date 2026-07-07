"""付款 QR Code 圖檔伺服與網址解析測試。"""

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.services.payment_qr import QR_IMAGE_PATH, resolve_payment_qr_url, self_hosted_qr_url

client = TestClient(app)


def test_qr_image_file_is_bundled():
    assert QR_IMAGE_PATH.is_file()


def test_qr_image_route_serves_png():
    res = client.get("/qr-payment.png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"
    assert res.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_resolve_prefers_env_url(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_qr_image_url", "https://cdn.example.com/qr.png")
    monkeypatch.setattr(settings, "public_base_url", "https://bot.example.com")
    assert resolve_payment_qr_url() == "https://cdn.example.com/qr.png"


def test_resolve_falls_back_to_self_hosted_when_env_unset(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_qr_image_url", "")
    monkeypatch.setattr(settings, "public_base_url", "https://bot.example.com/")
    assert resolve_payment_qr_url() == "https://bot.example.com/qr-payment.png"


def test_resolve_falls_back_when_env_url_not_https(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_qr_image_url", "http://insecure.example.com/qr.png")
    monkeypatch.setattr(settings, "public_base_url", "https://bot.example.com")
    assert resolve_payment_qr_url() == "https://bot.example.com/qr-payment.png"


def test_resolve_empty_when_nothing_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_qr_image_url", "")
    monkeypatch.setattr(settings, "public_base_url", "")
    assert self_hosted_qr_url() == ""
    assert resolve_payment_qr_url() == ""
