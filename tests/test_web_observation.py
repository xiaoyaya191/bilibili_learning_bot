import web_panel


def _client():
    web_panel.app.testing = True
    client = web_panel.app.test_client()
    with client.session_transaction() as session:
        session["disclaimer_agreed"] = True
        session["panel_authenticated"] = True
    return client


def _configure_local_state(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(web_panel, "BOT_RUNTIME_LOG_FILE", tmp_path / "web_bot_runtime.log")
    monkeypatch.setattr(web_panel, "_refresh_bot_state", lambda: False)
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: tmp_path / "knowledge")


def test_observation_uses_current_runtime_state_and_cached_metadata(tmp_path, monkeypatch):
    _configure_local_state(tmp_path, monkeypatch)
    bvid = "BV1ab411c7mD"
    web_panel.write_json(tmp_path / "bot_runtime_state.json", {
        "video_observation": {
            "bvid": bvid, "title": "Runtime video", "up": "creator",
            "cover": "https://example.test/cover.jpg", "duration": 125,
            "category": "technology", "stage": "reading subtitles",
            "tags": ["AI", "tool"], "score": 8.5,
            "thought": "The subtitle evidence looks useful.",
            "description": "Current recommendation description",
            "view_count": 99,
        }
    })
    web_panel.write_json(tmp_path / "history_videos.json", {"videos": [{
        "bvid": bvid, "title": "Cached video", "action": "view", "score": 7,
    }]})
    web_panel.write_json(tmp_path / "watch_history_metadata.json", {bvid: {
        "description": "Cached public description", "view_count": 1234,
        "like_count": 88, "favorite_count": 12,
    }})
    (tmp_path / "web_bot_runtime.log").write_text("[10:00:00] working\n", encoding="utf-8")

    body = _client().get("/api/observe").get_json()

    assert body["ok"] is True
    assert body["user_awareness"] is False
    observation = body["observation"]
    assert observation["bvid"] == bvid
    assert observation["title"] == "Runtime video"
    assert observation["duration"] == "2:05"
    assert observation["description"] == "Current recommendation description"
    assert observation["view_count"] == 99
    assert observation["like_count"] == 88
    assert observation["favorite_count"] == 12
    assert observation["url"] == f"https://www.bilibili.com/video/{bvid}"
    assert observation["logs"] == ["[10:00:00] working"]


def test_observation_awareness_setting_is_shared_in_config(tmp_path, monkeypatch):
    _configure_local_state(tmp_path, monkeypatch)
    client = _client()

    saved = client.post("/api/observe/settings", json={"user_awareness": True}).get_json()
    loaded = client.get("/api/observe").get_json()

    assert saved == {"ok": True, "user_awareness": True}
    assert loaded["user_awareness"] is True
    assert web_panel.read_json(tmp_path / "config.json", {})["ui"]["observation_user_awareness"] is True


def test_manual_observation_judgment_uses_mocked_ai_without_bilibili_side_effects(tmp_path, monkeypatch):
    _configure_local_state(tmp_path, monkeypatch)
    bvid = "BV1ab411c7mD"
    web_panel.write_json(tmp_path / "bot_runtime_state.json", {"video_observation": {
        "bvid": bvid, "title": "Local metadata only", "stage": "AI judgment",
    }})

    async def fake_call_ai(messages, **kwargs):
        assert messages[0]["role"] == "system"
        assert "Local metadata only" in messages[1]["content"]
        return "8/10. Check the full video before relying on it."

    monkeypatch.setattr("services._services_ai.call_ai", fake_call_ai)
    response = _client().post("/api/observe/force-judge", json={})

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert response.get_json()["answer"].startswith("8/10")
