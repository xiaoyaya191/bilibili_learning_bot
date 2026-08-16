"""tests/test_json_utils.py — 测试 json_utils.py JsonStore"""
import sys
import os
import tempfile
sys.path.insert(0, '.')

from utils.storage import JsonStore, sanitize_export, is_safe_path


class TestJsonStore:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "test.json")

    def teardown_method(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_read(self):
        store = JsonStore(self.path)
        store.write({"key": "value"})
        data = store.read()
        assert data == {"key": "value"}

    def test_read_nonexistent_returns_empty_dict(self):
        store = JsonStore(self.path)
        assert store.read() == {}

    def test_read_with_default(self):
        store = JsonStore(self.path)
        assert store.read(default=[]) == []

    def test_exists(self):
        store = JsonStore(self.path)
        assert not store.exists()
        store.write({})
        assert store.exists()

    def test_update(self):
        store = JsonStore(self.path)
        store.write({"a": 1})
        store.update(lambda d: d.update({"b": 2}))
        data = store.read()
        assert data == {"a": 1, "b": 2}

    def test_stat(self):
        store = JsonStore(self.path)
        store.write({"test": "data"})
        stat = store.stat()
        assert stat["exists"]
        assert stat["size"] > 0


class TestSanitizeExport:
    def test_masks_api_key(self):
        data = {"api": {"api_key": "sk-secret123"}}
        result = sanitize_export(data)
        assert result["api"]["api_key"] == "[已隐藏]"

    def test_masks_nested(self):
        data = {"providers": [{"api_key": "sk-1"}, {"api_key": "sk-2"}]}
        result = sanitize_export(data)
        assert result["providers"][0]["api_key"] == "[已隐藏]"
        assert result["providers"][1]["api_key"] == "[已隐藏]"

    def test_preserves_non_sensitive(self):
        data = {"name": "test", "api_key": "sk-secret"}
        result = sanitize_export(data)
        assert result["name"] == "test"


class TestIsSafePath:
    def test_valid_path(self):
        assert is_safe_path("test.json", "/tmp/mydir")

    def test_rejects_dotdot(self):
        assert not is_safe_path("../etc/passwd", "/tmp/mydir")

    def test_rejects_dotdot_middle(self):
        assert not is_safe_path("data/../../etc/passwd", "/tmp/mydir")
