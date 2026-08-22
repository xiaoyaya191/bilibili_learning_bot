import os

import web_panel


def test_launcher_disclaimer_skip_still_requires_browser_acknowledgement(tmp_path, monkeypatch):
    config_file = tmp_path / "config.json"
    config_file.write_text(
        '{"web":{"username":"tester","password":"not-a-real-password"}}',
        encoding="utf-8",
    )
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config_file)
    monkeypatch.setenv("BILI_DISCLAIMER_SKIP", "1")
    web_panel.app.testing = False

    with web_panel.app.test_client() as client:
        response = client.get("/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"].startswith("/disclaimer")
