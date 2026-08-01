import json

import core.config as core_config
import persona.managers as managers
import web_panel


def test_web_diary_entry_is_persisted_and_returned_by_the_diary_api(tmp_path, monkeypatch):
    """The dashboard must write to the same diary file that the bot reads."""
    diary_file = tmp_path / "bot_diary.json"
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(managers, "BOT_DIARY_FILE", str(diary_file))
    web_panel.app.testing = True

    with web_panel.app.test_client() as client:
        created = client.post(
            "/api/diary/entry",
            json={"title": "网页复盘", "content": "已完成一次真实的学习记录。"},
        )
        assert created.status_code == 200
        payload = created.get_json()
        assert payload["ok"] is True
        assert payload["entry"]["source"] == "web_manual"

        diary = client.get("/api/diary")
        assert diary.status_code == 200
        entries = diary.get_json()["diary"]["entries"]
        assert entries[-1]["title"] == "网页复盘"
        assert entries[-1]["content"] == "已完成一次真实的学习记录。"

    on_disk = json.loads(diary_file.read_text(encoding="utf-8"))
    assert on_disk["entries"][-1]["type"] == "manual"


def test_web_diary_entry_can_be_updated_and_deleted(tmp_path, monkeypatch):
    diary_file = tmp_path / "bot_diary.json"
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(managers, "BOT_DIARY_FILE", str(diary_file))
    web_panel.app.testing = True

    with web_panel.app.test_client() as client:
        created = client.post("/api/diary/entry", json={"title": "草稿", "content": "初始内容"}).get_json()
        entry_id = created["entry"]["id"]

        updated = client.put(
            f"/api/diary/entry/{entry_id}",
            json={"title": "修订稿", "content": "修订后的内容"},
        )
        assert updated.status_code == 200
        assert updated.get_json()["entry"]["title"] == "修订稿"

        deleted = client.delete(f"/api/diary/entry/{entry_id}")
        assert deleted.status_code == 200
        assert client.get("/api/diary").get_json()["diary"]["entries"] == []


def test_safety_api_exposes_plaintext_and_encrypted_storage_views(tmp_path, monkeypatch):
    config_path = tmp_path / "config.json"
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config_path)
    monkeypatch.setattr(core_config, "CONFIG_FILE", str(config_path))
    monkeypatch.setattr(core_config, "CIPHER_KEY_FILE", str(tmp_path / ".cipher_key"))
    assert core_config.save_config({"reply_safety": {"enabled": True, "blocked_keywords": ["test-term"]}})
    web_panel.app.testing = True

    with web_panel.app.test_client() as client:
        shown = client.get("/api/behavior/safety").get_json()
        assert shown["enabled"] is True
        assert shown["keywords"] == ["test-term"]
        assert shown["encrypted_keywords"] != shown["keywords"]

        rejected = client.post("/api/behavior/safety/save", json={
            "view": "encrypted", "keywords": shown["encrypted_keywords"],
        })
        assert rejected.status_code == 400
