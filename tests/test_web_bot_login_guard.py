def test_web_bot_start_requires_completed_bilibili_login(monkeypatch):
    import web_panel

    monkeypatch.setattr(web_panel, "_refresh_bot_state", lambda: False)
    monkeypatch.setattr(web_panel, "_has_valid_bili_cookies", lambda: False)

    ok, message = web_panel.start_bot_process("current")

    assert ok is False
    assert "B站尚未完成登录" in message
