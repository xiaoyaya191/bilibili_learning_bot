import json


def _prepare(monkeypatch, tmp_path):
    import web_panel

    data_dir = tmp_path / "Data"
    config_file = data_dir / "config.json"
    data_dir.mkdir()
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(web_panel, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_panel, "CONFIG_FILE", str(config_file))
    web_panel._PASSWORD_RESET_ATTEMPTS.clear()
    web_panel.app.config.update(TESTING=True, SECRET_KEY="test-secret")
    return web_panel, config_file, web_panel.app.test_client()


def test_security_question_resets_password_without_storing_answer(monkeypatch, tmp_path):
    web_panel, config_file, client = _prepare(monkeypatch, tmp_path)
    setup = client.post(
        "/api/auth/setup",
        json={
            "username": "researcher",
            "password": "old-password",
            "recovery_question": "你的小学名字是什么？",
            "recovery_answer": "  Example School  ",
        },
    )
    assert setup.get_json()["ok"] is True
    stored = config_file.read_text(encoding="utf-8")
    assert "Example School" not in stored
    assert json.loads(stored)["web"]["recovery_answer"].startswith("$sha256$")

    client.post("/api/auth/logout")
    question = client.post(
        "/api/auth/recovery-question", json={"username": "researcher"}
    )
    assert question.get_json() == {"ok": True, "question": "你的小学名字是什么？"}

    wrong = client.post(
        "/api/auth/reset-password",
        json={"username": "researcher", "answer": "wrong", "password": "new-password"},
    )
    assert wrong.get_json()["ok"] is False

    reset = client.post(
        "/api/auth/reset-password",
        json={
            "username": "researcher",
            "answer": "example school",
            "password": "new-password",
        },
    )
    assert reset.get_json()["ok"] is True
    client.post("/api/auth/logout")
    login = client.post(
        "/api/auth/login",
        json={"username": "researcher", "password": "new-password"},
    )
    assert login.get_json()["ok"] is True


def test_authenticated_user_can_set_custom_security_question(monkeypatch, tmp_path):
    web_panel, config_file, client = _prepare(monkeypatch, tmp_path)
    client.post(
        "/api/auth/setup",
        json={"username": "researcher", "password": "normal-password"},
    )
    response = client.post(
        "/api/auth/security-question",
        json={"question": "我的自定义问题？", "answer": "私密答案"},
    )
    assert response.get_json()["ok"] is True
    web_cfg = json.loads(config_file.read_text(encoding="utf-8"))["web"]
    assert web_cfg["recovery_question"] == "我的自定义问题？"
    assert "私密答案" not in config_file.read_text(encoding="utf-8")


def test_login_page_links_to_forgot_password(monkeypatch, tmp_path):
    _, _, client = _prepare(monkeypatch, tmp_path)
    html = client.get("/login").get_data(as_text=True)
    assert 'href="/forgot-password"' in html
    assert "网页端账号恢复.txt" not in html
    assert "BiliLearn\\账号恢复" not in html
