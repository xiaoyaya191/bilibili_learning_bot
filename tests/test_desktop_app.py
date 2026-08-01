import desktop_app


def test_desktop_server_disables_panel_auto_open(monkeypatch):
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured.update(kwargs)
        return object()

    monkeypatch.setattr(desktop_app.subprocess, "Popen", fake_popen)

    desktop_app._start_server()

    assert captured["env"]["BILI_WEB_AUTO_OPEN"] == "0"
    assert captured["env"]["BILI_TRAY_DISABLED"] == "1"


def test_child_streams_are_reconfigured_to_utf8(monkeypatch):
    calls = []

    class Stream:
        def reconfigure(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(desktop_app.sys, "stdout", Stream())
    monkeypatch.setattr(desktop_app.sys, "stderr", Stream())

    desktop_app._configure_child_text_streams()

    assert calls == [
        {"encoding": "utf-8", "errors": "replace"},
        {"encoding": "utf-8", "errors": "replace"},
    ]
