"""
webhook.handle_text_message 的端對端整合測試。
模擬 LINE Messaging API（reply_message / push_message / get_profile）與
Upstash KV（httpx.post），驗證完整的管理員指令與預約流程行為不變——
特別是 2-3 重構（管理員指令表化）前後的行為一致性。
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import patch
import json

import pytest
import linebot.v3.messaging as messaging

import app.routers.webhook as wh
from app.services.calendar_service import TW_TZ

# 開放時段改用「今天起算」的動態日期（台灣時區），
# 避免寫死的日期過期後整批整合測試失效。
D1, D2, D3, D4 = [
    (datetime.now(TW_TZ).date() + timedelta(days=i)).isoformat() for i in range(1, 5)
]

OPEN_SLOTS = {
    D1: ["15:00", "16:00"],
    D2: ["15:00"],
    D3: ["15:00"],
    D4: ["15:00"],
}


def _seed_open_slots(env):
    by_month = {}
    for d, times in OPEN_SLOTS.items():
        by_month.setdefault(d[:7], {})[d] = times
    for month, data in by_month.items():
        env.kv.store[f"open:{month}"] = json.dumps(data, ensure_ascii=False)


class FakeKV:
    def __init__(self):
        self.store = {}

    def exec_cmd(self, cmd):
        op = cmd[0]
        if op == "SET":
            if "NX" in cmd and cmd[1] in self.store:
                return None
            self.store[cmd[1]] = cmd[2]
            return "OK"
        if op == "GET":
            return self.store.get(cmd[1])
        if op == "DEL":
            existed = cmd[1] in self.store
            self.store.pop(cmd[1], None)
            return 1 if existed else 0
        if op == "SADD":
            s = self.store.setdefault(cmd[1], set())
            before = len(s)
            s.add(cmd[2])
            return len(s) - before
        if op == "INCR":
            val = int(self.store.get(cmd[1], 0)) + 1
            self.store[cmd[1]] = str(val)
            return val
        if op == "SISMEMBER":
            s = self.store.get(cmd[1], set())
            return 1 if cmd[2] in s else 0
        if op == "RPUSH":
            lst = self.store.setdefault(cmd[1], [])
            lst.append(cmd[2])
            return len(lst)
        if op == "LRANGE":
            return list(self.store.get(cmd[1], []))
        if op == "LREM":
            lst = self.store.get(cmd[1], [])
            if cmd[3] in lst:
                lst.remove(cmd[3])
            return 1
        raise ValueError(op)

    def post(self, url, headers=None, json=None, timeout=None):
        if url.endswith("/pipeline"):
            return _Resp([{"result": self.exec_cmd(c)} for c in json])
        return _Resp({"result": self.exec_cmd(json)})


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def json(self):
        return self._payload


def _mk_event(text, user_id="cust1"):
    return SimpleNamespace(
        message=SimpleNamespace(text=text),
        source=SimpleNamespace(user_id=user_id),
        reply_token="tok",
        delivery_context=SimpleNamespace(is_redelivery=False),
        webhook_event_id="evt1",
    )


def _extract(req):
    texts = []
    for m in req.messages:
        texts.append(m.text if hasattr(m, "text") else ("FLEX", m.alt_text))
    return texts


@pytest.fixture
def line_env(monkeypatch):
    """設定 admin id + KV，並攔截 LINE Messaging API 呼叫。"""
    monkeypatch.setattr(wh.settings, "admin_line_user_id", "admin1")
    monkeypatch.setattr(wh.settings, "kv_rest_api_url", "http://fake-kv")
    monkeypatch.setattr(wh.settings, "payment_qr_image_url", "https://example.com/qr.png")

    kv = FakeKV()
    replies, pushes, raw_replies, raw_pushes = [], [], [], []

    def fake_reply(self, req):
        raw_replies.append(req)
        replies.append(_extract(req))

    def fake_push(self, req):
        raw_pushes.append(req)
        pushes.append((req.to, _extract(req)))

    def fake_profile(self, user_id):
        return SimpleNamespace(display_name=f"User-{user_id}")

    with patch.object(messaging.MessagingApi, "reply_message", fake_reply), \
         patch.object(messaging.MessagingApi, "push_message", fake_push), \
         patch.object(messaging.MessagingApi, "get_profile", fake_profile), \
         patch("httpx.post", kv.post):
        yield SimpleNamespace(replies=replies, pushes=pushes, raw_replies=raw_replies, raw_pushes=raw_pushes, kv=kv)


def test_non_admin_cannot_use_admin_commands(line_env):
    wh.handle_text_message(_mk_event("/off", user_id="cust1"))
    assert line_env.replies[-1] == ["只有管理員可以使用這個指令。"]


def test_admin_bot_toggle(line_env):
    wh.handle_text_message(_mk_event("/off", user_id="admin1"))
    assert line_env.replies[-1] == ["🔴 Bot 已關閉，小夏老師親自接管。"]
    wh.handle_text_message(_mk_event("/on", user_id="admin1"))
    assert line_env.replies[-1] == ["🟢 Bot 已開啟，助理恢復上班。"]


def test_myid_available_to_non_admin(line_env):
    wh.handle_text_message(_mk_event("/myid", user_id="cust1"))
    assert line_env.replies[-1] == ["你的 LINE User ID：\ncust1\n\n⚠️ 這支帳號不是目前設定的管理員\nADMIN_LINE_USER_ID：已設定"]


def test_ok_with_no_pending_bookings(line_env):
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))
    assert line_env.replies[-1] == ["目前沒有待確認日期的預約。"]


def test_ok_continues_when_payment_qr_url_missing(line_env, monkeypatch):
    monkeypatch.setattr(wh.settings, "payment_qr_image_url", "")
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))

    line_env.replies.clear()
    line_env.pushes.clear()
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))

    assert "匯款資訊已發送給客人" in line_env.replies[-1][0]
    assert line_env.pushes == [("cust1", [("FLEX", "匯款資訊 — 預約日期已確認")])]
    assert "awaiting_payment" in line_env.kv.store[next(iter(k for k in line_env.kv.store if k.startswith("booking:")))]


def test_ok_falls_back_to_self_hosted_qr_image(line_env, monkeypatch):
    """PAYMENT_QR_IMAGE_URL 未設定時，匯款卡片改用 app 自己伺服的 /qr-payment.png。"""
    monkeypatch.setattr(wh.settings, "payment_qr_image_url", "")
    monkeypatch.setattr(wh.settings, "public_base_url", "https://bot.example.com")
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))

    line_env.raw_pushes.clear()
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))

    flex = line_env.raw_pushes[-1].messages[0]
    assert "https://bot.example.com/qr-payment.png" in str(flex.contents.to_dict())


def test_full_booking_lifecycle(line_env):
    _seed_open_slots(line_env)
    # 第一次「我要預約」→ 原則說明卡片
    wh.handle_text_message(_mk_event("我要預約", user_id="cust1"))
    assert line_env.replies[-1] == [("FLEX", "預約諮詢前，請先了解百無禁忌的原則")]

    # 第二次 → 顯示手動開放日期
    wh.handle_text_message(_mk_event("我要預約", user_id="cust1"))
    assert line_env.replies[-1] == [("FLEX", "選擇預約日期")]

    # 選擇日期+時段 → 建立 pending 預約，通知管理員
    wh.handle_text_message(_mk_event(f"預約 {D1} 15:00", user_id="cust1"))
    # Hybrid intake should reply with the prompt card while admin still receives booking request.
    assert line_env.replies[-1] == [("FLEX", "預約申請已送出，請填寫諮詢資料")]
    assert "intake_step:cust1" not in line_env.kv.store
    assert line_env.pushes[-1][0] == "admin1"
    assert "📅 預約申請" in line_env.pushes[-1][1][0]

    # 管理員 /ok → 發匯款資訊
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))
    assert "匯款資訊已發送給客人" in line_env.replies[-1][0]

    # 管理員 /ok 後仍可補填諮詢資料
    wh.handle_text_message(_mk_event("姓名：王小明 出生年月日時：1990-01-01 08:00 問題：想問工作", user_id="cust1"))
    assert "已收到您的諮詢資料" in line_env.replies[-1][0]

    # 客人回報已匯款
    wh.handle_text_message(_mk_event("已匯款", user_id="cust1"))
    assert "已收到您的匯款回報" in line_env.replies[-1][0]

    # 管理員 /paid → 完成預約（無 Calendar 設定，行事曆建立失敗屬預期）
    wh.handle_text_message(_mk_event("/paid", user_id="admin1"))
    assert "已完成" in line_env.replies[-1][0]

    # 完成後應從進行中佇列移除
    wh.handle_text_message(_mk_event("/list", user_id="admin1"))
    assert line_env.replies[-1] == ["📋 目前沒有任何進行中的預約。"]

    # /change 對已完成的預約改期
    wh.handle_text_message(_mk_event(f"/change {D1} 16:00", user_id="admin1"))
    assert "已改期" in line_env.replies[-1][0]


def test_booking_entry_uses_web_calendar_when_base_url_is_set(line_env, monkeypatch):
    monkeypatch.setattr(wh.settings, "public_base_url", "https://example.com")
    monkeypatch.setattr("app.routers.webhook.has_seen_principles", lambda user_id: True)

    wh.handle_text_message(_mk_event("時段", user_id="cust1"))

    assert line_env.replies[-1] == [("FLEX", "選擇預約時段")]


def test_admin_can_request_booking_editor_link(line_env, monkeypatch):
    monkeypatch.setattr(wh.settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(wh.settings, "admin_page_token", "secret-token")

    wh.handle_text_message(_mk_event("設定時段", user_id="admin1"))

    assert line_env.replies[-1] == [("FLEX", "設定可預約時段")]


def test_admin_booking_editor_link_requires_env(line_env, monkeypatch):
    monkeypatch.setattr(wh.settings, "public_base_url", "")
    monkeypatch.setattr(wh.settings, "admin_page_token", "secret-token")

    wh.handle_text_message(_mk_event("/booking-admin", user_id="admin1"))

    assert "尚未設定 PUBLIC_BASE_URL 或 ADMIN_PAGE_TOKEN" in line_env.replies[-1][0]


def test_no_rejects_booking_and_notifies_customer(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D2} 15:00", user_id="cust3"))
    wh.handle_text_message(_mk_event("/no", user_id="admin1"))
    assert "已婉拒" in line_env.replies[-1][0]
    assert line_env.pushes[-1][0] == "cust3"
    assert "無法安排" in line_env.pushes[-1][1][0]


def test_clear_requires_confirmation(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D3} 15:00", user_id="cust2"))

    wh.handle_text_message(_mk_event("/clear", user_id="admin1"))
    assert "即將清除全部 1 筆預約" in line_env.replies[-1][0]

    wh.handle_text_message(_mk_event("/clear yes", user_id="admin1"))
    assert "已清除全部 1 筆預約" in line_env.replies[-1][0]

    # 再次清除已無預約
    wh.handle_text_message(_mk_event("/clear", user_id="admin1"))
    assert line_env.replies[-1] == ["📋 目前沒有任何預約需要清除。"]


def test_redelivered_event_is_skipped(line_env):
    event = _mk_event("/myid", user_id="cust1")
    event.delivery_context.is_redelivery = True
    wh.handle_text_message(event)
    assert line_env.replies == []


def test_bot_off_notifies_customer_once(line_env):
    wh.handle_text_message(_mk_event("/off", user_id="admin1"))

    line_env.replies.clear()
    wh.handle_text_message(_mk_event("服務項目", user_id="cust1"))
    assert line_env.replies[-1] == ["小夏老師目前在線上，請稍候老師回覆 🙏"]

    # 第二次不再重複通知（靜默不回應）
    line_env.replies.clear()
    wh.handle_text_message(_mk_event("服務項目", user_id="cust1"))
    assert line_env.replies == []

    # 管理員即使在 Bot 關閉期間仍可正常互動
    line_env.replies.clear()
    wh.handle_text_message(_mk_event("服務項目", user_id="admin1"))
    assert line_env.replies[-1] == [("FLEX", "百無禁忌研究所 — 服務項目")]


def test_intake_pending_captures_full_name_and_birth(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))

    line_env.pushes.clear()
    line_env.replies.clear()
    wh.handle_text_message(_mk_event("1. 王小明\n2. 1990-01-01\n3. 想問工作", user_id="cust1"))
    assert "已收到您的諮詢資料" in line_env.replies[-1][0]
    assert line_env.pushes[-1][0] == "admin1"
    assert "王小明" in line_env.kv.store["intake_data:cust1"]


def test_intake_pending_rejects_placeholder_template_and_keeps_waiting(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))

    line_env.replies.clear()
    wh.handle_text_message(_mk_event("1. 姓名\n2. 出生年月日時\n3. 想問的問題", user_id="cust1"))
    assert line_env.replies[-1] == [wh.INTAKE_RETRY_TEXT]
    assert "intake_data:cust1" not in line_env.kv.store
    assert line_env.kv.store["intake_pending:cust1"] == "1"

    wh.handle_text_message(_mk_event("1. 王小明\n2. 1990-01-01 08:00\n3. 想問工作", user_id="cust1"))
    assert "已收到您的諮詢資料" in line_env.replies[-1][0]
    assert "王小明" in line_env.kv.store["intake_data:cust1"]


def test_intake_pending_rejects_incomplete_free_text_and_keeps_waiting(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))

    line_env.replies.clear()
    wh.handle_text_message(_mk_event("王小明 1990-01-01 想問工作", user_id="cust1"))
    assert "請直接回覆出生年月日時" in line_env.replies[-1][0]
    assert "intake_data:cust1" not in line_env.kv.store
    assert line_env.kv.store["intake_pending:cust1"] == "1"

def test_intake_pending_does_not_swallow_other_intent(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))

    # 預約後客人改問服務項目，不應回分類卡；改為重發 intake 卡片，之後同類訊息靜默。
    line_env.replies.clear()
    wh.handle_text_message(_mk_event("服務項目", user_id="cust1"))
    assert line_env.replies[-1] == [("FLEX", "預約申請已送出，請填寫諮詢資料")]
    line_env.replies.clear()
    wh.handle_text_message(_mk_event("服務項目", user_id="cust1"))
    assert line_env.replies == []


def test_booking_completion_sends_intake_prompt_card_without_step(line_env, monkeypatch):
    monkeypatch.setattr(wh.settings, "bot_basic_id", "@baiwujiji")
    _seed_open_slots(line_env)

    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))

    assert line_env.replies[-1] == [("FLEX", "預約申請已送出，請填寫諮詢資料")]
    flex_json = line_env.raw_replies[-1].messages[0].contents.to_dict()
    assert "https://line.me/R/oaMessage/@baiwujiji/" in json.dumps(flex_json, ensure_ascii=False)
    assert line_env.kv.store["intake_pending:cust1"] == "1"
    assert "intake_step:cust1" not in line_env.kv.store


def test_pending_intake_form_with_keyword_question_finishes_and_clears(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))

    line_env.replies.clear()
    wh.handle_text_message(_mk_event("1. 王小明\n2. 1990-01-01 08:00\n3. 想問感情", user_id="cust1"))

    assert "已收到您的諮詢資料" in line_env.replies[-1][0]
    data = json.loads(line_env.kv.store["intake_data:cust1"])
    assert data == {"n": "王小明", "b": "1990-01-01 08:00", "q": "想問感情"}
    assert "intake_pending:cust1" not in line_env.kv.store
    assert "intake_step:cust1" not in line_env.kv.store
    assert "intake_draft:cust1" not in line_env.kv.store
    assert "intake_reprompted:cust1" not in line_env.kv.store


def test_pending_stepwise_birth_multiline_and_keyword_question(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))

    wh.handle_text_message(_mk_event("王小明", user_id="cust1"))
    assert "請直接回覆出生年月日時" in line_env.replies[-1][0]
    wh.handle_text_message(_mk_event("1990年5月15日\n早上八點", user_id="cust1"))
    assert "請直接回覆想問的問題" in line_env.replies[-1][0]
    wh.handle_text_message(_mk_event("想問感情和財運", user_id="cust1"))

    data = json.loads(line_env.kv.store["intake_data:cust1"])
    assert data == {"n": "王小明", "b": "1990年5月15日\n早上八點", "q": "想問感情和財運"}
    assert "已收到您的諮詢資料" in line_env.replies[-1][0]


def test_paid_confirmation_card_uses_line_display_name_not_intake_name(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))
    wh.handle_text_message(_mk_event("1. 王小明\n2. 1990-01-01 08:00\n3. 想問感情", user_id="cust1"))
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))
    wh.handle_text_message(_mk_event("已匯款", user_id="cust1"))

    line_env.raw_pushes.clear()
    wh.handle_text_message(_mk_event("/paid", user_id="admin1"))

    customer_push = line_env.raw_pushes[0]
    flex_json = customer_push.messages[0].contents.to_dict()
    card_text = json.dumps(flex_json, ensure_ascii=False)
    assert "User-cust1" in card_text
    assert "王小明" not in card_text
    assert "1990-01-01 08:00" in card_text
    assert "想問感情" in card_text


def test_pending_escape_payment_and_human(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))

    line_env.replies.clear()
    wh.handle_text_message(_mk_event("已匯款", user_id="cust1"))
    assert "已收到您的匯款回報" in line_env.replies[-1][0]

    wh.handle_text_message(_mk_event(f"預約 {D4} 16:00", user_id="cust2"))
    line_env.replies.clear()
    wh.handle_text_message(_mk_event("找小夏老師", user_id="cust2"))
    assert "已經通知小夏老師" in line_env.replies[-1][0]


def test_intake_symbol_form_and_no_clear_state(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D4} 15:00", user_id="cust1"))
    wh.handle_text_message(_mk_event("①王小明②1990-01-01③想問感情", user_id="cust1"))
    line_env.replies.clear()
    wh.handle_text_message(_mk_event("謝謝", user_id="cust1"))
    assert line_env.replies == []

    wh.handle_text_message(_mk_event(f"預約 {D4} 16:00", user_id="cust2"))
    wh.handle_text_message(_mk_event("王小美", user_id="cust2"))
    wh.handle_text_message(_mk_event("/no", user_id="admin1"))
    line_env.replies.clear()
    wh.handle_text_message(_mk_event("好的", user_id="cust2"))
    assert line_env.replies == []


def test_paid_records_customer_visit_for_returning_recognition(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D1} 15:00", user_id="cust9"))
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))
    wh.handle_text_message(_mk_event("已匯款", user_id="cust9"))
    wh.handle_text_message(_mk_event("/paid", user_id="admin1"))

    profile = json.loads(line_env.kv.store["customer:cust9"])
    assert profile["c"] == 1
    assert profile["last"] == D1
    assert profile["n"] == "User-cust9"


def test_new_booking_notifies_admin_with_first_time_label(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D1} 15:00", user_id="cust1"))

    assert "🆕 第一次預約" in line_env.pushes[-1][1][0]


def test_new_booking_notifies_admin_with_returning_label(line_env):
    _seed_open_slots(line_env)
    line_env.kv.store["customer:cust1"] = json.dumps(
        {"n": "User-cust1", "c": 2, "first": "2026-05-01", "last": "2026-06-20"}, ensure_ascii=False
    )

    wh.handle_text_message(_mk_event(f"預約 {D1} 15:00", user_id="cust1"))

    admin_msg = line_env.pushes[-1][1][0]
    assert "↩️ 回頭客" in admin_msg
    assert "已完成 2 次" in admin_msg


def test_booking_entry_card_is_personalized_for_returning_customer(line_env, monkeypatch):
    monkeypatch.setattr(wh.settings, "public_base_url", "https://example.com")
    monkeypatch.setattr("app.routers.webhook.has_seen_principles", lambda user_id: True)
    line_env.kv.store["customer:cust1"] = json.dumps(
        {"n": "User-cust1", "c": 1, "first": "2026-06-20", "last": "2026-06-20"}, ensure_ascii=False
    )

    wh.handle_text_message(_mk_event("我要預約", user_id="cust1"))

    assert line_env.replies[-1] == [("FLEX", "選擇預約時段")]
    card = line_env.raw_replies[-1].messages[0].contents.to_dict()
    flat = json.dumps(card, ensure_ascii=False)
    assert "歡迎回來" in flat
    assert "第 2 次預約" in flat
    assert "uid=cust1" in flat and "sig=" in flat


def test_booking_entry_card_has_no_welcome_for_new_customer(line_env, monkeypatch):
    monkeypatch.setattr(wh.settings, "public_base_url", "https://example.com")
    monkeypatch.setattr("app.routers.webhook.has_seen_principles", lambda user_id: True)

    wh.handle_text_message(_mk_event("我要預約", user_id="cust1"))

    card = line_env.raw_replies[-1].messages[0].contents.to_dict()
    flat = json.dumps(card, ensure_ascii=False)
    assert "歡迎回來" not in flat


def test_booking_gets_order_no_and_admin_sees_it(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D1} 15:00", user_id="cust1"))

    booking_key = next(k for k in line_env.kv.store if k.startswith("booking:"))
    booking = json.loads(line_env.kv.store[booking_key])
    assert booking["o"].startswith("B-")
    assert f"編號 {booking['o']}" in line_env.pushes[-1][1][0]

    # /list 也要顯示編號
    wh.handle_text_message(_mk_event("/list", user_id="admin1"))
    assert booking["o"] in line_env.replies[-1][0]


def test_order_status_query_lists_customer_bookings(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D1} 15:00", user_id="cust1"))
    wh.handle_text_message(_mk_event(f"預約 {D2} 15:00", user_id="cust2"))

    # intake_pending 中也能查詢（逃逸名單）
    wh.handle_text_message(_mk_event("進度查詢", user_id="cust1"))
    assert line_env.replies[-1] == [("FLEX", "預約進度查詢")]
    card = line_env.raw_replies[-1].messages[0].contents.to_dict()
    flat = json.dumps(card, ensure_ascii=False)
    booking_key = next(k for k in line_env.kv.store if "cust1" in k and k.startswith("booking:"))
    my_order = json.loads(line_env.kv.store[booking_key])["o"]
    assert my_order in flat
    # 只列自己的，不能看到別人的預約
    other_key = next(k for k in line_env.kv.store if "cust2" in k and k.startswith("booking:"))
    other_order = json.loads(line_env.kv.store[other_key])["o"]
    assert other_order not in flat
    assert "等待老師確認日期" in flat


def test_order_status_query_without_bookings(line_env):
    wh.handle_text_message(_mk_event("我的預約", user_id="cust1"))
    assert "目前沒有查得到的預約紀錄" in line_env.replies[-1][0]


def test_confirmed_card_includes_order_no(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D1} 15:00", user_id="cust1"))
    booking_key = next(k for k in line_env.kv.store if k.startswith("booking:"))
    order_no = json.loads(line_env.kv.store[booking_key])["o"]

    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))
    wh.handle_text_message(_mk_event("已匯款", user_id="cust1"))
    line_env.raw_pushes.clear()
    wh.handle_text_message(_mk_event("/paid", user_id="admin1"))

    confirmed = next(p for p in line_env.raw_pushes if p.to == "cust1")
    flat = json.dumps(confirmed.messages[0].contents.to_dict(), ensure_ascii=False)
    assert order_no in flat

    # done 之後進度查詢仍查得到，狀態顯示為預約成立
    wh.handle_text_message(_mk_event("進度查詢", user_id="cust1"))
    flat = json.dumps(line_env.raw_replies[-1].messages[0].contents.to_dict(), ensure_ascii=False)
    assert order_no in flat
    assert "預約成立" in flat


# ============================================================
# 逾時預約掃描（sweep_stale_bookings）
# ============================================================
import time as _time

from app.routers.api import sweep_stale_bookings


def _seed_stale_booking(env, user_id, status, created_secs_ago, now, updated_secs_ago=None):
    ref = f"{user_id}|{int((now - created_secs_ago) * 1000)}"
    booking = {"d": D1, "t": "15:00", "n": f"User-{user_id}", "s": status, "o": "B-2026-0099"}
    if updated_secs_ago is not None:
        booking["u"] = now - updated_secs_ago
    env.kv.store[f"booking:{ref}"] = json.dumps(booking, ensure_ascii=False)
    env.kv.store.setdefault("booking_queue", []).append(ref)
    return ref


def test_sweep_reminds_admin_for_stale_pending_once(line_env):
    now = int(_time.time())
    _seed_stale_booking(line_env, "cust1", "pending", 25 * 3600, now)

    result = sweep_stale_bookings(now)

    assert result == {"admin_reminded": 1, "customer_reminded": 0, "released": 0}
    target, msgs = line_env.pushes[-1]
    assert target == "admin1"
    assert "還沒確認" in msgs[0]
    assert "B-2026-0099" in msgs[0]

    # 鎖住後同一次不重複提醒
    assert sweep_stale_bookings(now)["admin_reminded"] == 0


def test_sweep_ignores_fresh_bookings(line_env):
    now = int(_time.time())
    _seed_stale_booking(line_env, "cust1", "pending", 2 * 3600, now)
    _seed_stale_booking(line_env, "cust2", "awaiting_payment", 30 * 3600, now, updated_secs_ago=3 * 3600)

    result = sweep_stale_bookings(now)

    assert result == {"admin_reminded": 0, "customer_reminded": 0, "released": 0}
    assert line_env.pushes == []


def test_sweep_reminds_customer_awaiting_payment_after_48h(line_env):
    now = int(_time.time())
    ref = _seed_stale_booking(line_env, "cust1", "awaiting_payment", 60 * 3600, now, updated_secs_ago=49 * 3600)

    result = sweep_stale_bookings(now)

    assert result == {"admin_reminded": 0, "customer_reminded": 1, "released": 0}
    target, msgs = line_env.pushes[-1]
    assert target == "cust1"
    assert "仍在等待匯款" in msgs[0]
    assert f"booking:{ref}" in line_env.kv.store  # 預約還在，只是提醒

    assert sweep_stale_bookings(now)["customer_reminded"] == 0  # 只提醒一次


def test_sweep_releases_awaiting_payment_after_72h(line_env):
    now = int(_time.time())
    ref = _seed_stale_booking(line_env, "cust1", "awaiting_payment", 80 * 3600, now, updated_secs_ago=73 * 3600)

    result = sweep_stale_bookings(now)

    assert result == {"admin_reminded": 0, "customer_reminded": 0, "released": 1}
    assert f"booking:{ref}" not in line_env.kv.store
    assert line_env.kv.store.get("booking_queue", []) == []
    targets = [t for t, _ in line_env.pushes]
    assert "cust1" in targets and "admin1" in targets
    customer_msg = next(m for t, m in line_env.pushes if t == "cust1")[0]
    assert "已自動取消" in customer_msg


def test_sweep_never_releases_payment_reported(line_env):
    now = int(_time.time())
    ref = _seed_stale_booking(line_env, "cust1", "payment_reported", 200 * 3600, now, updated_secs_ago=150 * 3600)

    result = sweep_stale_bookings(now)

    assert result == {"admin_reminded": 0, "customer_reminded": 0, "released": 0}
    assert f"booking:{ref}" in line_env.kv.store


def test_update_booking_status_stamps_transition_time(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D1} 15:00", user_id="cust1"))
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))

    booking_key = next(k for k in line_env.kv.store if k.startswith("booking:"))
    booking = json.loads(line_env.kv.store[booking_key])
    assert booking["s"] == "awaiting_payment"
    assert abs(booking["u"] - _time.time()) < 60


def test_booking_and_paid_accumulate_monthly_stats(line_env):
    _seed_open_slots(line_env)
    wh.handle_text_message(_mk_event(f"預約 {D1} 15:00", user_id="cust1"))
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))
    wh.handle_text_message(_mk_event("已匯款", user_id="cust1"))
    wh.handle_text_message(_mk_event("/paid", user_id="admin1"))

    stats = {k: v for k, v in line_env.kv.store.items() if k.startswith("stats:")}
    month = next(iter(stats)).split(":")[1]
    assert line_env.kv.store[f"stats:{month}:new"] == "1"
    assert line_env.kv.store[f"stats:{month}:done"] == "1"


def test_sweep_release_counts_into_monthly_stats(line_env):
    now = int(_time.time())
    _seed_stale_booking(line_env, "cust1", "awaiting_payment", 80 * 3600, now, updated_secs_ago=73 * 3600)

    sweep_stale_bookings(now)

    month = next(k for k in line_env.kv.store if k.startswith("stats:")).split(":")[1]
    assert line_env.kv.store[f"stats:{month}:released"] == "1"


def test_admin_dashboard_command_sends_link(line_env, monkeypatch):
    monkeypatch.setattr(wh.settings, "public_base_url", "https://example.com")
    monkeypatch.setattr(wh.settings, "admin_page_token", "secret-token")

    wh.handle_text_message(_mk_event("/admin", user_id="admin1"))
    assert "https://example.com/admin.html?token=secret-token" in line_env.replies[-1][0]

    wh.handle_text_message(_mk_event("管理後台", user_id="cust1"))
    assert line_env.replies[-1] == ["只有管理員可以使用這個指令。"]
