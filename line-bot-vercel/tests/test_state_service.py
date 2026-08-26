"""
state_service 的 KV 邏輯測試。
用一個記憶體字典模擬 Upstash REST API（單指令 POST / 與 pipeline POST /pipeline），
驗證收斂後的 kv_cmd/kv_get 樣板行為與各函式的邏輯正確。
"""

import pytest

from app.services import state_service as ss


class FakeKV:
    """模擬 Upstash REST 的最小行為：單指令與 pipeline。"""

    def __init__(self):
        self.store = {}

    def exec_cmd(self, cmd):
        op = cmd[0]
        if op == "SET":
            key, val = cmd[1], cmd[2]
            self.store[key] = val
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
            val = cmd[3]
            if val in lst:
                lst.remove(val)
            return 1
        raise ValueError(f"unsupported op: {op}")

    def post(self, url, headers=None, json=None, timeout=None):
        if url.endswith("/pipeline"):
            return _Resp([{"result": self.exec_cmd(cmd)} for cmd in json])
        return _Resp({"result": self.exec_cmd(json)})


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200
        self.text = ""

    def json(self):
        return self._payload


@pytest.fixture
def fake_kv(monkeypatch):
    kv = FakeKV()
    monkeypatch.setattr(ss, "_get_kv_url", lambda: "http://fake-kv")
    monkeypatch.setattr("httpx.post", kv.post)
    return kv


def test_bot_active_defaults_true_and_toggles(fake_kv):
    assert ss.is_bot_active() is True
    ss.set_bot_active(False)
    assert ss.is_bot_active() is False
    ss.set_bot_active(True)
    assert ss.is_bot_active() is True


def test_bot_off_notification_tracking(fake_kv):
    assert ss.has_been_notified_bot_off("u1") is False
    ss.mark_notified_bot_off("u1")
    assert ss.has_been_notified_bot_off("u1") is True
    assert ss.has_been_notified_bot_off("u2") is False


def test_seen_principles(fake_kv):
    assert ss.has_seen_principles("u1") is False
    ss.set_seen_principles("u1")
    assert ss.has_seen_principles("u1") is True


def test_clear_confirm_pending_roundtrip(fake_kv):
    assert ss.has_clear_confirm_pending() is False
    ss.set_clear_confirm_pending()
    assert ss.has_clear_confirm_pending() is True
    ss.clear_confirm_pending()
    assert ss.has_clear_confirm_pending() is False


def test_booking_lifecycle(fake_kv):
    ss.save_booking("u1", "2026-01-05", "15:00", "Alice")
    pending = ss.get_queue_bookings_by_status("pending")
    assert len(pending) == 1
    ref = pending[0]["ref"]
    assert pending[0]["user_id"] == "u1"
    assert pending[0]["booking"]["n"] == "Alice"

    assert ss.update_booking_status(ref, "awaiting_payment") is True
    awaiting = ss.get_queue_bookings_by_status("awaiting_payment")
    assert len(awaiting) == 1
    assert awaiting[0]["booking"]["s"] == "awaiting_payment"

    ss.delete_booking(ref)
    assert ss.get_all_queue_bookings() == []


def test_update_booking_status_missing_booking_returns_false(fake_kv):
    assert ss.update_booking_status("nonexistent|123", "awaiting_payment") is False


def test_intake_pending_and_data(fake_kv):
    assert ss.has_intake_pending("u1") is False
    ss.set_intake_pending("u1")
    assert ss.has_intake_pending("u1") is True
    ss.clear_intake_pending("u1")
    assert ss.has_intake_pending("u1") is False

    assert ss.get_intake_data("u1") == ("", "", "")
    ss.save_intake_data("u1", "王小明", "1990-01-01", "想問感情")
    assert ss.get_intake_data("u1") == ("王小明", "1990-01-01", "想問感情")
    ss.clear_intake_data("u1")
    assert ss.get_intake_data("u1") == ("", "", "")


def test_done_booking_and_reschedule(fake_kv):
    ss.save_booking("u1", "2026-01-05", "15:00", "Alice")
    ref = ss.get_queue_bookings_by_status("pending")[0]["ref"]
    booking = ss.get_queue_bookings_by_status("pending")[0]["booking"]

    ss.save_done_booking(ref, booking, "evt123")
    done = ss.get_all_done_bookings()
    assert len(done) == 1
    assert done[0]["booking"]["cal_id"] == "evt123"

    assert ss.update_done_booking_datetime(ref, "2026-01-06", "16:00", done[0]["booking"]) is True
    done_after = ss.get_all_done_bookings()
    assert done_after[0]["booking"]["d"] == "2026-01-06"
    assert done_after[0]["booking"]["t"] == "16:00"


def test_get_taken_slots_only_counts_active_statuses(fake_kv):
    ss.save_booking("u1", "2026-01-05", "15:00", "Alice")
    ss.save_booking("u2", "2026-01-05", "16:00", "Bob")
    ref2 = [e for e in ss.get_all_queue_bookings() if e["user_id"] == "u2"][0]["ref"]
    ss.update_booking_status(ref2, "payment_reported")

    taken = ss.get_taken_slots("2026-01-05")
    assert taken == {"15:00", "16:00"}
    assert ss.get_taken_slots("2026-01-06") == set()


def test_customer_profile_accumulates_visits(fake_kv):
    assert ss.get_customer_profile("u1") is None

    ss.record_customer_visit("u1", "Alice", "2026-01-05")
    profile = ss.get_customer_profile("u1")
    assert profile == {"n": "Alice", "c": 1, "first": "2026-01-05", "last": "2026-01-05"}

    ss.record_customer_visit("u1", "Alice", "2026-03-10")
    profile = ss.get_customer_profile("u1")
    assert profile["c"] == 2
    assert profile["first"] == "2026-01-05"
    assert profile["last"] == "2026-03-10"


def test_customer_link_sig_is_stable_and_user_specific(fake_kv):
    sig1 = ss.customer_link_sig("u1")
    assert sig1 == ss.customer_link_sig("u1")
    assert len(sig1) == 16
    assert sig1 != ss.customer_link_sig("u2")


def test_next_order_no_increments_per_year(fake_kv):
    first = ss.next_order_no()
    second = ss.next_order_no()
    year = list(fake_kv.store)[0].split(":")[1]
    assert first == f"B-{year}-0001"
    assert second == f"B-{year}-0002"


def test_save_booking_assigns_order_no(fake_kv):
    order_no = ss.save_booking("u1", "2026-01-05", "15:00", "Alice")
    assert order_no.startswith("B-")
    booking = ss.get_queue_bookings_by_status("pending")[0]["booking"]
    assert booking["o"] == order_no
