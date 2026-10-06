import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy

import httpx
import pytest

from services import ai_pool
from services.ai_pool import DEFAULTS, ENDPOINT_DEFAULTS, EndpointPool, PoolError, endpoints_for, merge_secret_endpoints, public_settings, route, validate_settings


def endpoint(identifier, **changes):
    result = dict(deepcopy(ENDPOINT_DEFAULTS), id=identifier, name=identifier, base_url=f"https://{identifier}.example/v1", api_key=identifier + "-secret", model_chat="model-" + identifier)
    result.update(changes)
    return result


def config(*items, **changes):
    preferences = dict(deepcopy(DEFAULTS), enabled=True, include_primary=False, retry_delay_seconds=0, endpoints=list(items))
    preferences.update(changes)
    return {"api_pool": preferences, "api": {"model_brain": "original"}}


def answer(content="OK"):
    return {"choices": [{"message": {"content": content}}]}


def mock_network(monkeypatch, handler):
    original = httpx.AsyncClient
    monkeypatch.setattr(ai_pool.httpx, "AsyncClient", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    monkeypatch.setattr("services.proxy_config.get_proxy_url", lambda: "")


def call(tmp_path, configuration, **kwargs):
    return asyncio.run(route({"model": "original", "messages": [{"role": "user", "content": "测试"}]}, config_data=configuration, data_dir=tmp_path, **kwargs))


def test_default_off_and_validation():
    assert not validate_settings({})["enabled"]
    with pytest.raises(PoolError, match="未开启"):
        asyncio.run(route({}, config_data={}))


@pytest.mark.parametrize("changes", [
    {"enabled": "true"}, {"rounds": 0}, {"rounds": 11}, {"attempt_limit": 0},
    {"cooldown_seconds": -1}, {"total_timeout_seconds": float("nan")},
    {"strategy": "bad"}, {"retry_statuses": [400]}, {"failover_statuses": [422]},
    {"endpoints": "bad"}, {"endpoints": [endpoint("same"), endpoint("same")]},
    {"endpoints": [endpoint("primary")]}, {"endpoints": [endpoint("a", base_url="file:///secret")]},
    {"endpoints": [endpoint("a", base_url="https://user:pass@example.com/v1")]},
    {"endpoints": [endpoint("a", base_url="https://example.com/v1?key=secret")]},
    {"endpoints": [endpoint("a", api_key="[已隐藏]")]},
    {"endpoints": [endpoint("a", headers={"Authorization": "secret"})]},
    {"endpoints": [endpoint("a", headers={"X-Key": "bad\nheader"})]},
    {"endpoints": [endpoint("a", weight=0)]}, {"endpoints": [endpoint("a", attempts=6)]},
    {"endpoints": [endpoint("a", timeout_seconds=0)]},
    {"endpoints": [endpoint(str(index)) for index in range(101)]},
])
def test_invalid_settings(changes):
    with pytest.raises(ValueError):
        validate_settings(dict(DEFAULTS, **changes))


def test_round_robin_persists_across_instances(monkeypatch, tmp_path):
    seen = []
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(200, json=answer())
    mock_network(monkeypatch, handler)
    configuration = config(endpoint("a"), endpoint("b"), endpoint("c"))
    for _index in range(4):
        assert call(tmp_path, configuration)["choices"][0]["message"]["content"] == "OK"
    assert seen == ["a.example", "b.example", "c.example", "a.example"]
    assert EndpointPool(tmp_path).status(configuration["api_pool"]["endpoints"])[0]["calls"] == 2


@pytest.mark.parametrize("code", [401, 402, 403, 404, 429, 500, 502, 503, 504])
def test_provider_failure_moves_to_next_without_leaking_keys(monkeypatch, tmp_path, code):
    seen = []
    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "a.example":
            return httpx.Response(code, json={"error": {"message": "a-secret"}})
        return httpx.Response(200, json=answer("second"))
    mock_network(monkeypatch, handler)
    result = call(tmp_path, config(endpoint("a"), endpoint("b"), strategy="failover"))
    assert result["choices"][0]["message"]["content"] == "second"
    assert seen == ["a.example", "b.example"]


def test_request_rejection_not_replayed(monkeypatch, tmp_path):
    seen = []
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(400, json={"error": "a-secret"})
    mock_network(monkeypatch, handler)
    with pytest.raises(PoolError) as error:
        call(tmp_path, config(endpoint("a"), endpoint("b")))
    assert seen == ["a.example"]
    assert "a-secret" not in str(error.value)
    assert "未继续重放" in str(error.value)


def test_no_repeat_auth_or_balance_even_with_zero_cooldown(monkeypatch, tmp_path):
    seen = []
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(402, json={})
    mock_network(monkeypatch, handler)
    with pytest.raises(PoolError):
        call(tmp_path, config(endpoint("a", attempts=5), rounds=10, cooldown_seconds=0))
    assert seen == ["a.example"]


def test_retry_round_and_total_attempt_limit(monkeypatch, tmp_path):
    seen = []
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(503, json={})
    mock_network(monkeypatch, handler)
    with pytest.raises(PoolError, match="总请求次数"):
        call(tmp_path, config(endpoint("a", attempts=5), endpoint("b"), failure_threshold=100, rounds=10, attempt_limit=3))
    assert len(seen) == 3


def test_retry_after_cools_only_failed_endpoint(monkeypatch, tmp_path):
    seen = []
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(429, headers={"Retry-After": "120"}) if request.url.host == "a.example" else httpx.Response(200, json=answer())
    mock_network(monkeypatch, handler)
    configuration = config(endpoint("a"), endpoint("b"), strategy="failover")
    call(tmp_path, configuration)
    call(tmp_path, configuration)
    assert seen == ["a.example", "b.example", "b.example"]
    state = EndpointPool(tmp_path).status(configuration["api_pool"]["endpoints"])
    assert state[0]["cooldown_remaining"] >= 119
    assert state[1]["cooldown_remaining"] == 0


def test_all_cooling_fast_fails_and_reset_restores(monkeypatch, tmp_path):
    seen = []
    def handler(request):
        seen.append(True)
        return httpx.Response(429, headers={"Retry-After": "30"})
    mock_network(monkeypatch, handler)
    configuration = config(endpoint("a"))
    with pytest.raises(PoolError): call(tmp_path, configuration)
    with pytest.raises(PoolError, match="全部冷却"): call(tmp_path, configuration)
    assert len(seen) == 1
    EndpointPool(tmp_path).reset()
    with pytest.raises(PoolError): call(tmp_path, configuration)
    assert len(seen) == 2


def test_weighted_order_and_thread_safe_cursor(tmp_path):
    pool = EndpointPool(tmp_path)
    endpoints = [endpoint("a", weight=2), endpoint("b", weight=1)]
    preferences = validate_settings(config(*endpoints, strategy="weighted")["api_pool"])
    assert [pool.order(endpoints, preferences, "chat")[0]["id"] for _index in range(6)] == ["a", "a", "b", "a", "a", "b"]
    preferences["strategy"] = "round_robin"
    pool.reset()
    with ThreadPoolExecutor(max_workers=6) as workers:
        result = list(workers.map(lambda _index: EndpointPool(tmp_path).order(endpoints, preferences, "chat")[0]["id"], range(20)))
    assert result.count("a") == result.count("b") == 10


def test_vision_and_tool_capability_and_model_mapping(monkeypatch, tmp_path):
    seen = []
    def handler(request):
        seen.append((request.url.host, json.loads(request.content)))
        return httpx.Response(200, json=answer())
    mock_network(monkeypatch, handler)
    configuration = config(endpoint("a", supports_vision=False), endpoint("b", supports_vision=True, model_vision="vision-b"))
    asyncio.run(route({"model": "original", "messages": [{"content": [{"type": "image_url", "image_url": {"url": "data:image/png;base64,AA"}}]}]}, config_data=configuration, data_dir=tmp_path))
    assert seen[0][0] == "b.example"
    assert seen[0][1]["model"] == "vision-b"
    endpoints = endpoints_for(config(endpoint("a", supports_tools=False), endpoint("b")), validate_settings(config(endpoint("a", supports_tools=False), endpoint("b"))["api_pool"]), {"tools": [{}]})
    assert [item["id"] for item in endpoints] == ["b"]


def test_custom_headers_utf8_and_local_key_optional(monkeypatch, tmp_path):
    def handler(request):
        assert request.headers["X-Project"] == "local"
        assert "authorization" not in request.headers
        assert json.loads(request.content)["messages"][0]["content"] == "测试"
        return httpx.Response(200, json=answer())
    mock_network(monkeypatch, handler)
    call(tmp_path, config(endpoint("a", api_key="", headers={"X-Project": "local"})))


def test_invalid_response_retries_and_reasoning_is_valid(monkeypatch, tmp_path):
    counter = []
    def handler(request):
        counter.append(True)
        return httpx.Response(200, json={"choices": []}) if len(counter) == 1 else httpx.Response(200, json={"choices": [{"message": {"reasoning_content": "summary"}}]})
    mock_network(monkeypatch, handler)
    result = call(tmp_path, config(endpoint("a", attempts=2)))
    assert result["choices"][0]["message"]["reasoning_content"] == "summary"


def test_secret_preservation_by_id_after_reorder():
    previous = {"endpoints": [endpoint("a", headers={"X-Key": "secret"}), endpoint("b")]}
    incoming = public_settings(dict(DEFAULTS, endpoints=list(reversed(previous["endpoints"]))))
    assert incoming["endpoints"][1]["headers"] == "[已隐藏]"
    merged = merge_secret_endpoints(incoming, previous)
    assert merged["endpoints"][0]["api_key"] == "b-secret"
    assert merged["endpoints"][1]["api_key"] == "a-secret"
    assert merged["endpoints"][1]["headers"] == {"X-Key": "secret"}
    from utils.storage import strip_hidden_placeholders, sanitize_export
    exported = sanitize_export(previous)
    assert exported["endpoints"][0]["headers"] == "[已隐藏]"
    exported["endpoints"].reverse()
    restored = strip_hidden_placeholders(exported, previous)
    assert restored["endpoints"][0]["api_key"] == "b-secret"


def test_changed_key_resets_health_and_accounts_are_isolated(tmp_path):
    pool = EndpointPool(tmp_path / "first")
    item = endpoint("a")
    pool.record(item, success=False, status=429, preferences=DEFAULTS)
    assert pool.status([item])[0]["cooldown_remaining"] > 0
    assert pool.status([endpoint("a", api_key="new")])[0]["calls"] == 0
    assert EndpointPool(tmp_path / "second").status([item])[0]["calls"] == 0


def test_network_failure_failover_and_disabled_network_retry(monkeypatch, tmp_path):
    seen = []
    def handler(request):
        seen.append(request.url.host)
        if request.url.host == "a.example": raise httpx.ConnectError("private-key-a", request=request)
        return httpx.Response(200, json=answer())
    mock_network(monkeypatch, handler)
    call(tmp_path, config(endpoint("a"), endpoint("b")))
    assert seen == ["a.example", "b.example"]
    with pytest.raises(PoolError) as error:
        call(tmp_path, config(endpoint("a"), endpoint("b"), retry_network_errors=False, strategy="failover"))
    assert "private-key-a" not in str(error.value)


def test_redirect_does_not_forward_credentials(monkeypatch, tmp_path):
    seen = []
    def handler(request):
        seen.append(request.url.host)
        return httpx.Response(302, headers={"Location": "https://elsewhere.example"})
    mock_network(monkeypatch, handler)
    with pytest.raises(PoolError, match="重定向"):
        call(tmp_path, config(endpoint("a")))
    assert seen == ["a.example"]


def test_total_deadline_and_cancel_propagation(monkeypatch, tmp_path):
    async def handler(request):
        await asyncio.sleep(2)
        return httpx.Response(200, json=answer())
    mock_network(monkeypatch, handler)
    with pytest.raises(PoolError, match="总耗时上限"):
        call(tmp_path, config(endpoint("a"), total_timeout_seconds=1))
    async def cancel():
        task = asyncio.create_task(route({"messages": []}, config_data=config(endpoint("a")), data_dir=tmp_path))
        await asyncio.sleep(0.01)
        task.cancel()
        with pytest.raises(asyncio.CancelledError): await task
    asyncio.run(cancel())

def test_real_local_http_failover(monkeypatch, tmp_path):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    received = []
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            received.append((self.path, self.headers.get("Authorization"), payload["model"]))
            code = 402 if self.path.startswith("/first") else 200
            body = json.dumps({"error": "balance"} if code == 402 else answer("local-http-ok")).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    monkeypatch.setattr("services.proxy_config.get_proxy_url", lambda: "")
    first = endpoint("a", base_url=f"http://127.0.0.1:{server.server_port}/first/v1")
    second = endpoint("b", base_url=f"http://127.0.0.1:{server.server_port}/second/v1")
    try:
        result = call(tmp_path, config(first, second, strategy="failover"))
        assert result["choices"][0]["message"]["content"] == "local-http-ok"
        assert received == [("/first/v1/chat/completions", "Bearer a-secret", "model-a"), ("/second/v1/chat/completions", "Bearer b-secret", "model-b")]
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


def test_random_order_has_no_duplicates(monkeypatch, tmp_path):
    monkeypatch.setattr(ai_pool.random, "shuffle", lambda items: items.reverse())
    endpoints = [endpoint("a"), endpoint("b"), endpoint("c")]
    pool = EndpointPool(tmp_path)
    preferences = dict(DEFAULTS, strategy="random")
    assert [item["id"] for item in pool.order(endpoints, preferences, "chat")] == ["c", "b", "a"]
