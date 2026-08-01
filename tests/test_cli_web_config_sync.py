from pathlib import Path
import io


def test_cli_delegates_config_io_to_the_shared_core_layer(monkeypatch):
    import cli.app as cli_app
    import core.config as core_config

    payload = {"video": {"browse_mode": "candidate_review", "candidate_pool_size": 35}}
    saved = []
    monkeypatch.setattr(core_config, "load_config", lambda: payload)
    monkeypatch.setattr(core_config, "save_config", lambda value: saved.append(value) or True)

    assert cli_app.load_config() is payload
    assert cli_app.save_config(payload) is True
    assert saved == [payload]
    assert Path(cli_app.CONFIG_FILE).resolve() == Path(core_config.CONFIG_FILE).resolve()


def test_web_config_endpoint_reads_values_saved_by_the_cli(monkeypatch):
    import cli.app as cli_app
    import core.config as core_config
    import web_panel

    state = {"video": {"browse_mode": "candidate_review", "candidate_pool_size": 35}}
    monkeypatch.setattr(core_config, "load_config", lambda: state)
    monkeypatch.setattr(core_config, "save_config", lambda value: True)
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])

    assert cli_app.save_config(state) is True
    response = web_panel.app.test_client().get("/api/config")

    assert response.status_code == 200
    assert response.get_json()["video"]["candidate_pool_size"] == 35


def test_web_session_limits_share_config_and_validate_completion_action(monkeypatch):
    import core.config as core_config
    import web_panel

    state = {"session": {}}
    monkeypatch.setattr(core_config, "load_config", lambda: state)
    monkeypatch.setattr(core_config, "save_config", lambda value: True)
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])
    client = web_panel.app.test_client()

    response = client.post("/api/bot/session-limits", json={
        "max_videos": 12,
        "max_learned_videos": 4,
        "max_duration_minutes": 90,
        "completion_action": "monitor",
    })

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["max_videos"] == 12
    assert payload["max_learned_videos"] == 4
    assert payload["max_duration_minutes"] == 90
    assert payload["completion_action"] == "monitor"
    assert state["session"]["completion_action"] == "monitor"

    invalid = client.post("/api/bot/session-limits", json={"completion_action": "unknown"})
    assert invalid.status_code == 400


def test_web_bot_reader_hands_completed_session_to_monitor(monkeypatch):
    import web_panel

    started = []
    logs = []
    monkeypatch.setattr(web_panel, "_refresh_bot_state", lambda: False)
    monkeypatch.setattr(
        web_panel, "_start_monitor_process",
        lambda: started.append(True) or (True, "实时监听已启动"),
    )
    monkeypatch.setattr(web_panel, "log_line", logs.append)

    web_panel._bot_reader(io.StringIO("[SESSION] HANDOFF_MONITOR_REQUESTED\n"))

    assert started == [True]
    assert any("切换到实时监听" in line for line in logs)


def test_shared_settings_parser_preserves_the_existing_value_type():
    from cli.app import _flatten_shared_settings, _parse_shared_setting_value, _shared_setting_display, _shared_setting_is_sensitive

    assert _parse_shared_setting_value("否", True) is False
    assert _parse_shared_setting_value("35", 20) == 35
    assert _parse_shared_setting_value('["AI", "科技"]', []) == ["AI", "科技"]
    assert _shared_setting_is_sensitive(("api", "unified_api_key")) is True
    assert _shared_setting_display(("api", "unified_api_key"), "secret") == "<已设置，已隐藏>"
    assert _flatten_shared_settings({"active_preset": "deepseek"}) == [(("active_preset",), "deepseek")]


def test_cli_exposes_the_full_shared_settings_workspace():
    source = (Path(__file__).resolve().parents[1] / "cli" / "app.py").read_text(encoding="utf-8")
    main = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")

    assert "def show_shared_settings_menu" in source
    assert "全部设置（与网页端实时共用 config.json）" in source
    assert 'config.setdefault("reply_safety", {})["enabled"]' in source
    assert "show_shared_settings_menu" in main
    assert 'choice.lower() == "all"' in main
