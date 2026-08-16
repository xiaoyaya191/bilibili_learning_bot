"""openai 包可选：缺失或版本过旧时自动走 httpx 直连。"""
import asyncio

import services._services_ai as ai_module
from utils.helpers import ensure_ai_marker


def _live_config():
    return {
        "api_key": "test-key",
        "base_url": "http://127.0.0.1:1/v1",
        "model_brain": "test-model",
        "vision_api_key": "",
        "vision_base_url": "",
    }


class _Message:
    content = "hello"
    tool_calls = None


class _Choice:
    message = _Message()


class _Response:
    choices = [_Choice()]


def test_call_ai_raw_uses_httpx_without_openai(monkeypatch):
    called = []

    async def fake_httpx(**_kwargs):
        called.append(True)
        return _Response()

    monkeypatch.setattr(ai_module, "_openai_available", lambda: False)
    monkeypatch.setattr(ai_module, "_call_ai_via_httpx", fake_httpx)
    monkeypatch.setattr(ai_module, "_live_config", _live_config)

    response = asyncio.run(ai_module.call_ai_raw(
        [{"role": "user", "content": "hi"}], verbose=False
    ))
    assert response.choices[0].message.content == "hello"
    assert called


def test_call_ai_with_tools_falls_back_to_httpx(monkeypatch):
    async def fake_raw(**_kwargs):
        return _Response()

    monkeypatch.setattr(ai_module, "_openai_available", lambda: False)
    monkeypatch.setattr(ai_module, "call_ai_raw", fake_raw)
    monkeypatch.setattr(ai_module, "_live_config", _live_config)

    result = asyncio.run(ai_module.call_ai_with_tools(
        [{"role": "user", "content": "hi"}],
        [{"function": {"name": "finalize"}}],
        verbose=False,
        tool_handler=lambda *_args, **_kwargs: "ok",
    ))
    assert result == "hello"


def test_ensure_ai_marker_keeps_empty_reply_empty():
    assert ensure_ai_marker("") == ""
    assert ensure_ai_marker("  ") == ""
