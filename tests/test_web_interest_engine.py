import json
from pathlib import Path

import web_panel


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
