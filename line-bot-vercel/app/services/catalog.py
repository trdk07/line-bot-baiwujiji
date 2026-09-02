"""
品項目錄 — 補庫與點燈的品項、價格、效期設定。

改價格或加品項直接改這裡；`item` key 會存進訂單 JSON，
已有訂單的 key 不要改名（label 可以隨時改）。
"""

CATALOG = {
    "treasury": {
        "label": "補庫",
        "prefix": "F",           # 對外訂單編號前綴（F-2026-0001）
        "price": 3600,           # 每庫
        "unit": "庫",
        "term_days": 90,         # 效期約一季（僅供顯示，補庫不追蹤到期）
        "remind_renewal": False,
        "items": {
            "wealth": "補財庫",
            "love": "姻緣庫",
            "noble": "貴人庫",
        },
    },
    "lamp": {
        "label": "點燈",
        "prefix": "L",           # L-2026-0001
        "price": 1800,           # 每燈
        "unit": "燈",
        "term_days": 90,         # 一季一期
        "remind_renewal": True,  # 到期前 7 天推送續燈提醒
        "items": {
            "seven": "七星燈",
            "bright": "光明燈",
            "noble": "貴人燈",
            "love": "姻緣燈",
            "wealth": "財運燈",
        },
    },
}

# 「姻緣」類品項可選單人／雙人（雙人需填對方資料）
COUPLE_ITEMS = {("treasury", "love"), ("lamp", "love")}

MAX_QTY = 5

RENEWAL_REMIND_DAYS = 7  # 點燈到期前幾天提醒續燈


def get_type(order_type: str) -> dict | None:
    return CATALOG.get(order_type)


def get_item_label(order_type: str, item: str) -> str:
    return CATALOG.get(order_type, {}).get("items", {}).get(item, "")


def calc_amount(order_type: str, qty: int) -> int:
    return CATALOG[order_type]["price"] * qty


def public_catalog() -> dict:
    """給報名頁用的目錄（含價格與品項清單）。"""
    return {
        t: {
            "label": c["label"],
            "price": c["price"],
            "unit": c["unit"],
            "termDays": c["term_days"],
            "maxQty": MAX_QTY,
            "items": [
                {"key": k, "label": v, "couple": (t, k) in COUPLE_ITEMS}
                for k, v in c["items"].items()
            ],
        }
        for t, c in CATALOG.items()
    }
