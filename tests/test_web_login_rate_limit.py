# -*- coding: utf-8 -*-
def test_login_is_rate_limited_after_repeated_failures(monkeypatch, tmp_path):
    import web_panel

    data_dir = tmp_path / "Data"
    config_file = data_dir / "config.json"
    data_dir.mkdir()
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(web_panel, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_panel, "CONFIG_FILE", str(config_file))
    web_panel.app.config.update(TESTING=True, SECRET_KEY="test-secret")
    web_panel._LOGIN_ATTEMPTS.clear()

    client = web_panel.app.test_client()
    client.post("/api/auth/setup", json={"username": "researcher", "password": "normal-password"})
    client.post("/api/auth/logout")

    for _ in range(12):
        failed = client.post("/api/auth/login", json={"username": "researcher", "password": "wrong-password"})
        assert failed.status_code in {200, 429}

    limited = client.post("/api/auth/login", json={"username": "researcher", "password": "normal-password"})
    assert limited.status_code == 429
    assert limited.get_json()["ok"] is False

    web_panel._LOGIN_ATTEMPTS.clear()
    success = client.post("/api/auth/login", json={"username": "researcher", "password": "normal-password"})
    assert success.get_json()["ok"] is True
