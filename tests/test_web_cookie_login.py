import json


def _allow_web_request(monkeypatch, web_panel):
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])


def test_cookie_parser_accepts_header_and_dict():
    import web_panel

    header = "SESSDATA=session-value; bili_jct=csrf-value; ignored=nope"
    assert web_panel._normalize_bili_cookie_input(header) == {
        "SESSDATA": "session-value",
        "bili_jct": "csrf-value",
    }
    assert web_panel._normalize_bili_cookie_input({
        "DedeUserID": 12345,
        "sid": "sid-value",
        "password": "must-not-pass",
    }) == {"DedeUserID": "12345", "sid": "sid-value"}


def test_cookie_import_rejects_incomplete_credentials(monkeypatch):
    import web_panel

    _allow_web_request(monkeypatch, web_panel)
    response = web_panel.app.test_client().post(
        "/api/bili/cookie", json={"cookie": "SESSDATA=short"}
    )
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_cookie_import_verifies_and_saves_only_whitelisted_values(monkeypatch, tmp_path):
    import web_panel

    _allow_web_request(monkeypatch, web_panel)
    cookie_file = tmp_path / "bilibili_cookies.json"
    monkeypatch.setattr(web_panel, "COOKIE_FILE", cookie_file)

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({"data": {"isLogin": True, "mid": 10001}}).encode()

    captured = []

    def fake_urlopen(request, timeout=0):
        captured.append((request, timeout))
        return FakeResponse()

    monkeypatch.setattr(web_panel, "urlopen", fake_urlopen)
    response = web_panel.app.test_client().post("/api/bili/cookie", json={
        "cookie": "SESSDATA=session-value-long; bili_jct=csrf-value; password=secret-value"
    })
    data = response.get_json()

    assert response.status_code == 200
    assert data == {
        "ok": True,
        "message": "Cookie 验证并导入成功",
        "uid": "10001",
        "cookie_file": str(cookie_file),
    }
    saved = json.loads(cookie_file.read_text(encoding="utf-8"))
    assert saved == {
        "SESSDATA": "session-value-long",
        "bili_jct": "csrf-value",
        "DedeUserID": "10001",
    }
    assert "secret-value" not in json.dumps(data)
    assert captured[0][1] == 10


def test_cookie_login_controls_are_present():
    from pathlib import Path

    html = Path("web_panel.html").read_text(encoding="utf-8-sig")
    assert "导入网页版 Cookie" in html
    assert "importBiliCookie()" in html
    assert "deleteBiliCookie()" in html
    assert "不接收 B 站账号密码" in html
