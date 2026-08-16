from copy import deepcopy


def _allow_web_request(monkeypatch, web_panel):
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])


def test_preset_endpoint_reads_nested_api_active_preset(monkeypatch):
    import core.config as core_config
    import web_panel

    _allow_web_request(monkeypatch, web_panel)
    monkeypatch.setattr(core_config, "load_config", lambda: {"api": {"active_preset": "deepseek"}})

    response = web_panel.app.test_client().get("/api/ai/presets")

    assert response.status_code == 200
    assert response.get_json()["active_preset"] == "deepseek"


def test_browse_flow_persists_a_user_selected_candidate_count(monkeypatch):
    import core.config as core_config
    import web_panel

    _allow_web_request(monkeypatch, web_panel)
    state = {"video": {"browse_mode": "direct", "candidate_pool_size": 30}}
    saved = []

    def load_config():
        return deepcopy(state)

    def save_config(value):
        saved.append(deepcopy(value))
        state.clear()
        state.update(deepcopy(value))
        return True

    monkeypatch.setattr(core_config, "load_config", load_config)
    monkeypatch.setattr(core_config, "save_config", save_config)
    response = web_panel.app.test_client().post(
        "/api/bot/browse-flow", json={"browse_mode": "candidate_review", "candidate_pool_size": 35}
    )

    assert response.status_code == 200
    assert response.get_json()["browse_mode"] == "candidate_review"
    assert response.get_json()["candidate_pool_size"] == 35
    assert saved[-1]["video"]["candidate_pool_size"] == 35
