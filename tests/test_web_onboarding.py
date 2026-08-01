from pathlib import Path


def _allow_web_request(monkeypatch, web_panel):
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])


def test_onboarding_only_auto_opens_for_a_freshly_configured_user(monkeypatch, tmp_path):
    import web_panel

    config_file = Path(tmp_path) / "config.json"
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config_file)
    _allow_web_request(monkeypatch, web_panel)

    web_panel.write_json(config_file, {"web": {"username": "legacy", "password": "hash"}})
    client = web_panel.app.test_client()
    assert client.get("/api/onboarding").get_json() == {
        "ok": True,
        "state": "legacy",
        "auto_show": False,
    }

    web_panel.write_json(config_file, {"web": {"onboarding_state": "pending"}})
    assert client.get("/api/onboarding").get_json()["auto_show"] is True

    skipped = client.post("/api/onboarding", json={"state": "skipped"})
    assert skipped.status_code == 200
    assert skipped.get_json()["auto_show"] is False
    assert client.get("/api/onboarding").get_json()["state"] == "skipped"


def test_log_template_uses_structured_error_detection_for_candidates():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")

    assert "hasErrorTag" in template
    assert "[CANDIDATE]" in template
    assert "log-line.candidate" in template
    assert "panel_onboarding_seen_v2" in template
    assert "/api/onboarding" in template
