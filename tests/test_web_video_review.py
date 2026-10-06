import json
from copy import deepcopy
from pathlib import Path

import pytest

from services.video_review import DEFAULTS, VideoReview


@pytest.fixture
def review_api(tmp_path, monkeypatch):
    import core.config as core_config
    import web_panel
    state = {"revisit": dict(deepcopy(DEFAULTS), min_age_hours=0, min_score=0)}
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel.app, "testing", True)
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])
    monkeypatch.setattr(core_config, "load_config", lambda: deepcopy(state))
    monkeypatch.setattr(core_config, "config", deepcopy(state))
    def save(value):
        state.clear()
        state.update(deepcopy(value))
        return True
    monkeypatch.setattr(core_config, "save_config", save)
    (tmp_path / "history_videos.json").write_text(json.dumps({"videos": [{"bvid": "BV1AA00000001", "title": "测试视频", "action": "view", "category": "知识", "score": 9}]}), encoding="utf-8")
    return web_panel.app.test_client(), VideoReview(tmp_path), state


def test_preview_read_only_and_manual_without_enable(review_api):
    client, review, state = review_api
    result = client.get("/api/video-review").get_json()
    assert not result["automatic"]
    assert result["candidate_total"] == 1
    assert review.snapshot() == []
    response = client.post("/api/video-review/run", json={"confirmed": True})
    assert response.get_json()["ok"]
    assert review.snapshot()[0]["status"] == "pending"
    assert not state["revisit"]["enabled"]
    assert client.post("/api/video-review/run", json={"confirmed": True}).status_code == 409


def test_save_validate_confirm_and_disable(review_api):
    client, review, state = review_api
    for body in ([1], {"sources": []}, {"enabled": "true"}, {"unknown": 1}, {"time_windows": ["bad"]}):
        assert client.post("/api/video-review/settings", json=body).status_code == 400
    response = client.post("/api/video-review/settings", json={"enabled": True, "time_windows": ["22:00-01:00"], "categories": ["知识"]})
    assert response.get_json()["ok"]
    assert state["revisit"]["rules_confirmed"]
    assert client.get("/api/video-review").get_json()["automatic"]
    assert client.post("/api/video-review/settings", json={"enabled": False}).get_json()["ok"]
    assert not client.get("/api/video-review").get_json()["automatic"]


def test_cancel_confirmation_and_legacy_entry(review_api):
    client, review, state = review_api
    assert client.post("/api/action/kb-revisit", json={}).status_code == 400
    response = client.post("/api/action/kb-revisit", json={"confirmed": True}).get_json()
    task_id = response["task_id"]
    assert client.post("/api/video-review/cancel", json={"task_id": task_id}).status_code == 400
    assert client.post("/api/video-review/cancel", json={"task_id": task_id, "confirmed": True}).get_json()["ok"]
    assert review.snapshot()[0]["status"] == "cancelled"


def test_manual_invalid_target_and_input(review_api):
    client, review, state = review_api
    for body in ([1], {}, {"confirmed": True, "bvid": "../../secret"}):
        assert client.post("/api/video-review/run", json=body).status_code == 400
    assert client.post("/api/video-review/run", json={"confirmed": True, "bvid": "BV1AA00000009"}).status_code == 409
    assert review.snapshot() == []


def test_review_routes_require_auth(monkeypatch):
    import web_panel
    monkeypatch.setattr(web_panel.app, "testing", False)
    client = web_panel.app.test_client()
    for method, path in (("GET", "/api/video-review"), ("POST", "/api/video-review/settings"), ("POST", "/api/video-review/run"), ("POST", "/api/video-review/cancel")):
        result = client.open(path, method=method)
        assert result.status_code == 401
        assert result.get_json()["auth_required"]


def test_review_partition_queue_priority_and_read_only_pipeline():
    root = Path(__file__).resolve().parents[1]
    html = (root / "web_panel.html").read_text(encoding="utf-8")
    assert 'data-pg="video-review"' in html
    assert 'id="pg-video-review"' in html
    assert 'video-review.js' in html
    source = (root / "brain/_brain_loop.py").read_text(encoding="utf-8")
    assert source.index("queued_target = watch_queue.claim") < source.index("await asyncio.gather(_do_revisit()")
    assert "random.random() >= PROB_REVISIT" not in source
    assert source.index("review_score = score") < source.index("from services.local_favorites import auto_collect_video")
