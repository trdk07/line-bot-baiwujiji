"""付款 QR Code 圖檔來源解析。

vercel.json 的 rewrites 會把所有路徑導到 FastAPI，靜態檔案不會被 Vercel
直接伺服，所以 QR 圖改由 app 自己以 /qr-payment.png 路由回傳
（app/static/qr-payment.png 會隨 serverless function 一起部署，
與 templates/booking.html 同一種機制）。
"""

import os
from pathlib import Path

from app.config import get_settings
from app.templates.flex_messages import normalize_image_url

QR_IMAGE_PATH = Path(__file__).resolve().parents[1] / "static" / "qr-payment.png"
QR_IMAGE_ROUTE = "/qr-payment.png"


def _public_base_url() -> str:
    """取得可對外的 https base URL。

    優先用 PUBLIC_BASE_URL（使用者自訂網域時設定），未設定時退回 Vercel
    自動注入的網域環境變數 —— 這樣部署到 Vercel 上完全不需要任何手動設定，
    QR 圖就能自動用正確的網址對外提供。
    """
    base = (get_settings().public_base_url or "").strip().rstrip("/")
    if base.lower().startswith("https://"):
        return base
    # Vercel 部署時自動注入，無需使用者設定：
    #   VERCEL_PROJECT_PRODUCTION_URL → 正式網域（webhook 一律走這個）
    #   VERCEL_URL                    → 當次 deployment 的網址（後備）
    for env_name in ("VERCEL_PROJECT_PRODUCTION_URL", "VERCEL_URL"):
        host = (os.environ.get(env_name) or "").strip().strip("/")
        if host:
            return f"https://{host}"
    return ""


def self_hosted_qr_url() -> str:
    """app 自己伺服的 QR 圖網址；無法判定對外網址或圖檔不存在時回空字串。"""
    base = _public_base_url()
    if base and QR_IMAGE_PATH.is_file():
        return f"{base}{QR_IMAGE_ROUTE}"
    return ""


def resolve_payment_qr_url() -> str:
    """回傳匯款卡片要用的 QR 圖網址。

    優先採用 PAYMENT_QR_IMAGE_URL（經 normalize_image_url 修正分享頁網址），
    未設定或無效時退回 app 自帶的 /qr-payment.png —— 隨程式碼部署、
    Content-Type 保證是 image/png，LINE 一定載得到。
    """
    url = normalize_image_url(get_settings().payment_qr_image_url)
    return url or self_hosted_qr_url()
