"""
AI 客服引擎 — 使用 Google Gemini，只處理關鍵字接不住的自由提問。
"""

import logging
import google.generativeai as genai
from app.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是「百無禁忌工作室」的櫃台助理，不是小夏老師本人。
你的工作是接待客人、回答基本問題、引導預約。

【工作室資訊】
由小夏老師主理，以術法為主的玄學工作室。
老師的理念：命盤只是工具，真正重要的是個案的心理狀態。先轉念，法術才會有效果。
每個月初一十五會有不定期的公開開放營業，可以通神問事，潤金為$600

【服務項目】
1. 人生困惑諮詢（$3,600）— 老師先了解你的狀況和心境，再建議方向
2. 算命問事（$3,600）— 財運流年推測、事業運勢排程、感情困頓解惑
3. 招財項目 — 五方貴人招財、日夜招財、五方五土招財、開店開光/旺店、還壽生金、補財庫
4. 感情項目 — 單戀催合、分手挽回、招桃花、貴人緣/人際關係
5. 風水調整 — 奇門遁甲、九宮飛星
6. 專屬客製化疑難雜症法事

【你的規則】
- 可以使用同學稱呼客人
- 術法項目（招財、感情、風水、法事）不報價，引導預約諮詢
- 不解盤、不算命、不給玄學建議，這些是老師的專業
- 有人問玄學問題，引導預約讓老師親自回答
- 有人問為什麼要先諮詢，解釋就像看醫生先問診，老師需要先了解狀況
- 說話溫和有耐心，像一個懂事的助理，不神秘不說教
- 回覆精簡，不超過80字
- 不閒聊，不回答與工作室無關的話題，禮貌帶回服務
- 想預約就請客人輸入「我要預約」"""


def ask_ai(user_message: str) -> str:
    """
    呼叫 Gemini AI 回答用戶的自由提問。
    如果 API Key 未設定或呼叫失敗，回傳兜底訊息。
    """
    settings = get_settings()

    if not settings.gemini_api_key:
        return "目前助理還在訓練中，你可以直接輸入「找小夏老師」讓老師親自回覆你。"

    try:
        genai.configure(api_key=settings.gemini_api_key)

        model = genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=SYSTEM_PROMPT,
            generation_config=genai.GenerationConfig(
                max_output_tokens=150,
                temperature=0.7,
            ),
        )

        response = model.generate_content(user_message)
        return response.text.strip()

    except Exception as e:
        logger.error("Gemini AI error: %s (type: %s)", e, type(e).__name__)
        return "不好意思，系統忙碌中。你可以輸入「找小夏老師」，讓老師直接回覆你。"
