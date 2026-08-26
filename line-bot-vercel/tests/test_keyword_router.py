"""
keyword_router.match_keyword 的意圖比對測試。
關鍵字比對順序即優先權，這裡同時涵蓋正例（應匹配的意圖）與
負例（容易被更寬鬆的 pattern 搶先匹配、但不該匹配到錯誤意圖的情況）。
"""

import pytest

from app.services.keyword_router import match_keyword


POSITIVE_CASES = [
    # --- 管理員指令 ---
    ("/off", "bot_off"),
    ("/on", "bot_on"),
    ("/ok", "booking_ok"),
    ("/ok 2", "booking_ok"),
    ("/no", "booking_no"),
    ("/no 3", "booking_no"),
    ("/paid", "booking_paid"),
    ("/paid 1", "booking_paid"),
    ("/list", "booking_list"),
    ("/clear", "booking_clear"),
    ("/clear yes", "booking_clear"),
    ("/change 2026-03-01 14:00", "booking_change"),
    ("/change 1 2026-03-01 14:00", "booking_change"),
    ("/crm", "crm"),
    ("/crm ok 1", "crm"),
    ("/booking-admin", "booking_admin"),
    ("設定時段", "booking_admin"),
    ("/myid", "get_my_id"),
    ("填寫諮詢資料", "intake_help"),

    # --- 諮詢資料後備格式 ---
    ("①王小明②1990-01-01③想問感情", "intake_form"),

    # --- 報到登記 ---
    ("我會到", "checkin_yes"),
    ("會到", "checkin_yes"),
    ("報到", "checkin_yes"),
    ("+1", "checkin_yes"),
    ("我到了", "checkin_yes"),
    ("會晚到", "checkin_late"),
    ("晚一點", "checkin_late"),
    ("pass", "checkin_no"),
    ("不到", "checkin_no"),
    ("請假", "checkin_no"),

    # --- 匯款回報 ---
    ("已匯款", "payment_reported"),
    ("已轉帳", "payment_reported"),
    ("轉好了", "payment_reported"),

    # --- 預約流程 ---
    ("預約 2026-03-01 14:00", "booking_confirm"),
    ("預約 2026-03-01", "booking_date"),
    ("時段", "schedule"),
    ("什麼時候可以", "schedule"),
    ("我要預約", "booking"),
    ("想預約", "booking"),

    # --- 進度查詢 ---
    ("進度查詢", "order_status"),
    ("查詢進度", "order_status"),
    ("我的預約", "order_status"),
    ("預約查詢", "order_status"),
    ("訂單", "order_status"),

    # --- 諮詢說明 / 服務分類（順序敏感，見 NEGATIVE_CASES）---
    ("什麼是諮詢", "what_is_consultation"),
    ("為什麼要先諮詢", "what_is_consultation"),
    ("人生困惑", "category_consultation"),
    ("人生困惑諮詢", "category_consultation"),
    ("算命問事", "category_fortune"),
    ("招財項目", "category_wealth"),
    ("感情項目", "category_love"),
    ("風水調整", "category_fengshui"),
    ("客製化法事", "category_custom"),
    ("疑難雜症", "category_custom"),

    # --- 主要動作 ---
    ("服務項目", "services"),
    ("有什麼服務", "services"),
    ("找小夏老師", "human"),
    ("找老師", "human"),

    # --- 價格防禦 ---
    ("多少錢", "pricing"),
    ("費用", "pricing"),
]

# 容易互相搶先匹配的情況：確認實際比對到的是「更精確」的意圖，
# 而不是被範圍較寬的 pattern（如「項目」「預約」）誤先攔截。
PRIORITY_CASES = [
    ("招財項目", "category_wealth"),   # 不應被 services 的「項目」搶先
    ("感情項目", "category_love"),      # 同上
    ("人生困惑諮詢", "category_consultation"),  # 不應被 what_is_consultation 誤判
    ("我的預約", "order_status"),       # 不應被 booking 的「預約」搶先
    ("預約查詢", "order_status"),       # 同上
    ("我要預約", "booking"),            # 反向確認：純預約意圖不被 order_status 攔截
]

NEGATIVE_CASES = [
    "哈囉",
    "謝謝",
    "",
    "今天天氣真好",
    "/open\n7/12 15",
    "/close 7/12 15",
    "/slots",
]


@pytest.mark.parametrize("text,expected_intent", POSITIVE_CASES)
def test_match_keyword_positive(text, expected_intent):
    assert match_keyword(text) == expected_intent


@pytest.mark.parametrize("text,expected_intent", PRIORITY_CASES)
def test_match_keyword_priority(text, expected_intent):
    assert match_keyword(text) == expected_intent


@pytest.mark.parametrize("text", NEGATIVE_CASES)
def test_match_keyword_negative(text):
    assert match_keyword(text) is None
