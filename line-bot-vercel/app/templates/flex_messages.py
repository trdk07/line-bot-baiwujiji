"""
LINE Flex Message 模板 — 所有互動卡片的定義。
這些全部是固定內容，不花 AI Token。
"""

from datetime import datetime

# === 色彩定義 ===
BG_DARK = "#1B1B1B"
GOLD = "#C9A962"
TEXT_WHITE = "#FFFFFF"
TEXT_GREY = "#AAAAAA"
DIVIDER = "#333333"

WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def _make_button(label: str, text: str) -> dict:
    """建立一個按鈕元件，點擊後發送文字訊息。"""
    return {
        "type": "button",
        "action": {"type": "message", "label": label, "text": text},
        "style": "primary",
        "color": GOLD,
        "height": "sm",
        "margin": "sm",
    }


def _make_text(text: str, size: str = "sm", color: str = TEXT_WHITE, weight: str = "regular", align: str = "start") -> dict:
    return {
        "type": "text",
        "text": text,
        "size": size,
        "color": color,
        "weight": weight,
        "align": align,
        "wrap": True,
    }


# ============================================================
# 主選單：服務項目一覽
# ============================================================
def service_menu() -> dict:
    return {
        "type": "flex",
        "altText": "百無禁忌工作室 — 服務項目",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {
                "body": {"backgroundColor": BG_DARK},
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "lg",
                "paddingAll": "20px",
                "contents": [
                    _make_text("百無禁忌工作室", size="xl", color=GOLD, weight="bold", align="center"),
                    _make_text("— 服務項目 —", size="sm", color=TEXT_GREY, align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},
                    _make_button("✦ 人生困惑諮詢", "人生困惑諮詢"),
                    _make_button("✦ 算命問事", "算命問事"),
                    _make_button("✦ 招財項目", "招財項目"),
                    _make_button("✦ 感情項目", "感情項目"),
                    _make_button("✦ 風水調整", "風水調整"),
                    _make_button("✦ 客製化疑難雜症法事", "客製化法事"),
                ],
            },
        },
    }


# ============================================================
# 人生困惑諮詢
# ============================================================
def consultation_card() -> dict:
    return {
        "type": "flex",
        "altText": "人生困惑諮詢 $3,600",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("人生困惑諮詢", size="xl", color=GOLD, weight="bold"),
                    _make_text("$3,600", size="lg", color=TEXT_WHITE, weight="bold"),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text(
                        "就像看醫生會先問診了解狀況一樣，老師會先了解你目前的情況和心境，再給你最適合的方向與建議。",
                        color=TEXT_GREY,
                    ),
                    _make_text(
                        "老師的理念：命盤只是工具，真正重要的是你的心理狀態。先轉念，後續不管是調整方向還是法術協助，效果才會真的出來。",
                        color=TEXT_GREY,
                    ),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_button("預約諮詢", "我要預約"),
                ],
            },
        },
    }


# ============================================================
# 算命問事
# ============================================================
def fortune_card() -> dict:
    return {
        "type": "flex",
        "altText": "算命問事 — 服務項目",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("算命問事", size="xl", color=GOLD, weight="bold"),
                    _make_text("每項 $3,600", size="md", color=TEXT_WHITE),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("✦ 財運流年推測", color=TEXT_WHITE),
                    _make_text("✦ 事業運勢排程", color=TEXT_WHITE),
                    _make_text("✦ 感情困頓解惑", color=TEXT_WHITE),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_button("預約算命問事", "我要預約"),
                ],
            },
        },
    }


# ============================================================
# 招財項目
# ============================================================
def wealth_card() -> dict:
    return {
        "type": "flex",
        "altText": "招財項目",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("招財項目", size="xl", color=GOLD, weight="bold"),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("✦ 五方貴人招財（個人／公司）", color=TEXT_WHITE),
                    _make_text("✦ 日夜招財（限店面）", color=TEXT_WHITE),
                    _make_text("✦ 五方五土招財（個人／公司）", color=TEXT_WHITE),
                    _make_text("✦ 開店開光／旺店", color=TEXT_WHITE),
                    _make_text("✦ 還壽生金", color=TEXT_WHITE),
                    _make_text("✦ 補財庫", color=TEXT_WHITE),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("每個人的狀況不同，建議先預約諮詢讓老師了解你的需求。", color=TEXT_GREY),
                    _make_button("預約諮詢了解更多", "我要預約"),
                ],
            },
        },
    }


# ============================================================
# 感情項目
# ============================================================
def love_card() -> dict:
    return {
        "type": "flex",
        "altText": "感情項目",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("感情項目", size="xl", color=GOLD, weight="bold"),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("✦ 單戀催合", color=TEXT_WHITE),
                    _make_text("✦ 分手挽回", color=TEXT_WHITE),
                    _make_text("✦ 招桃花", color=TEXT_WHITE),
                    _make_text("✦ 貴人緣／人際關係", color=TEXT_WHITE),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("感情的事因人而異，建議先預約諮詢讓老師了解完整狀況。", color=TEXT_GREY),
                    _make_button("預約諮詢了解更多", "我要預約"),
                ],
            },
        },
    }


