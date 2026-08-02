import json

import web_panel


def _client():
    web_panel.app.testing = True
    client = web_panel.app.test_client()
    with client.session_transaction() as session:
        session["disclaimer_agreed"] = True
        session["panel_authenticated"] = True
    return client


def test_persona_put_migrates_runtime_personas_when_web_file_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "CONFIG_FILE", tmp_path / "config.json")
    web_panel.write_json(tmp_path / "config.json", {"persona": {"active_persona": "默认人格"}})
    web_panel.write_json(tmp_path / "personas.json", {
        "active_persona": "默认人格",
        "personas": {
            "默认人格": {
                "name": "AI小助手",
                "style": "friendly",
                "system_prompt": "old prompt",
                "owner_prompt": "owner preference",
                "rules": ["be helpful"],
            }
        },
    })

    response = _client().put("/api/personas/默认人格", json={
        "name": "AI小助手",
        "style": "natural",
        "system_prompt": "new prompt",
        "owner_prompt": "remember context",
        "rules": ["be factual", "be kind"],
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["ok"] is True
    assert payload["key"] == "AI小助手"

    web = web_panel.read_json(tmp_path / "web_personas.json")
    runtime = web_panel.read_json(tmp_path / "personas.json")
    assert web["active"] == "AI小助手"
    assert web["items"]["AI小助手"]["system_prompt"] == "new prompt"
    assert web["items"]["AI小助手"]["owner_prompt"] == "remember context"
    assert web["items"]["AI小助手"]["rules"] == ["be factual", "be kind"]
    assert runtime["active_persona"] == "AI小助手"
    assert runtime["personas"]["AI小助手"] == web["items"]["AI小助手"]
