"""封面显示与同步：https 归一化、历史/实况封面回填优先级。"""
import json
import types

import web_panel


def test_normalize_cover_url():
    assert web_panel._normalize_cover_url("http://i0.hdslb.com/bfs/archive/a.jpg") == "https://i0.hdslb.com/bfs/archive/a.jpg"
    assert web_panel._normalize_cover_url("//i1.hdslb.com/bfs/archive/b.jpg") == "https://i1.hdslb.com/bfs/archive/b.jpg"
    assert web_panel._normalize_cover_url("https://i0.hdslb.com/c.jpg") == "https://i0.hdslb.com/c.jpg"
    assert web_panel._normalize_cover_url("") == ""


def test_watch_history_cards_fill_cover_from_cached_metadata(monkeypatch, tmp_path):
    history = tmp_path / "history_videos.json"
    history.write_text(json.dumps({"videos": [{
        "bvid": "BV1xx411c7mD", "title": "标题", "up": "UP",
        "action": "view", "pic": "", "time": "2026-08-04T00:00:00",
    }]}), encoding="utf-8")
    metadata = tmp_path / "watch_history_metadata.json"
    metadata.write_text(json.dumps({
        "BV1xx411c7mD": {"pic": "//i1.hdslb.com/bfs/archive/new.jpg", "duration": 120},
    }), encoding="utf-8")

    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: tmp_path / "no_kb")
    monkeypatch.setattr(web_panel, "_watch_history_metadata_path", lambda: metadata)

    cards = web_panel._watch_history_cards()
    assert cards
    assert cards[0]["cover"] == "https://i1.hdslb.com/bfs/archive/new.jpg"


def test_video_observation_cover_syncs_with_metadata(monkeypatch, tmp_path):
    runtime = tmp_path / "bot_runtime_state.json"
    runtime.write_text(json.dumps({
        "video_observation": {"bvid": "BV1xx411c7mD", "cover": "", "title": "标题"},
        "activity": {"label": "正在处理"},
    }), encoding="utf-8")
    metadata = tmp_path / "watch_history_metadata.json"
    metadata.write_text(json.dumps({
        "BV1xx411c7mD": {"pic": "http://i0.hdslb.com/bfs/archive/new.jpg", "duration": 100},
    }), encoding="utf-8")

    monkeypatch.setattr(web_panel, "read_json", lambda path, default=None: json.loads(tmp_path.joinpath(path.name).read_text(encoding="utf-8")))
    monkeypatch.setattr(web_panel, "_watch_history_metadata_path", lambda: metadata)
    monkeypatch.setattr(web_panel, "_watch_history_cards", lambda: [])
    monkeypatch.setattr(web_panel, "_refresh_bot_state", lambda: False)
    monkeypatch.setattr(web_panel, "_read_runtime_log", lambda *args, **kwargs: [])
    monkeypatch.setattr(web_panel, "_ensure_observation_cover_backfill", lambda *args, **kwargs: None)

    payload = web_panel._video_observation_payload()
    assert payload["cover"] == "https://i0.hdslb.com/bfs/archive/new.jpg"


def test_ensure_observation_cover_backfill_queues_missing_covers(monkeypatch):
    started = []

    class _Thread:
        def __init__(self, *args, **kwargs):
            started.append((args, kwargs))

        def start(self):
            return None

    monkeypatch.setattr(web_panel, "threading", types.SimpleNamespace(Thread=_Thread))
    monkeypatch.setattr(web_panel, "_cache_watch_history_metadata", lambda *args, **kwargs: (1, 0))
    with web_panel._observation_cover_backfill_lock:
        web_panel._observation_cover_backfill_queued.clear()

    web_panel._ensure_observation_cover_backfill("BV1xx411c7mD", ["", "BV2xx411c7mD", "BV3xx411c7mD"])
    assert started
    args, kwargs = started[0]
    assert kwargs["target"] == web_panel._run_observation_cover_backfill
    assert kwargs["args"][0][0] == "BV1xx411c7mD"
