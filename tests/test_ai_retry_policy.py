import asyncio
import time

import pytest

import brain._brain_ai as ai_module
from brain._brain_ai import BrainAIMixin


def test_consecutive_failures_enter_degraded_mode_without_sleep(monkeypatch):
    brain = BrainAIMixin()
    brain._ai_errors_consecutive = 5
    brain._ai_degraded_until = 0.0
    brain._ai_degraded_logged = False
    brain._ai_using_fallback_provider = False
    brain._ai_fallback_recheck_at = 0.0
    brain._preferred_ai_method = "httpx"
    brain._live_config = lambda: {
        "api_key": "test-key",
        "base_url": "http://127.0.0.1:1/v1",
        "model_brain": "test-model",
        "model_vision": "test-vision",
        "vision_api_key": "test-key",
        "vision_base_url": "http://127.0.0.1:1/v1",
        "fallback_models": {},
        "fallback_model_chat": "",
        "fallback_model_vision": "",
        "fallback_provider_enabled": False,
        "fallback_provider_api_key": "",
        "fallback_provider_base_url": "",
        "fallback_provider_name": "",
        "fallback_provider_models": {},
    }
    brain._get_ai_backends = lambda: ["httpx"]

    async def forbidden_sleep(_seconds):
        raise AssertionError("degraded mode must not block with sleep")

    monkeypatch.setattr(ai_module.asyncio, "sleep", forbidden_sleep)
    started = time.monotonic()
    with pytest.raises(RuntimeError, match="非阻塞降级期"):
        asyncio.run(brain._call_ai_with_retry(messages=[]))

    assert time.monotonic() - started < 0.5
    assert brain._ai_degraded_until > time.time()


def test_balance_error_fast_fails_without_retry_sleep(monkeypatch):
    brain = BrainAIMixin()
    brain._ai_errors_consecutive = 0
    brain._ai_degraded_until = 0.0
    brain._ai_degraded_logged = False
    brain._ai_using_fallback_provider = False
    brain._ai_fallback_recheck_at = 0.0
    brain._preferred_ai_method = "httpx"
    brain._live_config = lambda: {
        "api_key": "test-key", "base_url": "http://127.0.0.1:1/v1",
        "model_brain": "test-model", "model_vision": "test-vision",
        "vision_api_key": "test-key", "vision_base_url": "http://127.0.0.1:1/v1",
        "fallback_models": {}, "fallback_model_chat": "", "fallback_model_vision": "",
        "fallback_provider_enabled": False, "fallback_provider_api_key": "",
        "fallback_provider_base_url": "", "fallback_provider_name": "",
        "fallback_provider_models": {},
    }
    brain._get_ai_backends = lambda: ["httpx"]

    async def balance_error(**_kwargs):
        raise RuntimeError('HTTP 402: {"error":{"message":"Insufficient Balance"}}')

    async def forbidden_sleep(_seconds):
        raise AssertionError("HTTP 402 must not retry or sleep")

    brain._call_ai_via_httpx = balance_error
    monkeypatch.setattr(ai_module.asyncio, "sleep", forbidden_sleep)

    with pytest.raises(RuntimeError, match="余额或配额不足"):
        asyncio.run(brain._call_ai_with_retry(messages=[]))

    assert brain._ai_degraded_until > time.time()
