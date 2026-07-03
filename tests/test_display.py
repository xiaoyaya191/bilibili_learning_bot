"""tests/test_display.py — 测试 utils/display.py"""
import sys
sys.path.insert(0, '.')

from utils.display import mask_secret


class TestMaskSecret:
    def test_short_value_fully_masked(self):
        result = mask_secret("abc")
        assert result == "***"

    def test_long_value_partially_masked(self):
        result = mask_secret("sk-1234567890abcdef")
        assert result.startswith("sk-123")
        assert result.endswith("cdef")
        assert "..." in result

    def test_empty_returns_placeholder(self):
        assert mask_secret("") == "(未配置)"

    def test_none_returns_placeholder(self):
        assert mask_secret(None) == "(未配置)"
