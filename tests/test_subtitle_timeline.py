import asyncio

import api.subtitles as subtitles
import web_panel


def _client():
    web_panel.app.testing = True
    client = web_panel.app.test_client()
    with client.session_transaction() as session:
        session["disclaimer_agreed"] = True
        session["panel_authenticated"] = True
    return client


def test_cc_timeline_keeps_exact_time_ranges(tmp_path, monkeypatch):
    monkeypatch.setattr(subtitles, "DATA_DIR", tmp_path)
    subtitles._cache_subtitle_timeline("BV1ab411c7mD", "ai-zh", [
        {"from": 1.25, "to": 4.75, "content": "第一条观点"},
        {"from": 65, "to": 67.2, "content": "第二条观点"},
    ])

    timeline = subtitles.get_cached_subtitle_timeline("BV1ab411c7mD")

    assert timeline["track"] == "ai-zh"
    assert timeline["segments"] == [
        {"start": 1.25, "end": 4.75, "start_label": "00:01", "end_label": "00:04", "text": "第一条观点"},
        {"start": 65.0, "end": 67.2, "start_label": "01:05", "end_label": "01:07", "text": "第二条观点"},
    ]


def test_timeline_endpoints_return_cues_and_ai_evidence(monkeypatch):
    timeline = {
        "track": "ai-zh",
        "segments": [
            {"start": 12, "end": 16, "start_label": "00:12", "end_label": "00:16", "text": "视频解释了异步任务的作用。"},
            {"start": 42, "end": 48, "start_label": "00:42", "end_label": "00:48", "text": "这里给出了并发和等待的例子。"},
        ],
    }
    monkeypatch.setattr(web_panel, "_load_timeline_for_web", lambda _bvid, refresh=False: timeline)

    async def fake_call_ai(*_args, **_kwargs):
        return "异步任务的作用在 00:12 - 00:16，例子在 00:42 - 00:48。"

    monkeypatch.setattr("services._services_ai.call_ai", fake_call_ai)
    client = _client()

    loaded = client.get("/api/video/timeline?bvid=BV1ab411c7mD").get_json()
    answered = client.post("/api/video/timeline/answer", json={
        "bvid": "BV1ab411c7mD", "question": "异步任务有什么作用？",
    }).get_json()

    assert loaded["ok"] is True
    assert loaded["total"] == 2
    assert loaded["segments"][0]["start_label"] == "00:12"
    assert answered["ok"] is True
    assert "00:12 - 00:16" in answered["answer"]
    assert answered["evidence"][0]["text"] == "视频解释了异步任务的作用。"


def test_legacy_timeline_backfill_skips_videos_known_to_have_no_cc(tmp_path, monkeypatch):
    bvid = "BV1ab411c7mD"
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "_watch_history_cards", lambda: [{
        "bvid": bvid,
        "score": 9.0,
    }])
    monkeypatch.setattr(subtitles, "get_cached_subtitle_timeline", lambda _bvid: {})
    web_panel.write_json(tmp_path / "subtitle_timeline_backfill.json", {
        bvid: {"status": "unavailable"},
    })

    assert web_panel._scored_timeline_backfill_candidates() == []


def test_timeline_backfill_status_endpoint_is_json(monkeypatch):
    monkeypatch.setattr(web_panel, "_scored_timeline_backfill_candidates", lambda limit=20: [])
    payload = _client().get("/api/video/timeline/backfill").get_json()

    assert payload["ok"] is True
    assert payload["pending"] == 0
    assert "running" in payload
