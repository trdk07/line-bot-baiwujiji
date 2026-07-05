"""測試 webhook.py 中的純文字解析函式（不涉及 LINE / KV / Calendar API）。"""

import pytest

from app.routers.webhook import _parse_intake_text, _parse_booking_number


class TestParseIntakeText:
    def test_numbered_dot_format(self):
        text = "1. 王小明\n2. 1990-01-01 08:00\n3. 想問感情運勢"
        name, birth, question = _parse_intake_text(text)
        assert name == "王小明"
        assert birth == "1990-01-01 08:00"
        assert question == "想問感情運勢"

    def test_numbered_dash_format(self):
        text = "1-王小明\n2-1990-01-01\n3-想問工作"
        name, birth, question = _parse_intake_text(text)
        assert name == "王小明"
        assert birth == "1990-01-01"
        assert question == "想問工作"

    def test_numbered_chinese_punctuation(self):
        text = "1、王小明\n2、1990-01-01\n3、想問感情"
        name, birth, question = _parse_intake_text(text)
        assert name == "王小明"
        assert birth == "1990-01-01"
        assert question == "想問感情"

    def test_plain_three_lines_fallback(self):
        text = "王小明\n1990-01-01\n想問感情運勢\n還有其他問題"
        name, birth, question = _parse_intake_text(text)
        assert name == "王小明"
        assert birth == "1990-01-01"
        assert question == "想問感情運勢\n還有其他問題"

    def test_plain_two_lines_fallback(self):
        text = "王小明\n1990-01-01"
        name, birth, question = _parse_intake_text(text)
        assert name == "王小明"
        assert birth == "1990-01-01"
        assert question == ""

    def test_plain_one_line_fallback(self):
        text = "王小明"
        name, birth, question = _parse_intake_text(text)
        assert name == "王小明"
        assert birth == ""
        assert question == ""

    def test_empty_text(self):
        name, birth, question = _parse_intake_text("")
        assert name == ""
        assert birth == ""
        assert question == ""


class TestParseBookingNumber:
    @pytest.mark.parametrize("text,expected", [
        ("/ok", None),
        ("/ok 2", 2),
        ("/ok  10", 10),
        ("/no", None),
        ("/no 3", 3),
        ("/paid", None),
        ("/paid 1", 1),
        ("hello", None),
        ("/list", None),
    ])
    def test_parse_booking_number(self, text, expected):
        assert _parse_booking_number(text) == expected
