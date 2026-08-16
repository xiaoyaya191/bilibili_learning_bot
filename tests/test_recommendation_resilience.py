import asyncio
import time

import api.client as client_module
from api.client import BiliClient


def _client():
    client = BiliClient()
    client.credential = object()
    return client


def test_recommendations_retry_transient_dns_error(monkeypatch):
    client = _client()
    calls = 0

    async def fake_get_videos(**_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("curl: (28) Resolving timed out after 30083 milliseconds")
        return {"item": [{"bvid": "BV1test"}]}

    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(client_module.homepage, "get_videos", fake_get_videos)
    monkeypatch.setattr(client_module, "_bili_throttle", no_sleep)
    monkeypatch.setattr(client_module.asyncio, "sleep", no_sleep)

    assert asyncio.run(client.get_recommendations()) == [{"bvid": "BV1test"}]
    assert calls == 2


def test_recommendations_use_recent_cache_after_network_failure(monkeypatch):
    client = _client()
    client._recommendation_cache = [{"bvid": "BV1cached"}]
    client._recommendation_cache_ts = time.time()

    async def failing_get_videos(**_kwargs):
        raise RuntimeError("curl: (28) Resolving timed out after 30083 milliseconds")

    async def no_sleep(*_args, **_kwargs):
        return None

    monkeypatch.setattr(client_module.homepage, "get_videos", failing_get_videos)
    monkeypatch.setattr(client_module, "_bili_throttle", no_sleep)
    monkeypatch.setattr(client_module.asyncio, "sleep", no_sleep)

    assert asyncio.run(client.get_recommendations()) == [{"bvid": "BV1cached"}]
