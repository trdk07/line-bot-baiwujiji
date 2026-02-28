"""
百無禁忌 LINE Bot — FastAPI 應用程式入口。
"""

from fastapi import FastAPI
from app.config import get_settings
from app.routers import webhook

settings = get_settings()

app = FastAPI(
    title="百無禁忌 LINE Bot",
    version="0.1.0",
    docs_url="/docs" if settings.env == "development" else None,
)

# --- 掛載路由 ---
app.include_router(webhook.router)


# --- Health Check ---
@app.get("/health")
async def health_check():
    """給部署平台的健康檢查端點。"""
    return {"status": "ok", "version": app.version}
