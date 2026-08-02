import asyncio
import json
from pathlib import Path

import persona.managers as managers
from persona.managers import BotDiaryManager


def test_auto_diary_persists_local_fallback_when_ai_is_unavailable(tmp_path, monkeypatch):
    diary_file = tmp_path / "bot_diary.json"
    monkeypatch.setattr(managers, "BOT_DIARY_FILE", str(diary_file))
    manager = BotDiaryManager({"api": {}})

    entry = asyncio.run(manager.generate_from_events([
        {"type": "video_processed", "title": "Python 入门", "score": 8.2},
        {"type": "video_skipped", "title": "无关视频", "score": 3.0},
    ], current_mood={"mood": "平静", "energy": 82}))

    saved = json.loads(diary_file.read_text(encoding="utf-8"))
    assert entry["source"] == "local"
    assert entry["title"]
    assert "Python 入门" in entry["content"]
    assert saved["entries"][0]["id"] == entry["id"]


def test_dashboard_quick_actions_use_valid_unquoted_attribute_selectors():
    template = Path(__file__).resolve().parents[1] / "web_panel.html"
    with template.open(encoding="utf-8") as source:
        quick_actions = [line for line in source if line.startswith("actionHtml+=")]

    assert any("[data-pg=reviews]" in line for line in quick_actions)
    assert any("[data-pg=mem]" in line for line in quick_actions)
    assert any("[data-pg=logs]" in line for line in quick_actions)
    assert all('[data-pg=\\"' not in line for line in quick_actions)
