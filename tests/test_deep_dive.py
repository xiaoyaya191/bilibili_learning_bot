import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace

from services import deep_dive
from services import learning_agent


def test_deep_dive_and_agent_await_async_web_search(monkeypatch):
    async def fake_web_search(query, limit=5):
        return [{"title": query, "url": "https://example.com", "snippet": str(limit)}]

    monkeypatch.setitem(sys.modules, "knowledge.web_search", SimpleNamespace(web_search=fake_web_search))

    assert asyncio.run(deep_dive._web_search("topic", limit=3))[0]["title"] == "topic"
    assert asyncio.run(learning_agent._web_search_agent("agent topic", count=4))[0]["snippet"] == "4"


def test_run_deep_research_clamps_source_count_and_writes_manifest(monkeypatch, tmp_path):
    saved_path = tmp_path / "deepdive_topic.md"
    captured = {}

    async def fake_run_deep_dive(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "saved_path": str(saved_path),
            "sources": [{"type": "web", "title": "Source", "url": "https://example.com"}],
            "separate_paths": [str(tmp_path / "separate" / "01_source.md")],
        }

    monkeypatch.setattr(deep_dive, "run_deep_dive", fake_run_deep_dive)

    result = asyncio.run(
        deep_dive.run_deep_research(
            topic="test topic",
            mode="invalid",
            source_count=1,
            custom_prompt="focus on evidence",
            sort_by="invalid",
        )
    )

    assert captured["video_count"] == 12
    assert captured["mode"] == "search"
    assert captured["save_mode"] == "both"
    assert captured["export_formats"] == ["html", "ppt"]
    assert captured["sort_by"] == "default"
    assert "focus on evidence" in captured["custom_prompt"]

    manifest_path = Path(result["research_manifest_path"])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["kind"] == "deep_research"
    assert manifest["requested_source_count"] == 12
    assert manifest["found_source_count"] == 1
    assert manifest["sources"][0]["title"] == "Source"


def test_run_deep_research_clamps_source_count_to_maximum(monkeypatch, tmp_path):
    captured = {}

    async def fake_run_deep_dive(**kwargs):
        captured.update(kwargs)
        return {
            "success": True,
            "saved_path": str(tmp_path / "deepdive_topic.md"),
            "sources": [],
            "separate_paths": [],
        }

    monkeypatch.setattr(deep_dive, "run_deep_dive", fake_run_deep_dive)

    asyncio.run(deep_dive.run_deep_research(topic="test topic", source_count=99))

    assert captured["video_count"] == 40


def test_run_deep_research_returns_failed_deep_dive_result(monkeypatch):
    expected = {"success": False, "error": "upstream failed"}

    async def fake_run_deep_dive(**kwargs):
        return expected

    monkeypatch.setattr(deep_dive, "run_deep_dive", fake_run_deep_dive)

    result = asyncio.run(deep_dive.run_deep_research(topic="test topic"))

    assert result is expected
    assert "research_manifest_path" not in result
