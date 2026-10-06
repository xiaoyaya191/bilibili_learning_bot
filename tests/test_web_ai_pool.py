import asyncio
from copy import deepcopy
from pathlib import Path

import pytest

from services.ai_pool import DEFAULTS, ENDPOINT_DEFAULTS


def endpoint(identifier, **changes):
    result = dict(ENDPOINT_DEFAULTS, id=identifier, name=identifier, base_url="https://example.test/v1", api_key=identifier + "-secret", model_chat="test")
    result.update(changes)
    return result


@pytest.fixture
def pool_api(tmp_path, monkeypatch):
    import core.config as core_config
    import web_panel
    state = {"api_pool": dict(deepcopy(DEFAULTS), endpoints=[endpoint("a", headers={"X-Key": "header-secret"}), endpoint("b")]), "api": {"unified_api_key": "primary-secret", "model_brain": "model"}}
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel.app, "testing", True)
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])
    monkeypatch.setattr(core_config, "load_config", lambda: deepcopy(state))
    monkeypatch.setattr(core_config, "config", deepcopy(state))
    def save(value):
        state.clear()
        state.update(deepcopy(value))
        return True
    monkeypatch.setattr(core_config, "save_config", save)
    return web_panel.app.test_client(), state


def test_get_masks_keys_headers_and_save_by_id_not_position(pool_api):
    client, state = pool_api
    response = client.get("/api/ai-pool").get_json()
    assert response["settings"]["endpoints"][0]["api_key"] == "[已隐藏]"
    assert response["settings"]["endpoints"][0]["headers"] == "[已隐藏]"
    assert "a-secret" not in str(response)
    response["settings"]["endpoints"].reverse()
    assert client.post("/api/ai-pool", json=response["settings"]).get_json()["ok"]
    assert state["api_pool"]["endpoints"][0]["id"] == "b"
    assert state["api_pool"]["endpoints"][0]["api_key"] == "b-secret"
    assert state["api_pool"]["endpoints"][1]["headers"] == {"X-Key": "header-secret"}


def test_json_editor_preserves_masked_pool_after_reorder(pool_api):
    client, state = pool_api
    configuration = client.get("/api/config").get_json()
    assert configuration["api_pool"]["endpoints"][0]["headers"] == "[已隐藏]"
    configuration["api_pool"]["endpoints"].reverse()
    assert client.post("/api/config", json=configuration).get_json()["ok"]
    assert state["api_pool"]["endpoints"][0]["api_key"] == "b-secret"
    assert state["api_pool"]["endpoints"][1]["api_key"] == "a-secret"
    assert state["api"]["unified_api_key"] == "primary-secret"


def test_empty_secret_explicitly_deletes_and_other_settings_do_not_overwrite_pool(pool_api):
    client, state = pool_api
    preferences = client.get("/api/ai-pool").get_json()["settings"]
    preferences["endpoints"][0]["api_key"] = ""
    assert client.post("/api/ai-pool", json=preferences).get_json()["ok"]
    assert state["api_pool"]["endpoints"][0]["api_key"] == ""
    assert client.post("/api/config", json={"api": {"model_brain": "new-model"}}).get_json()["ok"]
    assert len(state["api_pool"]["endpoints"]) == 2


@pytest.mark.parametrize("body", [[1], {"rounds": 11}, {"endpoints": "bad"}, {"enabled": "true"}, {"retry_statuses": [400]}, {"endpoints": [endpoint("a"), endpoint("a")]}])
def test_invalid_request_rejected_without_mutation(pool_api, body):
    client, state = pool_api
    previous = deepcopy(state)
    assert client.post("/api/ai-pool", json=body).status_code == 400
    assert state == previous


