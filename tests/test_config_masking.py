"""tests/test_config_masking.py — /api/config 敏感字段脱敏与回写保护.

GET 下发配置时 API Key/密码哈希等被替换为 '[已隐藏]'；
POST 保存时 strip_hidden_placeholders 用磁盘真实值还原占位符，
GET-改-POST 整体回写流程不会覆盖真实凭据。
"""
import json

import web_panel


def _client(monkeypatch, tmp_path, config):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config_path)
    import core.config as core_config
    monkeypatch.setattr(core_config, "CONFIG_FILE", str(config_path))
    client = web_panel.app.test_client()
    with client.session_transaction() as session:
        session["disclaimer_agreed"] = True
        session["panel_authenticated"] = True
    return client


def _saved(tmp_path):
    return json.loads((tmp_path / "config.json").read_text(encoding="utf-8"))


def test_config_get_masks_non_empty_sensitive_values(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, {
        "api": {
            "unified_api_key": "sk-secret",
            "vision_api_key": "sk-vision",
            "unified_base_url": "https://api.example.com/v1",
        },
        "web": {"username": "demo", "password": "hashed-value"},
    })

    data = client.get("/api/config").get_json()

    assert data["api"]["unified_api_key"] == "[已隐藏]"
    assert data["api"]["vision_api_key"] == "[已隐藏]"
    assert data["api"]["unified_base_url"] == "https://api.example.com/v1"
    assert data["web"]["password"] == "[已隐藏]"


def test_config_get_keeps_empty_key_unmasked(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, {
        "api": {"unified_api_key": "", "unified_base_url": ""},
        "web": {"username": "demo", "password": "hashed-value"},
    })

    data = client.get("/api/config").get_json()

    assert data["api"]["unified_api_key"] == ""


def test_masked_roundtrip_preserves_stored_key(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, {
        "api": {"unified_api_key": "sk-secret", "unified_base_url": "https://api.example.com/v1"},
        "web": {"username": "demo", "password": "hashed-value"},
    })

    data = client.get("/api/config").get_json()
    data.setdefault("video", {})["browse_mode"] = "candidate_review"
    response = client.post("/api/config", json=data)

    assert response.get_json()["ok"] is True
    saved = _saved(tmp_path)
    assert saved["api"]["unified_api_key"] == "sk-secret"
    assert saved["web"]["password"] == "hashed-value"
    assert saved["video"]["browse_mode"] == "candidate_review"


def test_post_with_new_plaintext_key_updates_it(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, {
        "api": {"unified_api_key": "sk-old", "unified_base_url": "https://api.example.com/v1"},
        "web": {"username": "demo", "password": "hashed-value"},
    })

    data = client.get("/api/config").get_json()
    data["api"]["unified_api_key"] = "sk-new"
    response = client.post("/api/config", json=data)

    assert response.get_json()["ok"] is True
    assert _saved(tmp_path)["api"]["unified_api_key"] == "sk-new"


def test_models_list_placeholder_falls_back_to_stored_key(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path, {
        "api": {"unified_api_key": "sk-stored", "unified_base_url": "https://api.example.com/v1"},
        "web": {"username": "demo", "password": "hashed-value"},
    })

    captured = {}

    class FakeResponse:
        status = 200

        def read(self):
            return json.dumps({"data": [{"id": "gpt-4o"}]}).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    import urllib.request

    def fake_urlopen(req, timeout=None, context=None):
        captured["auth"] = req.headers.get("Authorization")
        return FakeResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    response = client.get("/api/models/list", query_string={
        "api_key": "[已隐藏]",
        "base_url": "https://api.example.com/v1",
    })

    payload = response.get_json()
    assert payload["ok"] is True
    assert captured["auth"] == "Bearer sk-stored"
