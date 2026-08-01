import json

from persona import managers


def test_running_persona_manager_refreshes_web_save_and_renders_all_fields(tmp_path, monkeypatch):
    personas_path = tmp_path / "personas.json"
    monkeypatch.setattr(managers, "PERSONAS_FILE", str(personas_path))
    manager = managers.PersonaManager({"persona": {"active_persona": "Default"}})

    (tmp_path / "web_personas.json").write_text(json.dumps({
        "active": "Live",
        "items": {
            "Live": {
                "name": "Live persona",
                "style": "clear",
                "system_prompt": "Use evidence.",
                "owner_prompt": "Keep answers concise.",
                "rules": ["Do not invent facts.", "Respect boundaries."],
            },
        },
    }), encoding="utf-8")

    prompt = manager.build_prompt_block()

    assert manager.get_active_persona() == "Live"
    assert "Live persona" in prompt
    assert "Use evidence." in prompt
    assert "Keep answers concise." in prompt
    assert "Do not invent facts." in prompt
