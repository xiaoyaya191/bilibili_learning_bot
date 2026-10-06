import json
from pathlib import Path

import web_panel
from services.interest_engine import InterestEngine


def test_interest_engine_web_api_persists_the_cli_v2_shape(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    web_panel.app.testing = True

    with web_panel.app.test_client() as client:
        created = client.post(
            "/api/interest-engine/interests",
            json={"keyword": "Python", "weight": "high", "synonyms": ["py", "FastAPI"]},
        )
        assert created.status_code == 200
        body = created.get_json()
        assert body["interests"] == [{
            "keyword": "python",
            "weight": "high",
            "synonyms": ["py", "fastapi"],
            "auto_suggested": False,
        }]

        ai_created = client.post(
            "/api/interest-engine/interests",
            json={"keyword": "LLM", "weight": "medium", "auto_suggested": True},
        )
        assert ai_created.status_code == 200

        compatibility_saved = client.post(
            "/api/interests", json={"interests": ["Python", "LLM"]}
        )
        assert compatibility_saved.status_code == 200
        entries = client.get("/api/interest-engine").get_json()["interests"]
        assert next(item for item in entries if item["keyword"] == "llm")["auto_suggested"] is True

        updated = client.post(
            "/api/interest-engine",
            json={"proxy_mode": "ai_only", "serendipity_rate": 0.25, "use_synonyms": False},
        )
        assert updated.status_code == 200
        assert updated.get_json()["settings"]["proxy_mode"] == "ai_only"
        assert updated.get_json()["settings"]["serendipity_rate"] == 0.25

        excluded = client.post("/api/interest-engine/exclusions", json={"keyword": "spoiler"})
        assert excluded.status_code == 200
        assert excluded.get_json()["negative_keywords"] == ["spoiler"]

    saved = json.loads((tmp_path / "interest_engine.json").read_text(encoding="utf-8"))
    assert saved["interests"][0]["keyword"] == "python"
    assert saved["settings"]["proxy_mode"] == "ai_only"
    assert saved["negative_keywords"] == ["spoiler"]


def test_interest_workspace_template_has_cli_shared_controls():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    for marker in (
        'data-pg="interests"',
        'id="pg-interests"',
        'id="interestKeyword"',
        'id="interestExclusion"',
        'id="interestProxyMode"',
        '/api/interest-engine',
        'function rf_interests()',
    ):
        assert marker in template
    assert 'min-block-size:260px' not in template
    assert '.system-grid .pc{margin:0;min-height:0}' in template
    assert 'id="interestAiProbability"' in template
    assert 'AI 永远不能覆盖或删除手工兴趣' in template


def test_new_interest_profiles_do_not_share_nested_defaults(tmp_path):
    first = InterestEngine(str(tmp_path / "first" / "interest_engine.json"))
    second = InterestEngine(str(tmp_path / "second" / "interest_engine.json"))

    assert first.add_interest("Python", source="manual") is True
    first.settings["ai_suggest"] = True

    assert second.get_keywords() == []
    assert second.settings["ai_suggest"] is False


def test_ai_suggestions_require_a_nonzero_probability_and_preserve_manual_items(tmp_path):
    engine = InterestEngine(str(tmp_path / "interest_engine.json"))
    assert engine.add_interest("Python", weight="high", synonyms=["py"], source="manual") is True

    engine.settings["ai_suggest"] = True
    engine.settings["ai_suggest_probability"] = 0.0
    assert engine.apply_ai_suggestions(["LLM"]) == 0
    assert engine.get_keywords() == ["python"]
    original_python = dict(engine.interests_list[0])

    engine.settings["ai_suggest_probability"] = 0.5
    assert engine.apply_ai_suggestions(["Python", "LLM"]) == 1
    python_item = next(item for item in engine.interests_list if item["keyword"] == "python")
    assert python_item == original_python
    assert engine.get_keywords() == ["python", "llm"]
