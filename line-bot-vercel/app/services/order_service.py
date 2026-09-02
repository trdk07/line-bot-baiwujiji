"""
補庫／點燈訂單 — 建單、LINE 綁定、付款回報、完成與續燈提醒。

與預約（booking）的差異：品項價格固定，送出即進入 awaiting_payment
（不需要老師先確認日期），付款回報後由老師確認收款完成訂單。

KV 結構：
  order:{order_no}       訂單 JSON（永久保存，取消也留紀錄）
  order_queue            List，進行中訂單編號（awaiting_payment / payment_reported）
  user_orders:{user_id}  List，該 LINE 用戶綁定過的訂單編號（進度查詢用）
  lamp_active            List，效期內的點燈訂單編號（續燈提醒掃描用）
"""

import json
import logging
import time

from app.config import get_settings
from app.services.catalog import (
    CATALOG, COUPLE_ITEMS, MAX_QTY, RENEWAL_REMIND_DAYS,
    calc_amount, get_item_label, get_type,
)
from app.services.notify_service import notify_admin_flex, push_flex_to_user, push_text_to_user
from app.services.payment_qr import resolve_linepay_qr_url, resolve_payment_qr_url
from app.services.state_service import (
    _pipeline, kv_cmd, kv_get,
    enqueue_crm, incr_monthly_stat, next_order_no, record_customer_visit,
)
from app.templates import flex_messages as fm

logger = logging.getLogger(__name__)

ORDER_ACTIVE_STATUSES = {"awaiting_payment", "payment_reported"}

LAMP_TERM_SECS = CATALOG["lamp"]["term_days"] * 24 * 3600
RENEWAL_REMIND_SECS = RENEWAL_REMIND_DAYS * 24 * 3600


def _save(order: dict):
    kv_cmd("SET", f"order:{order['no']}", json.dumps(order, ensure_ascii=False))


