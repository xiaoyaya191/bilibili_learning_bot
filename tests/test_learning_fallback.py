import asyncio

import pytest

import services._services_ai as services_ai
from brain.local_note import build_local_subtitle_note
from persona.managers import BotDiaryManager


def test_local_note_labels_source_material_and_samples_whole_subtitle():
    subtitle = "A" * 2000 + "MIDDLE" + "B" * 2000 + "ENDING"
    note = build_local_subtitle_note(subtitle, "source description", excerpt_chars=900)

    assert "不是 AI 总结" in note
    assert "视频简介（原始材料）" in note
    assert "MIDDLE" in note
    assert "ENDING" in note


@pytest.mark.parametrize("error_text", [
    "plugin_error: empty response after retry",
    "All connection attempts failed",
])
def test_services_ai_gateway_failure_does_not_retry_other_backend(monkeypatch, error_text):
    calls = []

    monkeypatch.setattr(services_ai, "_live_config", lambda: {
        "api_key": "test-key",
        "base_url": "http://127.0.0.1:8080/v1",
        "model_brain": "test-model",
    })

    async def broken_backend(**_kwargs):
        calls.append("openai")
        raise RuntimeError(error_text)

    async def forbidden_backend(**_kwargs):
        calls.append("httpx")
        raise AssertionError("fast-fail errors must not fan out")

    monkeypatch.setattr(services_ai, "_call_ai_via_openai", broken_backend)
    monkeypatch.setattr(services_ai, "_call_ai_via_httpx", forbidden_backend)

    with pytest.raises(RuntimeError, match=error_text):
        asyncio.run(services_ai.call_ai_raw(messages=[{"role": "user", "content": "x"}]))

    assert calls == ["openai"]


def test_diary_list_entries_alias(monkeypatch):
    monkeypatch.setattr(BotDiaryManager, "_load", lambda _self: {
        "diaries": [{"content": "one"}, {"content": "two"}],
    })
    manager = BotDiaryManager({})

    assert manager.list_entries(limit=1) == [{"content": "two"}]
