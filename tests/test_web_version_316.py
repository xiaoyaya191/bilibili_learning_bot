from pathlib import Path


def test_release_version_is_316():
    assert Path("VERSION").read_text(encoding="utf-8-sig").strip() == "3.1.6"


def test_info_and_about_render_release_version(monkeypatch):
    import web_panel

    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])
    monkeypatch.setattr(web_panel, "_refresh_bot_state", lambda: False)
    monkeypatch.setattr(web_panel, "_bili_account_profile", lambda: None)
    client = web_panel.app.test_client()

    info = client.get("/api/info")
    assert info.status_code == 200
    assert info.get_json()["version"] == "3.1.6"

    html = Path("web_panel.html").read_text(encoding="utf-8-sig")
    assert "d.version||'版本未知'" in html
    assert "envRow('系统版本',d.version||'-'" in html
