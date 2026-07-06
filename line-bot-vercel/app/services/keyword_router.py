"""
關鍵字路由器 — 第一層防線，不花任何 AI Token。
比對用戶訊息中的關鍵字，回傳對應的意圖代碼。
"""

import re
from typing import Optional

# (正則表達式, 意圖代碼)
# 順序即優先權：越前面的 pattern 越先比對到就直接回傳，不會再往下比對。
# 同一組內的 alternative 已移除「被其他 alternative 包含的冗餘字串」
# （例如「算命問事」本身已包含「算命」與「問事」，比對結果與只留「算命|問事」完全相同）。
KEYWORD_PATTERNS = [
    # --- 管理員指令（放最前面，優先比對）---
    (r"^/off$", "bot_off"),
    (r"^/on$", "bot_on"),
    (r"^/ok(\s+\d+)?$", "booking_ok"),
    (r"^/no(\s+\d+)?$", "booking_no"),
    (r"^/paid(\s+\d+)?$", "booking_paid"),
    (r"^/list$", "booking_list"),
    (r"^/clear(\s+yes)?$", "booking_clear"),
    (r"^/change\b", "booking_change"),
    (r"^/crm\b", "crm"),
    (r"^/booking-admin$|^設定時段$", "booking_admin"),
    (r"^/myid$", "get_my_id"),

    # --- 諮詢資料後備（①②③ 格式，intake_pending 消耗後仍可補填）---
    (r"①[\s\S]*②", "intake_form"),

    # --- 報到登記（0 Token）---
    (r"^我會到$|^會到$|^報到$|^\+1$|^到$|^我到了$|^我要來$", "checkin_yes"),
    (r"會晚到|晚到|晚一點", "checkin_late"),
    (r"^pass$|^不到$|^不去$|^請假$|不會到", "checkin_no"),

    # --- 匯款回報（放在預約流程前面）---
    (r"已匯款|已轉帳|匯好了|轉好了|已付款", "payment_reported"),

    # --- 預約流程（放在 booking 前面，優先比對日期格式）---
    (r"^預約\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$", "booking_confirm"),
    (r"^預約\s+\d{4}-\d{2}-\d{2}$", "booking_date"),
    (r"本週|下週|時段|什麼時候可以", "schedule"),

    # --- 服務分類（放在「服務項目」之前，避免「招財項目」「感情項目」被「項目」搶先匹配）---
    (r"什麼是諮詢|為什麼要諮詢|諮詢是什麼|為何諮詢|為什麼要先諮詢", "what_is_consultation"),
    (r"人生困惑|困惑諮詢", "category_consultation"),
    (r"算命|問事", "category_fortune"),
    (r"招財", "category_wealth"),
    (r"感情", "category_love"),
    (r"風水", "category_fengshui"),
    (r"客製化|疑難雜症|法事", "category_custom"),

    # --- 主要動作 ---
    (r"預約", "booking"),
    (r"服務|項目|你們做什麼|能做什麼", "services"),
    (r"找老師|找小夏", "human"),

    # --- 價格防禦 ---
    (r"多少錢|價格|費用|報價|怎麼收費|收費標準", "pricing"),
]

# 模組載入時預先編譯，避免每次請求重新編譯 regex。
_COMPILED_PATTERNS = [(re.compile(pattern, re.IGNORECASE), intent) for pattern, intent in KEYWORD_PATTERNS]


def match_keyword(text: str) -> Optional[str]:
    """
    比對用戶訊息，回傳意圖代碼。
    回傳 None 代表沒有匹配，應交給 AI 處理。
    """
    text = text.strip()
    for pattern, intent in _COMPILED_PATTERNS:
        if pattern.search(text):
            return intent
    return None
