import json
import re


def _recovery_code(path):
    text = path.read_text(encoding="utf-8")
    match = re.search(r"一次性恢复码:\s*([A-F0-9-]+)", text)
    assert match
    return match.group(1)


def test_setup_creates_rotating_local_recovery_file(monkeypatch, tmp_path):
    import web_panel

    data_dir = tmp_path / "Data"
    config_file = data_dir / "config.json"
    data_dir.mkdir()
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(web_panel, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_panel, "CONFIG_FILE", str(config_file))
    web_panel.app.config.update(TESTING=True, SECRET_KEY="test-secret")

    client = web_panel.app.test_client()
    response = client.post(
        "/api/auth/setup",
        json={"username": "researcher", "password": "normal-password"},
    )
    assert response.status_code == 200
    assert response.get_json()["ok"] is True

    recovery_file = tmp_path / web_panel.RECOVERY_DIR_NAME / web_panel.RECOVERY_FILE_NAME
    assert recovery_file.exists()
    first_code = _recovery_code(recovery_file)
    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert config["web"]["username"] == "researcher"
    assert first_code not in config_file.read_text(encoding="utf-8")

    client.post("/api/auth/logout")
    recovered = client.post(
        "/api/auth/login",
        json={"username": "researcher", "password": first_code},
    )
    assert recovered.get_json()["ok"] is True
    assert recovered.get_json()["recovery"] is True
    second_code = _recovery_code(recovery_file)
    assert second_code != first_code

    client.post("/api/auth/logout")
    reused = client.post(
        "/api/auth/login",
        json={"username": "researcher", "password": first_code},
    )
    assert reused.get_json()["ok"] is False
