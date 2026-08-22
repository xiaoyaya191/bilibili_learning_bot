import json

import web_panel


def _configured_panel(monkeypatch, tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({
        "web": {
            "username": "demo-user",
            "password": web_panel._hash_password("demo-password"),
        }
    }), encoding="utf-8")
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config_path)
    monkeypatch.setattr(web_panel.app, "testing", False)
    return web_panel.app.test_client()


def test_unauthenticated_session_cannot_reach_panel_by_changing_url(monkeypatch, tmp_path):
    client = _configured_panel(monkeypatch, tmp_path)
    with client.session_transaction() as session:
        session["disclaimer_agreed"] = True

    page = client.get("/", follow_redirects=False)
    api = client.get("/api/config", follow_redirects=False)

    assert page.status_code == 302
    assert page.headers["Location"].startswith("/login?next=/")
    assert api.status_code == 401
    assert api.get_json()["auth_required"] is True


def test_authenticated_session_is_not_shown_a_misleading_login_page(monkeypatch, tmp_path):
    client = _configured_panel(monkeypatch, tmp_path)
    with client.session_transaction() as session:
        session["disclaimer_agreed"] = True
        session["panel_authenticated"] = True

    response = client.get("/login?next=/", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["Location"] == "/"
