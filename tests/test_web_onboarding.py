from pathlib import Path


def _allow_web_request(monkeypatch, web_panel):
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])


def test_onboarding_only_auto_opens_for_a_freshly_configured_user(monkeypatch, tmp_path):
    import web_panel

    config_file = Path(tmp_path) / "config.json"
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config_file)
    _allow_web_request(monkeypatch, web_panel)

    web_panel.write_json(config_file, {"web": {"username": "legacy", "password": "hash"}})
    client = web_panel.app.test_client()
    assert client.get("/api/onboarding").get_json() == {
        "ok": True,
        "state": "legacy",
        "auto_show": True,
    }

    web_panel.write_json(config_file, {"web": {"onboarding_state": "pending"}})
    assert client.get("/api/onboarding").get_json()["auto_show"] is True

    skipped = client.post("/api/onboarding", json={"state": "skipped"})
    assert skipped.status_code == 200
    assert skipped.get_json()["auto_show"] is False
    assert client.get("/api/onboarding").get_json()["state"] == "skipped"


def test_log_template_uses_structured_error_detection_for_candidates():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    assert "hasErrorTag" in template
    assert "[CANDIDATE]" in template
    assert "log-line.candidate" in template
    assert "panel_onboarding_seen_v2" in template
    assert "/api/onboarding" in template


def test_first_use_uses_learning_companion_without_a_mode_picker():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    assert "id=\"settingsUseModes\"" not in template
    assert "var _firstUseMode=''" not in template
    assert "学习 + 陪伴" in template
    assert "showDashGuide(true)" in template


def test_onboarding_rejects_missing_mode_and_persists_a_valid_choice(monkeypatch, tmp_path):
    import web_panel
    from services.learning_loop import LearningLoopService

    config_file = Path(tmp_path) / "config.json"
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config_file)
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "_learning_loop", lambda: LearningLoopService(tmp_path / 'learning.sqlite3', tmp_path / 'kb'))
    _allow_web_request(monkeypatch, web_panel)
    client = web_panel.app.test_client()

    accepted = client.post("/api/onboarding", json={"action": "configure", "topic": "Python"})
    assert accepted.status_code == 200

    saved = client.post(
        "/api/onboarding",
        json={"action": "configure", "mode": "learning", "topic": "Python", "level": "systematic"},
    )
    assert saved.status_code == 200
    assert client.get("/api/user-experience").get_json() == {
        "ok": True,
        "mode": "learn_companion",
        "topic": "Python",
        "level": "systematic",
    }


def test_guide_intro_step_round_trip(monkeypatch, tmp_path):
    """教程第一步「查看项目介绍」：POST /api/guide/intro 后 guide-status 应标记完成。"""
    import web_panel

    config_file = Path(tmp_path) / "config.json"
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config_file)
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "COOKIE_FILE", tmp_path / "cookies.json")
    _allow_web_request(monkeypatch, web_panel)

    web_panel.write_json(config_file, {"web": {"username": "u", "password": "h"}})
    client = web_panel.app.test_client()

    status = client.get("/api/guide-status").get_json()
    assert status["ok"] is True
    assert status["steps"]["intro"] is False
    assert status["total"] == 7

    marked = client.post("/api/guide/intro").get_json()
    assert marked["ok"] is True

    status = client.get("/api/guide-status").get_json()
    assert status["steps"]["intro"] is True


def test_guide_status_tolerates_malformed_web_section(monkeypatch, tmp_path):
    """web 节点不是 dict 时 intro 步骤按未完成处理，接口不能 500。"""
    import web_panel

    config_file = Path(tmp_path) / "config.json"
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config_file)
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "COOKIE_FILE", tmp_path / "cookies.json")
    _allow_web_request(monkeypatch, web_panel)

    web_panel.write_json(config_file, {"web": "not-a-dict"})
    client = web_panel.app.test_client()
    status = client.get("/api/guide-status").get_json()
    assert status["ok"] is True
    assert status["steps"]["intro"] is False
