"""
LINE Flex Message 模板 — 所有互動卡片的定義。
這些全部是固定內容，不花 AI Token。
"""

from datetime import datetime

# === 色彩定義 ===
BG_DARK = "#EFEBE5"      # 卡片 body 背景
GOLD = "#C2A68C"         # icon 點綴 / 標籤（淺色底用）
TEXT_TITLE = "#7B3F2A"   # 卡片標題（赤褐）
TEXT_WHITE = "#4A453C"   # 主內文
TEXT_GREY = "#6E675E"    # 淡色說明
DIVIDER = "#C8B8A8"      # 分隔線
ACCENT_RED = "#8B2020"   # 主按鈕 / 預約完成強調
BG_HEADER = "#3D1F1F"    # 深棕 header

WEEKDAY_NAMES = ["一", "二", "三", "四", "五", "六", "日"]


def _make_button(label: str, text: str) -> dict:
    """建立一個按鈕元件，點擊後發送文字訊息。"""
    return {
        "type": "button",
        "action": {"type": "message", "label": label, "text": text},
        "style": "primary",
        "color": ACCENT_RED,
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


def _sep(margin: str = "md") -> dict:
    """建立分隔線元件。"""
    return {"type": "separator", "color": DIVIDER, "margin": margin}


def _ornament_divider(margin: str = "lg") -> dict:
    """建立左右對稱的置中裝飾分隔線，避免裝飾符號視覺上偏左或偏右。"""
    return {
        "type": "box",
        "layout": "horizontal",
        "spacing": "sm",
        "margin": margin,
        "alignItems": "center",
        "contents": [
            {"type": "separator", "color": DIVIDER, "flex": 1},
            {"type": "text", "text": "✦", "size": "xs", "color": GOLD, "align": "center", "flex": 0, "wrap": False},
            {"type": "separator", "color": DIVIDER, "flex": 1},
        ],
    }


def _field(label: str, value: str) -> dict:
    return {
        "type": "box",
        "layout": "vertical",
        "spacing": "xs",
        "contents": [
            _make_text(label, size="xs", color=GOLD),
            _make_text(value or "（未填）", size="sm", color=TEXT_WHITE),
        ],
    }


def _service_card(alt_text: str, contents: list, button_label: str = "預約諮詢", button_text: str = "我要預約") -> dict:
    """
    服務分類卡片的共用外殼：bubble + 暖土色背景 + 內容清單 + 底部按鈕。
    六張服務卡（人生困惑諮詢／算命問事／招財／感情／風水／客製化）結構相同，
    只有標題、說明段落、按鈕文字不同，因此把外層樣板收斂到這裡。
    """
    return {
        "type": "flex",
        "altText": alt_text,
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {"body": {"backgroundColor": BG_DARK}},
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [*contents, _make_button(button_label, button_text)],
            },
        },
    }