# ============================================================
# 風水調整
# ============================================================
def fengshui_card() -> dict:
    return {
        "type": "flex",
        "altText": "風水調整",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("風水調整", size="xl", color=GOLD, weight="bold"),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("✦ 奇門遁甲", color=TEXT_WHITE),
                    _make_text("✦ 九宮飛星", color=TEXT_WHITE),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("風水調整需要依據實際狀況判斷，建議先預約諮詢讓老師了解。", color=TEXT_GREY),
                    _make_button("預約諮詢了解更多", "我要預約"),
                ],
            },
        },
    }


# ============================================================
# 客製化法事
# ============================================================
def custom_card() -> dict:
    return {
        "type": "flex",
        "altText": "專屬客製化疑難雜症法事",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("專屬客製化", size="xl", color=GOLD, weight="bold"),
                    _make_text("疑難雜症法事", size="xl", color=GOLD, weight="bold"),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text(
                        "每個人的狀況都是獨一無二的。如果你的問題比較特殊，老師會針對你的情況量身安排最適合的法事。",
                        color=TEXT_GREY,
                    ),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_button("預約諮詢", "我要預約"),
                ],
            },
        },
    }


# ============================================================
# 預約原則說明（首次預約時顯示，只出現一次）
# ============================================================
def principles_card() -> dict:
    return {
        "type": "flex",
        "altText": "預約諮詢前，請先了解百無禁忌的原則",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("預約諮詢前", size="xl", color=GOLD, weight="bold", align="center"),
                    _make_text("請先了解百無禁忌的原則", size="md", color=GOLD, weight="bold", align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},

                    _make_text("① 玄學可以很科學", size="md", color=GOLD, weight="bold"),
                    _make_text(
                        "是能落地的日常策略。預約諮詢不代表一定要「做法術」，就像看診一樣，先幫你找出目前卡關的核心盲點。有時候，你需要的只是一套能落實在日常的能量策略。",
                        color=TEXT_GREY,
                    ),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},

                    _make_text("② 專業需要付費", size="md", color=GOLD, weight="bold"),
                    _make_text(
                        "可以理解成能量交換。你可以跟我聊聊發生了什麼事，但只要開始運用專業知識為你梳理脈絡、對症下藥，就需要收取諮詢費。",
                        color=TEXT_GREY,
                    ),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},

                    _make_text("③ 疑人不用，不勉強、不耗損", size="md", color=GOLD, weight="bold"),
                    _make_text(
                        "隔著網路沒見過面，有疑慮很合理。如果覺得不需要協助，或是對諮詢金額感到有壓力，可以直接說「先不用」。千萬別覺得不好意思。當你準備好了、願意交付信任時，我們再開始。",
                        color=TEXT_GREY,
                    ),
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},

                    _make_text("確認以上原則，準備好了嗎？", size="sm", color=TEXT_WHITE, align="center"),
                    _make_button("✦ 我要預約", "我要預約"),
                ],
            },
        },
    }


# ============================================================
# 預約引導卡片（Google Calendar 未設定時的備用）
# ============================================================
def booking_card() -> dict:
    return {
        "type": "flex",
        "altText": "預約諮詢",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("預約諮詢", size="xl", color=GOLD, weight="bold", align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("請提供以下資訊，老師會盡快跟你確認時間：", color=TEXT_WHITE),
                    _make_text("① 您的大名", color=GOLD),
                    _make_text("② 出生年月日（國曆）", color=GOLD),
                    _make_text("③ 想了解的問題", color=GOLD),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("直接在對話框中輸入即可，例如：", color=TEXT_GREY),
                    _make_text("王小明\n1990/05/15\n最近工作不順，想了解事業方向", color=TEXT_GREY),
                ],
            },
        },
    }


# ============================================================
# 日期選擇卡片（預約 Step 1）
# ============================================================
def date_picker_card(dates: list) -> dict:
    """顯示可預約日期讓客人選擇。"""
    buttons = []
    for date_str in dates:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = WEEKDAY_NAMES[d.weekday()]
        label = f"{d.month}/{d.day}（{weekday}）"
        buttons.append({
            "type": "button",
            "action": {
                "type": "message",
                "label": label,
                "text": f"預約 {date_str}",
            },
            "style": "primary",
            "color": GOLD,
            "height": "sm",
            "margin": "sm",
        })

    return {
        "type": "flex",
        "altText": "選擇預約日期",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("選擇預約日期", size="xl", color=GOLD, weight="bold", align="center"),
                    _make_text("請選擇方便的日期", size="sm", color=TEXT_GREY, align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},
                    *buttons,
                ],
            },
        },
    }


# ============================================================
# 時段選擇卡片（預約 Step 2）
# ============================================================
def time_picker_card(date_str: str, slots: list) -> dict:
    """顯示指定日期的可用時段讓客人選擇。"""
    d = datetime.strptime(date_str, "%Y-%m-%d")
    weekday = WEEKDAY_NAMES[d.weekday()]
    date_label = f"{d.month}/{d.day}（{weekday}）"

    buttons = []
    for slot in slots:
        buttons.append({
            "type": "button",
            "action": {
                "type": "message",
                "label": slot,
                "text": f"預約 {date_str} {slot}",
            },
            "style": "primary",
            "color": GOLD,
            "height": "sm",
            "margin": "sm",
        })

    return {
        "type": "flex",
        "altText": f"選擇 {date_label} 的時段",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("選擇時段", size="xl", color=GOLD, weight="bold", align="center"),
                    _make_text(date_label, size="lg", color=TEXT_WHITE, weight="bold", align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},
                    *buttons,
                ],
            },
        },
    }
