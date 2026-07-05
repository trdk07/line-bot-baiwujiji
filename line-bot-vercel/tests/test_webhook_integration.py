"""
webhook.handle_text_message 的端對端整合測試。
模擬 LINE Messaging API（reply_message / push_message / get_profile）與
Upstash KV（httpx.post），驗證完整的管理員指令與預約流程行為不變——
特別是 2-3 重構（管理員指令表化）前後的行為一致性。
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import linebot.v3.messaging as messaging

import app.routers.webhook as wh


class FakeKV:
    def __init__(self):
        self.store = {}

    def exec_cmd(self, cmd):
        op = cmd[0]
        if op == "SET":
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

    kv = FakeKV()
    replies, pushes = [], []

    def fake_reply(self, req):
        replies.append(_extract(req))

    def fake_push(self, req):
        pushes.append((req.to, _extract(req)))

    def fake_profile(self, user_id):
        return SimpleNamespace(display_name=f"User-{user_id}")

    with patch.object(messaging.MessagingApi, "reply_message", fake_reply), \
         patch.object(messaging.MessagingApi, "push_message", fake_push), \
         patch.object(messaging.MessagingApi, "get_profile", fake_profile), \
         patch("httpx.post", kv.post):
        yield SimpleNamespace(replies=replies, pushes=pushes, kv=kv)


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
    assert line_env.replies[-1] == ["你的 LINE User ID：\ncust1"]


def test_ok_with_no_pending_bookings(line_env):
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))
    assert line_env.replies[-1] == ["目前沒有待確認日期的預約。"]


def test_full_booking_lifecycle(line_env):
    # 第一次「我要預約」→ 原則說明卡片
    wh.handle_text_message(_mk_event("我要預約", user_id="cust1"))
    assert line_env.replies[-1] == [("FLEX", "預約諮詢前，請先了解百無禁忌的原則")]

    # 第二次 → 沒有 Google Calendar 設定，走 booking_card fallback
    wh.handle_text_message(_mk_event("我要預約", user_id="cust1"))
    assert line_env.replies[-1] == [("FLEX", "預約諮詢")]

    # 選擇日期+時段 → 建立 pending 預約，通知管理員
    wh.handle_text_message(_mk_event("預約 2026-03-02 15:00", user_id="cust1"))
    assert "預約申請已送出" in line_env.replies[-1][0]
    assert line_env.pushes[-1][0] == "admin1"
    assert "📅 預約申請" in line_env.pushes[-1][1][0]

    # 管理員 /ok → 發匯款資訊
    wh.handle_text_message(_mk_event("/ok", user_id="admin1"))
    assert "匯款資訊已發送給客人" in line_env.replies[-1][0]

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
    wh.handle_text_message(_mk_event("/change 2026-03-03 16:00", user_id="admin1"))
    assert "已改期" in line_env.replies[-1][0]


def test_no_rejects_booking_and_notifies_customer(line_env):
    wh.handle_text_message(_mk_event("預約 2026-03-05 15:00", user_id="cust3"))
    wh.handle_text_message(_mk_event("/no", user_id="admin1"))
    assert "已婉拒" in line_env.replies[-1][0]
    assert line_env.pushes[-1][0] == "cust3"
    assert "無法安排" in line_env.pushes[-1][1][0]


def test_clear_requires_confirmation(line_env):
    wh.handle_text_message(_mk_event("預約 2026-03-04 15:00", user_id="cust2"))

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
    wh.handle_text_message(_mk_event("預約 2026-03-02 15:00", user_id="cust1"))

    line_env.pushes.clear()
    line_env.replies.clear()
    wh.handle_text_message(_mk_event("1. 王小明\n2. 1990-01-01\n3. 想問工作", user_id="cust1"))
    assert "已收到您的諮詢資料" in line_env.replies[-1][0]
    assert line_env.pushes[-1][0] == "admin1"


def test_intake_pending_does_not_swallow_other_intent(line_env):
    wh.handle_text_message(_mk_event("預約 2026-03-02 15:00", user_id="cust1"))

    # 預約後客人改問服務項目，不應被誤判為諮詢資料
    line_env.replies.clear()
    wh.handle_text_message(_mk_event("服務項目", user_id="cust1"))
    assert line_env.replies[-1] == [("FLEX", "百無禁忌研究所 — 服務項目")]