# ============================================================
# 主選單：服務項目一覽
# ============================================================
def service_menu() -> dict:
    return {
        "type": "flex",
        "altText": "百無禁忌研究所 — 服務項目",
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
                    _make_text("百無禁忌研究所", size="xl", color=TEXT_TITLE, weight="bold", align="center"),
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
# 服務分類卡片（人生困惑諮詢／算命問事／招財／感情／風水／客製化）
# ============================================================
def consultation_card() -> dict:
    return _service_card(
        "人生困惑諮詢 $3,600",
        [
            _make_text("人生困惑諮詢", size="xl", color=TEXT_TITLE, weight="bold"),
            _make_text("$3,600", size="lg", color=TEXT_WHITE, weight="bold"),
            _sep(),
            _make_text(
                "就像看醫生會先問診了解狀況一樣，老師會先了解你目前的情況和心境，再給你最適合的方向與建議。",
                color=TEXT_GREY,
            ),
            _make_text(
                "老師的理念：命盤只是工具，真正重要的是你的心理狀態。先轉念，後續不管是調整方向還是法術協助，效果才會真的出來。",
                color=TEXT_GREY,
            ),
            _sep(),
        ],
    )


def fortune_card() -> dict:
    return _service_card(
        "算命問事 — 服務項目",
        [
            _make_text("算命問事", size="xl", color=TEXT_TITLE, weight="bold"),
            _make_text("每項 $3,600", size="md", color=TEXT_WHITE),
            _sep(),
            _make_text("✦ 財運流年推測", color=TEXT_WHITE),
            _make_text("✦ 事業運勢排程", color=TEXT_WHITE),
            _make_text("✦ 感情困頓解惑", color=TEXT_WHITE),
            _sep(),
        ],
        button_label="預約算命問事",
    )


def wealth_card() -> dict:
    return _service_card(
        "招財項目",
        [
            _make_text("招財項目", size="xl", color=TEXT_TITLE, weight="bold"),
            _make_text("依個人狀況報價", size="md", color=TEXT_WHITE, weight="bold"),
            _sep(),
            _make_text(
                "財運不順、生意不好、總覺得漏財？老師會針對你的狀況，找出財運卡關的原因，安排最適合的招財方式。",
                color=TEXT_GREY,
            ),
            _sep(),
            _make_text("✦ 五方貴人招財（個人／公司）", color=TEXT_WHITE),
            _make_text("✦ 日夜招財（限店面）", color=TEXT_WHITE),
            _make_text("✦ 五方五土招財（個人／公司）", color=TEXT_WHITE),
            _make_text("✦ 開店開光／旺店", color=TEXT_WHITE),
            _make_text("✦ 還壽生金", color=TEXT_WHITE),
            _make_text("✦ 補財庫", color=TEXT_WHITE),
            _sep(),
            _make_text("每個人的狀況不同，建議先預約諮詢讓老師了解你的需求。", color=TEXT_GREY),
        ],
        button_label="預約諮詢了解更多",
    )


def love_card() -> dict:
    return _service_card(
        "感情項目",
        [
            _make_text("感情項目", size="xl", color=TEXT_TITLE, weight="bold"),
            _make_text("依個人狀況報價", size="md", color=TEXT_WHITE, weight="bold"),
            _sep(),
            _make_text(
                "感情的問題往往不只是表面看到的那樣。老師會先了解你們之間的狀況，再針對問題的根源給出最適合的建議和處理方式。",
                color=TEXT_GREY,
            ),
            _sep(),
            _make_text("✦ 單戀催合", color=TEXT_WHITE),
            _make_text("✦ 分手挽回", color=TEXT_WHITE),
            _make_text("✦ 招桃花", color=TEXT_WHITE),
            _make_text("✦ 貴人緣／人際關係", color=TEXT_WHITE),
            _sep(),
            _make_text("感情的事因人而異，建議先預約諮詢讓老師了解完整狀況。", color=TEXT_GREY),
        ],
        button_label="預約諮詢了解更多",
    )


def fengshui_card() -> dict:
    return _service_card(
        "風水調整",
        [
            _make_text("風水調整", size="xl", color=TEXT_TITLE, weight="bold"),
            _sep(),
            _make_text("✦ 奇門遁甲", color=TEXT_WHITE),
            _make_text("✦ 九宮飛星", color=TEXT_WHITE),
            _sep(),
            _make_text("風水調整需要依據實際狀況判斷，建議先預約諮詢讓老師了解。", color=TEXT_GREY),
        ],
        button_label="預約諮詢了解更多",
    )


def custom_card() -> dict:
    return _service_card(
        "專屬客製化疑難雜症法事",
        [
            _make_text("專屬客製化", size="xl", color=TEXT_TITLE, weight="bold"),
            _make_text("疑難雜症法事", size="xl", color=TEXT_TITLE, weight="bold"),
            _sep(),
            _make_text(
                "每個人的狀況都是獨一無二的。如果你的問題比較特殊，老師會針對你的情況量身安排最適合的法事。",
                color=TEXT_GREY,
            ),
            _sep(),
        ],
    )


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
                    _make_text("預約諮詢前", size="xl", color=TEXT_TITLE, weight="bold", align="center"),
                    _make_text("請先了解百無禁忌的原則", size="md", color=TEXT_TITLE, weight="bold", align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},

                    _make_text("① 玄學可以很科學", size="md", color=TEXT_TITLE, weight="bold"),
                    _make_text(
                        "是能落地的日常策略。預約諮詢不代表一定要「做法術」，就像看診一樣，先幫你找出目前卡關的核心盲點。有時候，你需要的只是一套能落實在日常的能量策略。",
                        color=TEXT_GREY,
                    ),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},

                    _make_text("② 專業需要付費", size="md", color=TEXT_TITLE, weight="bold"),
                    _make_text(
                        "可以理解成能量交換。你可以跟我聊聊發生了什麼事，但只要開始運用專業知識為你梳理脈絡、對症下藥，就需要收取諮詢費。",
                        color=TEXT_GREY,
                    ),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},

                    _make_text("③ 疑人不用，不勉強、不耗損", size="md", color=TEXT_TITLE, weight="bold"),
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


def _info_row(icon: str, text: str) -> dict:
    return {
        "type": "box",
        "layout": "horizontal",
        "spacing": "md",
        "contents": [
            _make_text(icon, size="sm", color=GOLD),
            _make_text(text, size="sm", color=TEXT_WHITE),
        ],
    }


