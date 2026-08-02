from __future__ import annotations

import io


def test_critical_balance_failure_is_detected_from_bot_output(monkeypatch):
    import web_panel

    handled = []
    monkeypatch.setattr(web_panel, "_handle_critical_ai_failure", lambda line: handled.append(line))
    monkeypatch.setattr(web_panel, "log_line", lambda _line: None)

    web_panel._bot_reader(io.StringIO('[FATAL_AI_FAILURE] AI account balance HTTP 402\n'))

    assert handled == ['[FATAL_AI_FAILURE] AI account balance HTTP 402']
    assert web_panel._is_critical_ai_failure('HTTP 402: Insufficient Balance')
    assert not web_panel._is_critical_ai_failure('HTTP 429: rate limited')


def test_immediate_bot_stop_skips_the_grace_delay(monkeypatch):
    import web_panel

    class FakeInput:
        closed = False

        def write(self, _value):
            return None

        def flush(self):
            return None

    class FakeProcess:
        stdin = FakeInput()

        def terminate(self):
            self.terminated = True

        def wait(self, timeout):
            return 0

    process = FakeProcess()
    sleeps = []
    monkeypatch.setattr(web_panel, "bot_process", process)
    monkeypatch.setattr(web_panel, "_refresh_bot_state", lambda: True)
    monkeypatch.setattr(web_panel, "log_line", lambda _line: None)
    monkeypatch.setattr(web_panel.time, "sleep", lambda seconds: sleeps.append(seconds))

    web_panel.stop_bot_process(immediate=True)

    assert process.terminated is True
    assert sleeps == []


def test_asr_status_reports_real_local_download_delta(monkeypatch, tmp_path):
    import web_panel

    monkeypatch.setattr(web_panel, "CONFIG_FILE", tmp_path / "config.json")
    model_dir = tmp_path / "asr"
    model_dir.mkdir()
    (model_dir / "existing.txt").write_text("old", encoding="utf-8")
    monkeypatch.setattr(web_panel, "_asr_model_dir", lambda _cfg: model_dir)
    monkeypatch.setattr(web_panel, "_asr_download_job", {
        "state": "running", "phase": "downloading", "message": "loading",
        "started_at": 1.0, "finished_at": None, "initial_files": 1,
        "initial_bytes": 3,
    })
    (model_dir / "model.pt").write_bytes(b"weights")

    payload = web_panel._asr_status_payload()

    assert payload["job"]["downloaded_files"] == 1
    assert payload["job"]["downloaded_bytes"] == len(b"weights")


def test_icon_route_uses_packaged_app_icon(monkeypatch, tmp_path):
    import web_panel

    icon = tmp_path / "app.png"
    icon.write_bytes(b"PNG")
    monkeypatch.setattr(web_panel, "_ICON_FILE", icon)
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])

    response = web_panel.app.test_client().get("/app-icon")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["Cache-Control"] == "no-store, max-age=0"


def test_bili_profile_is_public_and_cookies_are_not_returned(monkeypatch, tmp_path):
    import web_panel

    class FakeResponse:
        def read(self):
            return b'{"code":0,"data":{"mid":123,"uname":"Tester","face":"https://face.example/avatar.png"}}'

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    cookies = tmp_path / "cookies.json"
    cookies.write_text('{"SESSDATA":"secret","bili_jct":"csrf","DedeUserID":"123"}', encoding="utf-8")
    monkeypatch.setattr(web_panel, "COOKIE_FILE", cookies)
    monkeypatch.setattr(web_panel, "_has_valid_bili_cookies", lambda: True)
    monkeypatch.setattr(web_panel, "urlopen", lambda *_args, **_kwargs: FakeResponse())
    web_panel._clear_bili_profile_cache()

    assert web_panel._bili_account_profile() == {
        "uid": "123", "name": "Tester", "face": "https://face.example/avatar.png",
    }