def test_reset_and_test_require_explicit_confirmation(pool_api, monkeypatch):
    client, state = pool_api
    assert client.post("/api/ai-pool/reset", json={}).status_code == 400
    assert client.post("/api/ai-pool/test", json={"id": "a"}).status_code == 400
    assert client.post("/api/ai-pool/reset", json={"confirmed": True}).get_json()["ok"]
    seen = []
    async def fake_route(payload, **kwargs):
        seen.append(kwargs)
        return {"choices": [{"message": {"content": "OK"}}]}
    monkeypatch.setattr("services.ai_pool.route", fake_route)
    response = client.post("/api/ai-pool/test", json={"confirmed": True, "id": "a"})
    assert response.get_json()["ok"]
    assert seen[0]["config_data"]["api_pool"]["attempt_limit"] == 1
    assert [item["id"] for item in seen[0]["config_data"]["api_pool"]["endpoints"]] == ["a"]
    assert not state["api_pool"]["enabled"]


def test_authentication_required(monkeypatch):
    import web_panel
    monkeypatch.setattr(web_panel.app, "testing", False)
    client = web_panel.app.test_client()
    for method, path in (("GET", "/api/ai-pool"), ("POST", "/api/ai-pool"), ("POST", "/api/ai-pool/test"), ("POST", "/api/ai-pool/reset")):
        response = client.open(path, method=method)
        assert response.status_code == 401
        assert response.get_json()["auth_required"]


def test_pool_visible_in_api_config_tab_and_dedicated_save():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web_panel.html").read_text(encoding="utf-8")
    assert "多API接口池" in html
    assert "ai-pool.js" in html
    assert "delete c.api_pool;" in html
    assert "if(window.loadAiPool)loadAiPool();" in html


def test_main_brain_and_services_use_pool_and_live_config(monkeypatch):
    import core.config
    from brain._brain_ai import BrainAIMixin
    from services import _services_ai
    configuration = {"api_pool": dict(deepcopy(DEFAULTS), enabled=True, include_primary=False, endpoints=[endpoint("a")]), "api": {"model_brain": "test"}}
    monkeypatch.setattr(core.config, "load_config", lambda: deepcopy(configuration))
    calls = []
    async def fake_route(payload, **kwargs):
        calls.append(payload)
        return {"choices": [{"message": {"content": "pooled"}}]}
    monkeypatch.setattr("services.ai_pool.route", fake_route)
    brain = BrainAIMixin()
    brain._ai_degraded_until = 99999999999
    result = asyncio.run(brain._call_ai_with_retry(messages=[{"role": "user", "content": "hi"}]))
    assert result.choices[0].message.content == "pooled"
    assert brain._ai_degraded_until == 0
    response = asyncio.run(_services_ai.call_ai_raw([{"role": "user", "content": "hi"}], verbose=False))
    assert response.choices[0].message.content == "pooled"
    assert len(calls) == 2


def test_pool_tools_work_without_primary_key_or_model(monkeypatch):
    import core.config
    from services import _services_ai
    configuration = {"api_pool": dict(deepcopy(DEFAULTS), enabled=True, include_primary=False, endpoints=[endpoint("a")]), "api": {}}
    monkeypatch.setattr(core.config, "load_config", lambda: deepcopy(configuration))
    calls = []
    async def fake_route(payload, **kwargs):
        calls.append(payload)
        if len(calls) == 1:
            return {"choices": [{"message": {"content": "", "tool_calls": [{"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}]}}]}
        return {"choices": [{"message": {"content": "done"}}]}
    monkeypatch.setattr("services.ai_pool.route", fake_route)
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
    executed = []
    result = asyncio.run(_services_ai.call_ai_with_tools([{"role": "user", "content": "hi"}], tools, verbose=False, tool_handler=lambda *args: executed.append(args) or "result"))
    assert result == "done"
    assert len(executed) == 1
    assert calls[1]["messages"][-1]["role"] == "tool"

def test_brain_fallback_model_reads_web_setting(monkeypatch):
    import core.config
    from brain._brain_ai import BrainAIMixin
    configuration = {"api": {"model_brain_fallback": "web-fallback"}, "fallback_models": {"chat": "old-fallback"}}
    monkeypatch.setattr(core.config, "load_config", lambda: deepcopy(configuration))
    assert BrainAIMixin()._live_config()["fallback_model_chat"] == "web-fallback"
    configuration["api"]["model_brain_fallback"] = "updated-fallback"
    assert BrainAIMixin()._live_config()["fallback_model_chat"] == "updated-fallback"
