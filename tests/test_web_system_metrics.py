def test_system_metrics_returns_current_values_and_history():
    import web_panel

    previous_testing = web_panel.app.testing
    web_panel.app.testing = True
    try:
        with web_panel.app.test_client() as client:
            response = client.get("/api/system/metrics")
        payload = response.get_json()
    finally:
        web_panel.app.testing = previous_testing

    assert response.status_code == 200
    assert payload["ok"] is True
    assert payload["history"]
    for key in (
        "cpu_percent",
        "memory_percent",
        "disk_percent",
        "asr_enabled",
        "uptime_seconds",
    ):
        assert key in payload["current"]
