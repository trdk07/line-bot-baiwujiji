"""
百無禁忌 LINE Bot — FastAPI 應用程式入口。
"""

from fastapi import FastAPI
from app.routers import webhook

app = FastAPI(
    title="百無禁忌 LINE Bot",
    version="0.1.0",
)

# --- 掛載路由 ---
app.include_router(webhook.router)


# --- Health Check ---
@app.get("/")
async def root():
    return {"status": "ok", "message": "百無禁忌 LINE Bot is running"}


@app.get("/health")
async def health_check():
    return {"status": "ok", "version": app.version}
