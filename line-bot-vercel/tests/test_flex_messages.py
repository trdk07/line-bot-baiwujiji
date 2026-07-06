"""
flex_messages 的結構性測試。
六張服務分類卡片共用 _service_card builder，這裡鎖定每張卡片的
altText、標題文字、按鈕文字與 JSON 結構不因重構而改變。
"""

from app.templates import flex_messages as fm


def _button_texts(card: dict) -> list:
    """從卡片 body 中取出所有按鈕的 action.text。"""
    contents = card["contents"]["body"]["contents"]
    return [c["action"]["text"] for c in contents if c.get("type") == "button"]


def _text_values(card: dict) -> list:
    """從卡片 body 中取出所有文字元件的內容（不含巢狀 box）。"""
    contents = card["contents"]["body"]["contents"]
    return [c["text"] for c in contents if c.get("type") == "text"]


def test_service_menu_lists_all_categories():
    card = fm.service_menu()
    assert card["altText"] == "百無禁忌研究所 — 服務項目"
    texts = _button_texts(card)
    assert texts == [
        "人生困惑諮詢", "算命問事", "招財項目", "感情項目", "風水調整", "客製化法事",
    ]


def test_consultation_card():
    card = fm.consultation_card()
    assert card["altText"] == "人生困惑諮詢 $3,600"
    assert "人生困惑諮詢" in _text_values(card)
    assert "$3,600" in _text_values(card)
    assert _button_texts(card) == ["我要預約"]


def test_fortune_card_button_label():
    card = fm.fortune_card()
    assert card["altText"] == "算命問事 — 服務項目"
    action = card["contents"]["body"]["contents"][-1]["action"]
    assert action["label"] == "預約算命問事"
    assert action["text"] == "我要預約"


def test_wealth_card_has_all_bullets():
    card = fm.wealth_card()
    texts = _text_values(card)
    for bullet in ["五方貴人招財（個人／公司）", "日夜招財（限店面）", "五方五土招財（個人／公司）",
                   "開店開光／旺店", "還壽生金", "補財庫"]:
        assert any(bullet in t for t in texts), f"missing bullet: {bullet}"


def test_love_card_has_all_bullets():
    card = fm.love_card()
    texts = _text_values(card)
    for bullet in ["單戀催合", "分手挽回", "招桃花", "貴人緣／人際關係"]:
        assert any(bullet in t for t in texts), f"missing bullet: {bullet}"


def test_fengshui_card_has_no_price_line():
    card = fm.fengshui_card()
    contents = card["contents"]["body"]["contents"]
    # 第一個元件是標題，第二個緊接著是分隔線（沒有價格說明行）
    assert contents[0]["text"] == "風水調整"
    assert contents[1]["type"] == "separator"


def test_custom_card_has_two_line_title():
    card = fm.custom_card()
    texts = _text_values(card)
    assert texts[0] == "專屬客製化"
    assert texts[1] == "疑難雜症法事"


def test_all_service_cards_end_with_single_button():
    for name in ["consultation_card", "fortune_card", "wealth_card",
                 "love_card", "fengshui_card", "custom_card"]:
        card = getattr(fm, name)()
        last = card["contents"]["body"]["contents"][-1]
        assert last["type"] == "button", f"{name} should end with a button"


def test_booking_confirmed_card_invitation_style_and_optional_fields():
    card = fm.booking_confirmed_card("王小明", "7/12（日）", "15:00 – 16:00", question="工作方向")
    assert card["altText"] == "預約成立 ✦ 7/12（日） 15:00 – 16:00"
    assert card["contents"]["styles"]["header"]["backgroundColor"] == fm.BG_HEADER
    body_text = str(card["contents"])
    assert "✦  預 約 成 立  ✦" in body_text
    assert "所問之事" in body_text
    assert "生辰" not in body_text


def test_booking_entry_card_uses_uri_button():
    card = fm.booking_entry_card("https://example.com/booking.html")
    assert card["altText"] == "選擇預約時段"
    action = card["contents"]["body"]["contents"][-1]["action"]
    assert action["type"] == "uri"
    assert action["uri"] == "https://example.com/booking.html"


def test_admin_booking_link_card_mentions_private_token_link():
    card = fm.admin_booking_link_card("https://example.com/booking.html?token=t", "8 月時段尚未開放")
    assert card["altText"] == "8 月時段尚未開放"
    assert "請勿轉傳" in str(card["contents"])
    assert card["contents"]["body"]["contents"][-1]["action"]["label"] == "設定時段"


def test_crm_preview_card_buttons():
    card = fm.crm_preview_card({"n": "王小明", "b": "", "q": "問題", "d": "2026-07-12", "t": "15:00"}, "新客戶")
    assert "/crm ok" in _button_texts(card)
    assert "/crm skip" in _button_texts(card)