# ============================================================
# 預約確認卡片（管理員 /paid 後發給客人）
# ============================================================
def booking_confirmed_card(
    customer_name: str,
    date_label: str,
    time_str: str,
    birth_date: str = "",
    question: str = "",
) -> dict:
    fields = [_field("大名", customer_name)]
    if birth_date:
        fields.append(_field("生辰", birth_date))
    if question:
        fields.append(_field("所問之事", question))

    return {
        "type": "flex",
        "altText": f"預約成立 ✦ {date_label} {time_str}",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {
                "header": {"backgroundColor": BG_HEADER},
                "body": {"backgroundColor": BG_DARK},
            },
            "header": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "16px",
                "contents": [
                    _make_text("✦  預 約 成 立  ✦", size="lg", color=GOLD, weight="bold", align="center"),
                    _make_text("百無禁忌研究所", size="xxs", color=DIVIDER, align="center"),
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "lg",
                "paddingAll": "24px",
                "contents": [
                    _make_text(date_label, size="xxl", color=TEXT_TITLE, weight="bold", align="center"),
                    _make_text(time_str, size="lg", color=TEXT_WHITE, align="center"),
                    _make_text("共 60 分鐘", size="xs", color=TEXT_GREY, align="center"),
                    _ornament_divider(),
                    {"type": "box", "layout": "vertical", "spacing": "md", "contents": fields},
                    _ornament_divider(),
                    _make_text("屆時見。", size="sm", color=TEXT_TITLE, align="center"),
                    _make_text("如需改期，直接在此告知即可", size="xxs", color=TEXT_GREY, align="center"),
                ],
            },
        },
    }


# ============================================================
# 改期通知卡片（管理員 /change 後發給客人）
# ============================================================
def booking_rescheduled_card(customer_name: str, date_label: str, time_str: str) -> dict:
    return {
        "type": "flex",
        "altText": "您的預約已改期",
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
                    _make_text("預約已改期", size="xl", color=TEXT_TITLE, weight="bold", align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},
                    {
                        "type": "box",
                        "layout": "vertical",
                        "spacing": "sm",
                        "margin": "md",
                        "contents": [
                            _info_row("👤", customer_name),
                            _info_row("📅", date_label),
                            _info_row("🕐", time_str),
                            _info_row("⏱", "60 分鐘"),
                        ],
                    },
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},
                    _make_text("如有疑問請聯絡我們 🙏", size="sm", color=TEXT_GREY, align="center"),
                ],
            },
        },
    }


def intake_card(display_name: str, name: str, birth_date: str, question: str) -> dict:
    """客戶諮詢資料卡片 — 解析用戶填寫的①②③欄位後發給管理員。"""
    return {
        "type": "flex",
        "altText": f"{display_name} 的諮詢資料",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {
                "header": {"backgroundColor": BG_HEADER},
                "body": {"backgroundColor": BG_DARK},
            },
            "header": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "16px",
                "contents": [
                    _make_text("📋 客戶諮詢資料", size="lg", color=GOLD, weight="bold"),
                    _make_text(display_name, size="sm", color=TEXT_GREY),
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _field("① 大名", name),
                    {"type": "separator", "color": DIVIDER},
                    _field("② 出生年月日", birth_date),
                    {"type": "separator", "color": DIVIDER},
                    _field("③ 想了解的問題", question),
                ],
            },
        },
    }


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
                    _make_text("預約諮詢", size="xl", color=TEXT_TITLE, weight="bold", align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("請提供以下資訊，老師會盡快跟你確認時間：", color=TEXT_WHITE),
                    _make_text("① 您的大名", color=GOLD),
                    _make_text("② 出生年月日（國曆）", color=GOLD),
                    _make_text("③ 想了解的問題", color=GOLD),
                    {"type": "separator", "color": DIVIDER, "margin": "md"},
                    _make_text("直接在對話框中輸入即可，例如：", color=TEXT_GREY),
                    _make_text("我是誰\n1990/05/15\n最近工作不順，想了解事業方向", color=TEXT_GREY),
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
                    _make_text("選擇預約日期", size="xl", color=TEXT_TITLE, weight="bold", align="center"),
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
                    _make_text("選擇時段", size="xl", color=TEXT_TITLE, weight="bold", align="center"),
                    _make_text(date_label, size="lg", color=TEXT_WHITE, weight="bold", align="center"),
                    _make_text("每個時段 60 分鐘", size="sm", color=TEXT_GREY, align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},
                    *buttons,
                ],
            },
        },
    }


