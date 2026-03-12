"""
關鍵字路由器 — 第一層防線，不花任何 AI Token。
比對用戶訊息中的關鍵字，回傳對應的意圖代碼。
"""

import re
from typing import Optional

# (正則表達式, 意圖代碼)
KEYWORD_PATTERNS = [
    # --- 管理員指令（放最前面，優先比對）---
    (r"^/off$", "bot_off"),
    (r"^/on$", "bot_on"),
    (r"^/ok(\s+\d+)?$", "booking_ok"),
    (r"^/no(\s+\d+)?$", "booking_no"),
    (r"^/paid(\s+\d+)?$", "booking_paid"),
    (r"^/myid$", "get_my_id"),

    # --- 報到登記（0 Token）---
    (r"^我會到$|^會到$|^報到$|^\+1$|^到$|^我到了$|^我要來$", "checkin_yes"),
    (r"會晚到|晚到|晚一點", "checkin_late"),
    (r"^pass$|^不到$|^不去$|^請假$|不會到", "checkin_no"),

    # --- 匯款回報（放在預約流程前面）---
    (r"已匯款|已轉帳|匯好了|轉好了|已付款", "payment_reported"),

    # --- 預約流程（放在 booking 前面，優先比對日期格式）---
    (r"^預約\s+\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}$", "booking_confirm"),
    (r"^預約\s+\d{4}-\d{2}-\d{2}$", "booking_date"),

    # --- 服務分類（放在「服務項目」之前，避免「招財項目」「感情項目」被「項目」搶先匹配）---
    (r"什麼是諮詢|為什麼要諮詢|諮詢是什麼|為何諮詢|為什麼要先諮詢", "what_is_consultation"),
    (r"人生困惑|困惑諮詢", "category_consultation"),
    (r"算命問事|算命|問事", "category_fortune"),
    (r"招財項目|招財", "category_wealth"),
    (r"感情項目|感情", "category_love"),
    (r"風水調整|風水", "category_fengshui"),
    (r"客製化|疑難雜症|法事", "category_custom"),

    # --- 主要動作 ---
    (r"我要預約|預約|想預約|預約諮詢|我想預約", "booking"),
    (r"服務項目|有什麼服務|服務|項目|你們做什麼|能做什麼", "services"),
    (r"找小夏老師|找老師|真人|客服|找人|小夏", "human"),

    # --- 價格防禦 ---
    (r"多少錢|價格|費用|報價|怎麼收費|收費標準", "pricing"),
]


def match_keyword(text: str) -> Optional[str]:
    """
    比對用戶訊息，回傳意圖代碼。
    回傳 None 代表沒有匹配，應交給 AI 處理。
    """
    text = text.strip()
    for pattern, intent in KEYWORD_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            return intent
    return None
