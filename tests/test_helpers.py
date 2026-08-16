"""tests/test_helpers.py — 测试 utils/helpers.py 工具函数"""
import sys
sys.path.insert(0, '.')

from utils.helpers import (
    _mask_urls,
    sanitize_filename,
    unix_to_iso,
    parse_iso_datetime,
    _clean_ai_output,
    human_reply_delay,
)


class TestMaskUrls:
    def test_masks_domain(self):
        result = _mask_urls("访问 https://api.openai.com/v1/chat 出错")
        assert "api.openai.com" not in result
        assert "***" in result
        assert "/v1/chat" in result

    def test_empty_string(self):
        assert _mask_urls("") == ""

    def test_none(self):
        assert _mask_urls(None) is None

    def test_no_url(self):
        assert _mask_urls("普通文本无URL") == "普通文本无URL"


class TestSanitizeFilename:
    def test_removes_special_chars(self):
        assert sanitize_filename('test<>:"file.txt') == 'testfile.txt'

    def test_folder_mode_truncates(self):
        result = sanitize_filename('very_long_folder_name_here', is_folder=True)
        assert len(result) <= 10

    def test_file_mode_truncates(self):
        result = sanitize_filename('x' * 200, is_folder=False)
        assert len(result) <= 100

    def test_strips_whitespace(self):
        assert sanitize_filename('  hello  ') == 'hello'


class TestUnixToIso:
    def test_valid_timestamp(self):
        result = unix_to_iso(1717200000)
        assert result.startswith('2024-06')
        assert 'T' in result

    def test_invalid_returns_empty(self):
        assert unix_to_iso("not_a_number") == ""


class TestParseIsoDatetime:
    def test_valid_iso(self):
        result = parse_iso_datetime("2024-06-01T12:00:00")
        assert result is not None

    def test_empty_returns_none(self):
        assert parse_iso_datetime("") is None

    def test_none_returns_none(self):
        assert parse_iso_datetime(None) is None


class TestCleanAiOutput:
    def test_removes_referenced_files(self):
        text = "hello\n[Referenced files] some_file.md\n\nworld"
        result = _clean_ai_output(text)
        assert "[Referenced files]" not in result
        assert "hello" in result
        assert "world" in result

    def test_removes_file_tags(self):
        text = 'text <file path="x.md" skipped="missing" /> end'
        result = _clean_ai_output(text)
        assert "file path" not in result


class TestHumanReplyDelay:
    def test_returns_number(self):
        result = human_reply_delay()
        assert isinstance(result, float)
        assert result >= 0