def get_order(order_no: str) -> dict | None:
    raw = kv_get(f"order:{order_no}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def validate_order_input(order_type: str, item: str, qty, name: str, birth: str) -> str:
    """回傳錯誤訊息字串；通過驗證回傳空字串。"""
    cfg = get_type(order_type)
    if not cfg:
        return "品項類型不正確"
    if item not in cfg["items"]:
        return "品項不正確"
    if not isinstance(qty, int) or not (1 <= qty <= MAX_QTY):
        return f"數量需為 1–{MAX_QTY}"
    if not (name or "").strip():
        return "請填寫姓名"
    if not (birth or "").strip():
        return "請填寫出生年月日"
    return ""


def create_order(
    order_type: str, item: str, qty: int,
    name: str, gender: str = "", birth: str = "", addr: str = "",
    note: str = "", partner: str = "", user_id: str = "", source: str = "web",
) -> dict:
    """建立訂單（狀態直接進 awaiting_payment，金額固定不需老師先確認）。

    回傳訂單 dict；輸入不合法時 raise ValueError。
    """
    err = validate_order_input(order_type, item, qty, name, birth)
    if err:
        raise ValueError(err)
    if (order_type, item) in COUPLE_ITEMS and partner:
        partner = partner.strip()
    else:
        partner = partner.strip() if (order_type, item) in COUPLE_ITEMS else ""

    cfg = get_type(order_type)
    now = int(time.time())
    order = {
        "no": next_order_no(cfg["prefix"]),
        "ty": order_type,
        "it": item,
        "q": qty,
        "amt": calc_amount(order_type, qty),
        "n": name.strip(),
        "g": gender.strip(),
        "b": birth.strip(),
        "addr": addr.strip(),
        "note": note.strip(),
        "pt": partner,
        "u": user_id,
        "s": "awaiting_payment",
        "c": now,
        "us": now,
        "src": source,
    }
    if not order["no"]:
        raise ValueError("系統忙碌中，請稍後再試")

    commands = [
        ["SET", f"order:{order['no']}", json.dumps(order, ensure_ascii=False)],
        ["RPUSH", "order_queue", order["no"]],
    ]
    if user_id:
        commands.append(["RPUSH", f"user_orders:{user_id}", order["no"]])
    _pipeline(commands)
    incr_monthly_stat("order_new")
    return order


def order_label(order: dict) -> str:
    """例：「補財庫 ×2庫（B-2026-0012）」的前半段。"""
    cfg = get_type(order.get("ty", "")) or {"unit": ""}
    return f"{get_item_label(order.get('ty', ''), order.get('it', ''))} ×{order.get('q', 1)}{cfg['unit']}"


def list_active_orders() -> list:
    """進行中訂單（依建立順序）。順帶清掉佇列裡的孤兒編號。"""
    queue = kv_cmd("LRANGE", "order_queue", 0, -1) or []
    if not queue:
        return []
    raws = _pipeline([["GET", f"order:{no}"] for no in queue])
    orders, stale = [], []
    for no, raw in zip(queue, raws):
        if not raw:
            stale.append(no)
            continue
        try:
            orders.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            stale.append(no)
    if stale:
        _pipeline([["LREM", "order_queue", 0, no] for no in stale])
    return orders


def list_user_orders(user_id: str, limit: int = 10) -> list:
    """該用戶綁定過的訂單，新的在前。"""
    nos = kv_cmd("LRANGE", f"user_orders:{user_id}", -limit, -1) or []
    if not nos:
        return []
    raws = _pipeline([["GET", f"order:{no}"] for no in nos])
    orders = []
    for raw in raws:
        if raw:
            try:
                orders.append(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                pass
    orders.reverse()
    return orders


def send_order_payment_card(order: dict) -> bool:
    """把付款卡（金額＋雙 QR＋已付款按鈕）推給已綁定的客人。"""
    if not order.get("u"):
        return False
    cfg = get_type(order["ty"])
    return push_flex_to_user(
        order["u"],
        fm.order_payment_card(
            order["no"], cfg["label"], order_label(order), order["amt"],
            resolve_payment_qr_url(), linepay_qr_url=resolve_linepay_qr_url(),
        ),
    )


def notify_order_created(order: dict):
    """新訂單通知老師；已綁定 LINE 的客人同時收到付款卡。"""
    settings = get_settings()
    cfg = get_type(order["ty"])
    if settings.admin_line_user_id:
        bound_note = "已綁定 LINE" if order.get("u") else "官網下單，等待客人回 LINE 綁定"
        push_text_to_user(
            settings.admin_line_user_id,
            f"🧾 新{cfg['label']}申請\n"
            f"{order.get('n', '')}｜{order_label(order)}\n"
            f"金額 NT$ {order['amt']:,}｜編號 {order['no']}\n"
            f"（{bound_note}）\n\n"
            f"客人回報付款後，回覆 /paid {order['no']} 或到後台確認收款。",
        )
    if order.get("u"):
        send_order_payment_card(order)


def bind_order(order_no: str, user_id: str) -> tuple[dict | None, str]:
    """把訂單綁到 LINE 用戶（官網下單後的「綁定」訊息）。回傳 (order, 錯誤訊息)。"""
    order = get_order(order_no)
    if not order:
        return None, "找不到這筆訂單，請確認編號。"
    if order.get("u") and order["u"] != user_id:
        return None, "這筆訂單已綁定其他 LINE 帳號。"
    if order.get("s") not in ORDER_ACTIVE_STATUSES and order.get("s") != "done":
        return None, "這筆訂單已取消，如需重新申請請再填一次。"
    if not order.get("u"):
        order["u"] = user_id
        _save(order)
        kv_cmd("RPUSH", f"user_orders:{user_id}", order_no)
    return order, ""


def find_user_awaiting_orders(user_id: str) -> list:
    return [o for o in list_active_orders() if o.get("u") == user_id and o.get("s") == "awaiting_payment"]


def mark_order_paid_reported(order: dict) -> bool:
    """客人回報已付款：awaiting_payment → payment_reported。"""
    if order.get("s") != "awaiting_payment":
        return False
    order["s"] = "payment_reported"
    order["us"] = int(time.time())
    _save(order)
    return True


def complete_order(order: dict) -> dict:
    """老師確認收款：完成訂單、累積顧客檔案與統計、排 CRM、設定點燈效期。"""
    settings = get_settings()
    now = int(time.time())
    order["s"] = "done"
    order["us"] = now
    if order.get("ty") == "lamp":
        order["exp"] = now + LAMP_TERM_SECS
    _save(order)
    kv_cmd("LREM", "order_queue", 0, order["no"])
    if order.get("ty") == "lamp":
        kv_cmd("RPUSH", "lamp_active", order["no"])

    incr_monthly_stat(f"{order['ty']}_done")
    user_id = order.get("u", "")
    if user_id:
        record_customer_visit(user_id, order.get("n", ""), time.strftime("%Y-%m-%d"))

    notified = False
    if user_id:
        notified = push_flex_to_user(user_id, fm.order_confirmed_card(order))

    if settings.notion_api_key and user_id:
        payload = {
            "u": user_id,
            "n": order.get("n", ""),
            "b": order.get("b", ""),
            "q": f"【{get_type(order['ty'])['label']}】{order_label(order)}（{order['no']}）",
            "d": time.strftime("%Y-%m-%d"),
            "t": "",
        }
        if enqueue_crm(payload):
            notify_admin_flex(user_id, fm.crm_preview_card(payload, "訂單完成"), prefix_text="CRM 資料待確認")

    return {"ok": True, "notified": notified}


def cancel_order(order: dict, notify: bool = True) -> dict:
    """取消訂單（保留紀錄供對帳，僅從進行中佇列移除）。"""
    order["s"] = "cancelled"
    order["us"] = int(time.time())
    _save(order)
    kv_cmd("LREM", "order_queue", 0, order["no"])
    notified = False
    if notify and order.get("u"):
        notified = push_text_to_user(
            order["u"],
            f"您的{order_label(order)}申請（{order['no']}）已取消。\n\n"
            f"如有疑問或想重新申請，歡迎直接在此告知 🙏",
        )
    return {"ok": True, "notified": notified}


def sweep_lamp_renewals(now_ts: int | None = None) -> dict:
    """點燈效期掃描（每日 cron）：到期前 7 天提醒續燈（一次），到期後移出效期清單。"""
    settings = get_settings()
    now_ts = now_ts or int(time.time())
    result = {"reminded": 0, "expired": 0}
    nos = kv_cmd("LRANGE", "lamp_active", 0, -1) or []
    if not nos:
        return result
    raws = _pipeline([["GET", f"order:{no}"] for no in nos])
    for no, raw in zip(nos, raws):
        if not raw:
            kv_cmd("LREM", "lamp_active", 0, no)
            continue
        try:
            order = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            kv_cmd("LREM", "lamp_active", 0, no)
            continue
        exp = order.get("exp")
        if not exp:
            kv_cmd("LREM", "lamp_active", 0, no)
            continue
        if exp <= now_ts:
            kv_cmd("LREM", "lamp_active", 0, no)
            result["expired"] += 1
            continue
        if exp - now_ts <= RENEWAL_REMIND_SECS:
            lock = kv_cmd("SET", f"reminder:lamp_renew:{no}", "1", "NX", "EX", 30 * 24 * 3600)
            if lock == "OK" and order.get("u"):
                item_label = get_item_label("lamp", order.get("it", ""))
                push_text_to_user(
                    order["u"],
                    f"🏮 續燈提醒\n\n您的{item_label}（{order['no']}）將於 7 天內圓滿到期。\n\n"
                    f"想延續光明，輸入「點燈」即可續點；有任何問題也歡迎直接詢問 🙏",
                )
                if settings.admin_line_user_id:
                    push_text_to_user(
                        settings.admin_line_user_id,
                        f"🏮 已發送續燈提醒\n{order.get('n', '')}｜{item_label}（{order['no']}）",
                    )
                result["reminded"] += 1
    return result
