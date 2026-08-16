import json

from persona import managers


def test_web_persona_is_runtime_authority_and_owner_is_recognized(tmp_path, monkeypatch):
    personas_path = tmp_path / "personas.json"
    web_path = tmp_path / "web_personas.json"
    personas_path.write_text(json.dumps({
        "active_persona": "默认人格",
        "personas": {"默认人格": {"name": "AI小助手", "system_prompt": ""}},
    }, ensure_ascii=False), encoding="utf-8")
    web_path.write_text(json.dumps({
        "active": "AI猫娘",
        "items": {
            "AI猫娘": {
                "name": "AI猫娘",
                "style": "像真人，但承认是AI",
                "system_prompt": "你是UP主测试用户（10001）的AI助手",
            }
        },
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(managers, "PERSONAS_FILE", str(personas_path))

    manager = managers.PersonaManager({"owner_share": {"owner_bili_uid": ""}})

    assert manager.get_active_persona() == "AI猫娘"
    assert "测试用户" in manager.build_prompt_block()
    owner_block = manager.build_relationship_block("10001")
    assert "就是你的主人" in owner_block
    assert "不是陌生人" in owner_block
    assert manager.build_relationship_block("10000") == ""


def test_persona_save_keeps_web_and_runtime_envelopes_in_sync(tmp_path, monkeypatch):
    personas_path = tmp_path / "personas.json"
    monkeypatch.setattr(managers, "PERSONAS_FILE", str(personas_path))
    manager = managers.PersonaManager({"persona": {"active_persona": "默认人格"}})

    manager.add_persona("测试人格", {"name": "测试人格", "system_prompt": "测试提示词"})
    manager.set_active_persona("测试人格")

    runtime = json.loads(personas_path.read_text(encoding="utf-8"))
    web = json.loads((tmp_path / "web_personas.json").read_text(encoding="utf-8"))
    assert runtime["active_persona"] == "测试人格"
    assert web["active"] == "测试人格"
    assert web["items"]["测试人格"]["system_prompt"] == "测试提示词"