def booking_entry_card(url: str) -> dict:
    return {
        "type": "flex",
        "altText": "選擇預約時段",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {
                "header": {"backgroundColor": BG_HEADER},
                "body": {"backgroundColor": BG_DARK},
            },
            "header": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "16px",
                "contents": [
                    _make_text("✦ 選擇方便的時間", size="lg", color=GOLD, weight="bold", align="center"),
                    _make_text("百無禁忌研究所", size="xs", color=DIVIDER, align="center"),
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    _make_text("請開啟月曆查看可預約時段。", color=TEXT_WHITE, align="center"),
                    _make_text("選好後會回到聊天室送出預約訊息。", size="xs", color=TEXT_GREY, align="center"),
                    _ornament_divider(),
                    {
                        "type": "button",
                        "action": {"type": "uri", "label": "開啟預約月曆", "uri": url},
                        "style": "primary",
                        "color": ACCENT_RED,
                        "height": "sm",
                    },
                ],
            },
        },
    }


def admin_booking_link_card(url: str, title: str) -> dict:
    card = booking_entry_card(url)
    card["altText"] = title
    card["contents"]["header"]["contents"][0]["text"] = f"✦ {title}"
    card["contents"]["body"]["contents"][0]["text"] = "請開啟月曆設定本月可預約時段。"
    card["contents"]["body"]["contents"][1]["text"] = "此連結含管理 token，請勿轉傳。"
    card["contents"]["body"]["contents"][-1]["action"]["label"] = "設定時段"
    return card


def crm_preview_card(payload: dict, customer_label: str) -> dict:
    fields = [
        _field("客戶狀態", customer_label),
        _field("大名", payload.get("n", "")),
        _field("生辰", payload.get("b", "")),
        _field("所問之事", payload.get("q", "")),
        _field("預約時間", f"{payload.get('d', '')} {payload.get('t', '')}"),
    ]
    return {
        "type": "flex",
        "altText": f"CRM 預覽 ✦ {payload.get('n', '')}",
        "contents": {
            "type": "bubble",
            "size": "mega",
            "styles": {
                "header": {"backgroundColor": BG_HEADER},
                "body": {"backgroundColor": BG_DARK},
            },
            "header": {
                "type": "box",
                "layout": "vertical",
                "paddingAll": "16px",
                "contents": [
                    _make_text("✦ CRM 資料預覽", size="lg", color=GOLD, weight="bold"),
                    _make_text("確認後再寫入 Notion", size="xs", color=DIVIDER),
                ],
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "paddingAll": "20px",
                "contents": [
                    *fields,
                    _ornament_divider(),
                    _make_button("寫入 CRM", "/crm ok"),
                    _make_button("略過", "/crm skip"),
                ],
            },
        },
    }


# ============================================================
# 匯款資訊卡片（管理員確認日期後發送給客人）
# ============================================================
def payment_info_card(date_label: str, time_str: str, qr_image_url: str) -> dict:
    """顯示匯款 QR Code，讓客人掃碼完成匯款。"""
    qr_section = []
    if qr_image_url:
        qr_section = [
            {
                "type": "image",
                "url": qr_image_url,
                "size": "xl",
                "aspectMode": "fit",
                "aspectRatio": "1:1",
                "margin": "md",
                "align": "center",
            },
            _make_text("請掃描上方 QR Code 完成匯款", color=TEXT_GREY, align="center"),
        ]
    else:
        qr_section = [
            _make_text("⚠️ 匯款 QR Code 暫時無法顯示，請聯繫老師取得匯款資訊。", color=GOLD, align="center"),
        ]

    return {
        "type": "flex",
        "altText": "匯款資訊 — 預約日期已確認",
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
                    _make_text("日期已確認 ✓", size="xl", color=TEXT_TITLE, weight="bold", align="center"),
                    _make_text(f"📅 {date_label}  {time_str}", size="md", color=TEXT_WHITE, align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},
                    _make_text("✦ 匯款資訊", size="lg", color=TEXT_TITLE, weight="bold", align="center"),
                    *qr_section,
                    _make_text("金額：NT$ 3,600", size="md", color=TEXT_TITLE, weight="bold", align="center"),
                    {"type": "separator", "color": DIVIDER, "margin": "lg"},
                    _make_text(
                        "⚠️ 匯款完成後，請務必按下方「已匯款」按鈕通知我們，預約才算成立。",
                        color=TEXT_WHITE,
                    ),
                    _make_button("✦ 已匯款", "已匯款"),
                    _make_text("百無禁忌研究所", size="xs", color=TEXT_GREY, align="center"),
                ],
            },
        },
    }
