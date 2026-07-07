"""
半自動 Notion CRM 同步。
"""

import json
import logging
import re
from datetime import date

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

CUSTOMER_DS = "1c250abc-cc15-8103-aa87-000bad27de6f"
COMM_DS = "1c250abc-cc15-810a-8561-000b682503ff"
NOTION_VERSION = "2025-09-03"

# 最近一次 Notion API 失敗原因，讓 /crm ok 的回覆能帶出實際錯誤
_last_error = ""


def _record_error(status_code: int, body_text: str):
    global _last_error
    try:
        data = json.loads(body_text)
        detail = f"{data.get('code', '')} {data.get('message', '')}".strip()
    except (json.JSONDecodeError, TypeError):
        detail = body_text[:200]
    hint = ""
    if status_code == 404:
        hint = "；請確認 Notion 資料庫已在「⋯ → 連接」加入這支 integration"
    _last_error = f"HTTP {status_code} {detail}{hint}"


def get_last_error() -> str:
    return _last_error


def parse_birth_date(text: str) -> str | None:
    if not text:
        return None
    m = re.search(r"(\d{2,4})\s*(?:[-/年])\s*(\d{1,2})\s*(?:[-/月])\s*(\d{1,2})", text)
    if not m:
        return None
    year, month, day = [int(x) for x in m.groups()]
    if year < 1911:
        year += 1911
    try:
        date(year, month, day)
        return f"{year:04d}-{month:02d}-{day:02d}"
    except ValueError:
        return None


def _headers() -> dict | None:
    key = get_settings().notion_api_key
    if not key:
        return None
    return {
        "Authorization": f"Bearer {key}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _post(path: str, payload: dict) -> dict | None:
    headers = _headers()
    if not headers:
        return None
    try:
        r = httpx.post(f"https://api.notion.com/v1/{path}", headers=headers, json=payload, timeout=10.0)
        if r.status_code >= 300:
            logger.error("Notion POST %s failed: HTTP %d body=%s", path, r.status_code, r.text)
            _record_error(r.status_code, r.text)
            return None
        return r.json()
    except Exception as e:
        logger.error("Notion POST %s error: %s", path, e)
        global _last_error
        _last_error = str(e)
        return None


def _patch(path: str, payload: dict) -> bool:
    headers = _headers()
    if not headers:
        return False
    try:
        r = httpx.patch(f"https://api.notion.com/v1/{path}", headers=headers, json=payload, timeout=10.0)
        if r.status_code >= 300:
            logger.error("Notion PATCH %s failed: HTTP %d body=%s", path, r.status_code, r.text)
            _record_error(r.status_code, r.text)
            return False
        return True
    except Exception as e:
        logger.error("Notion PATCH %s error: %s", path, e)
        global _last_error
        _last_error = str(e)
        return False


def _title(text: str) -> dict:
    return {"title": [{"text": {"content": text or "未命名"}}]}


def _rich(text: str) -> dict:
    return {"rich_text": [{"text": {"content": text}}]} if text else {"rich_text": []}


def _date(value: str | None) -> dict:
    return {"date": {"start": value}} if value else {"date": None}


def find_customer_by_line_id(user_id: str) -> dict | None:
    payload = {"filter": {"property": "LINE", "rich_text": {"equals": user_id}}, "page_size": 1}
    data = _post(f"data_sources/{CUSTOMER_DS}/query", payload)
    return (data.get("results") or [None])[0] if data else None


def create_customer(payload: dict) -> str | None:
    props = {"客户姓名": _title(payload.get("n", "")), "LINE": _rich(payload.get("u", "")), "状态": {"select": {"name": "初次咨询"}}}
    birth = parse_birth_date(payload.get("b", ""))
    if birth:
        props["阳历"] = _date(birth)
    data = _post("pages", {"parent": {"data_source_id": CUSTOMER_DS}, "properties": props})
    return data.get("id") if data else None


def update_customer_status(page_id: str, status: str) -> bool:
    return _patch(f"pages/{page_id}", {"properties": {"状态": {"select": {"name": status}}}})


def create_comm_record(payload: dict, customer_page_id: str) -> bool:
    detail = f"【預約諮詢】{payload.get('q', '')}\n生辰原文：{payload.get('b', '')}"
    props = {
        "客户名称": _title(payload.get("n", "")),
        "咨询方式": {"select": {"name": "线上"}},
        "沟通日期": _date(payload.get("d")),
        "詳細溝通內容": _rich(detail),
        "客户档案": {"relation": [{"id": customer_page_id}]},
    }
    return bool(_post("pages", {"parent": {"data_source_id": COMM_DS}, "properties": props}))


def _fail(reason: str) -> tuple[bool, str]:
    detail = get_last_error()
    return False, f"{reason}（{detail}）" if detail else reason


def sync_booking_to_crm(pending: dict) -> tuple[bool, str]:
    global _last_error
    _last_error = ""
    if not get_settings().notion_api_key:
        return False, "NOTION_API_KEY 未設定"
    customer = find_customer_by_line_id(pending.get("u", ""))
    is_new = customer is None
    page_id = create_customer(pending) if is_new else customer.get("id")
    if not page_id:
        return _fail("客戶檔案建立/查詢失敗")
    if not is_new and not update_customer_status(page_id, "服务中"):
        return _fail("客戶狀態更新失敗")
    if not create_comm_record(pending, page_id):
        return _fail("溝通記錄建立失敗")
    return True, "新客戶建檔" if is_new else "老客戶補記錄"
