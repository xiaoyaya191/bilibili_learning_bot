from pathlib import Path

import web_panel


def _client():
    web_panel.app.testing = True
    client = web_panel.app.test_client()
    with client.session_transaction() as session:
        session["disclaimer_agreed"] = True
        session["panel_authenticated"] = True
    return client


def test_watch_history_merges_interactions_and_keeps_view_metadata(tmp_path, monkeypatch):
    kb_dir = tmp_path / "kb"
    kb_dir.mkdir()
    (kb_dir / "[BV1ab411c7mD] - note.md").write_text("# note", encoding="utf-8")
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: kb_dir)
    web_panel.write_json(tmp_path / "history_videos.json", {
        "videos": [
            {
                "bvid": "BV1ab411c7mD", "title": "AI video", "up": "creator",
                "aid": 12, "action": "view", "pic": "https://example.test/cover.jpg",
                "duration": 125, "source": "AI 候选筛选", "result": "AI 筛选通过",
                "interest_reason": "AI", "time": "2026-07-30T10:00:00", "score": 8.5,
            },
            {
                "bvid": "BV1ab411c7mD", "title": "AI video", "up": "creator",
                "aid": 12, "action": "fav", "time": "2026-07-30T10:01:00", "score": 8.5,
            },
        ]
    })

    payload = _client().get("/api/watch-history").get_json()

    assert payload["total"] == 1
    card = payload["items"][0]
    assert card["duration"] == "2:05"
    assert card["archived"] is True
    assert card["cover"] == "https://example.test/cover.jpg"
    assert card["actions"] == ["已浏览", "已收藏"]
    assert card["url"] == "https://www.bilibili.com/video/BV1ab411c7mD"


def test_watch_history_enrichment_caches_public_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: tmp_path / "empty-kb")
    web_panel.write_json(tmp_path / "history_videos.json", {
        "videos": [{
            "bvid": "BV1ab411c7mD", "title": "old", "up": "creator", "action": "like",
            "time": "2026-07-30T10:00:00", "score": 7,
        }]
    })
    monkeypatch.setattr(web_panel, "_fetch_watch_history_metadata", lambda _bvid: {
        "pic": "https://example.test/new.jpg", "duration": 61, "title": "new title", "up": "new up",
    })

    response = _client().post("/api/watch-history/enrich", json={"bvids": ["BV1ab411c7mD"]})

    assert response.status_code == 200
    assert response.get_json()["fetched"] == 1
    saved = web_panel.read_json(tmp_path / "watch_history_metadata.json", {})
    assert saved["BV1ab411c7mD"]["duration"] == 61
    card = _client().get("/api/watch-history").get_json()["items"][0]
    assert card["cover"] == "https://example.test/new.jpg"
    assert card["duration"] == "1:01"


def test_watch_history_filters_and_local_unmatched_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: tmp_path / "empty-kb")
    web_panel.write_json(tmp_path / "history_videos.json", {"videos": [
        {"bvid": "BV1ab411c7mD", "title": "matched", "action": "view", "interest_reason": "AI", "result": "AI 筛选通过", "source": "AI 候选筛选", "time": "2026-07-30T10:00:00"},
        {"bvid": "BV1xx411c7mD", "title": "rejected", "action": "view", "result": "兴趣不匹配，已跳过", "time": "2026-07-30T09:00:00"},
    ]})
    client = _client()

    assert client.get("/api/watch-history?filter=matched").get_json()["total"] == 1
    assert client.get("/api/watch-history?filter=candidate").get_json()["total"] == 1
    assert client.get("/api/watch-history?filter=skipped").get_json()["total"] == 1
    assert client.post("/api/watch-history/remove-unmatched", json={}).status_code == 400
    removed = client.post("/api/watch-history/remove-unmatched", json={"confirmed": True})
    assert removed.get_json()["removed"] == 1
    assert client.get("/api/watch-history").get_json()["total"] == 1


def test_memory_workspace_can_load_more_than_eighty_cards(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: tmp_path / "empty-kb")
    web_panel.write_json(tmp_path / "history_videos.json", {"videos": [
        {
            "bvid": f"BV{i:010d}", "title": f"video {i}", "action": "view",
            "result": "AI 筛选通过", "interest_reason": "AI",
            "time": f"2026-07-30T10:{i % 60:02d}:00",
        }
        for i in range(120)
    ]})

    payload = _client().get("/api/watch-history?limit=120").get_json()

    assert payload["total"] == 120
    assert len(payload["items"]) == 120


def test_watch_history_returns_the_exact_requested_page_size_until_the_last_page(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: tmp_path / "empty-kb")
    web_panel.write_json(tmp_path / "history_videos.json", {"videos": [
        {
            "bvid": f"BV{index:010d}", "title": f"video {index}", "action": "view",
            "time": f"2026-07-30T10:{index % 60:02d}:00",
        }
        for index in range(25)
    ]})
    client = _client()

    first = client.get("/api/watch-history?offset=0&limit=12").get_json()
    second = client.get("/api/watch-history?offset=12&limit=12").get_json()
    last = client.get("/api/watch-history?offset=24&limit=12").get_json()

    assert first["total"] == 25
    assert len(first["items"]) == 12
    assert len(second["items"]) == 12
    assert len(last["items"]) == 1


def test_local_favorite_folders_are_not_bilibili_side_effects(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: tmp_path / "empty-kb")
    web_panel.write_json(tmp_path / "history_videos.json", {"videos": [{
        "bvid": "BV1ab411c7mD", "title": "matched", "action": "view", "interest_reason": "AI", "result": "AI 筛选通过", "time": "2026-07-30T10:00:00",
    }]})
    client = _client()

    created = client.post("/api/favorites/folders", json={"name": "AI 学习"}).get_json()
    folder_id = created["folder"]["id"]
    imported = client.post("/api/favorites/import-history", json={"folder_id": folder_id}).get_json()
    assert imported["added"] == 1
    payload = client.get("/api/favorites").get_json()
    assert payload["folders"][0]["items"][0]["bvid"] == "BV1ab411c7mD"
    removed = client.delete("/api/favorites/items", json={"folder_id": folder_id, "bvid": "BV1ab411c7mD"}).get_json()
    assert removed["removed"] == 1


def test_local_favorite_accepts_video_url_and_hydrates_public_card(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(web_panel, "active_knowledge_base_dir", lambda: tmp_path / "empty-kb")
    monkeypatch.setattr(web_panel, "_fetch_watch_history_metadata", lambda _bvid: {
        "pic": "https://example.test/cover.jpg", "duration": 91,
        "title": "public title", "up": "public up", "category": "technology",
        "view_count": 12345, "like_count": 678, "coin_count": 9, "favorite_count": 42,
    })
    client = _client()
    folder_id = client.post("/api/favorites/folders", json={"name": "Imported"}).get_json()["folder"]["id"]

    response = client.post("/api/favorites/items", json={
        "folder_id": folder_id,
        "bvid": "https://www.bilibili.com/video/BV1ab411c7mD",
        "source": "user import",
    })

    assert response.status_code == 200
    assert response.get_json()["fetched"] == 1
    card = client.get("/api/favorites").get_json()["folders"][0]["items"][0]
    assert card["bvid"] == "BV1ab411c7mD"
    assert card["title"] == "public title"
    assert card["cover"] == "https://example.test/cover.jpg"
    assert card["view_count"] == 12345
    assert card["like_count"] == 678
    assert card["favorite_count"] == 42


def test_comment_log_clear_respects_type_filter(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    web_panel.write_json(tmp_path / "comment_log.json", {
        "items": [
            {"time": "2026-07-30T10:00:00", "action": "incoming", "content": "question", "source": "u1"},
            {"time": "2026-07-30T10:01:00", "action": "reply", "content": "answer", "source": "u1"},
        ],
        "conversations": {
            "comment:1": {"turns": [
                {"time": "2026-07-30T10:02:00", "role": "user", "content": "follow up"},
                {"time": "2026-07-30T10:03:00", "role": "assistant", "content": "follow answer"},
            ]}
        },
    })
    client = _client()

    cleared = client.post("/api/comments/clear", json={"confirmed": True, "period": "all", "kind": "reply"})

    assert cleared.status_code == 200
    assert cleared.get_json()["removed"] == 2
    remaining = client.get("/api/comments?period=all").get_json()["items"]
    assert [row["category"] for row in remaining] == ["incoming", "incoming"]


def test_watch_history_workspace_template_has_real_media_cards():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")
    for marker in (
        'data-pg="watch-history"',
        'id="pg-watch-history"',
        'id="watchHistoryGrid"',
        "/api/watch-history",
        "memHistoryCounts",
        "renderMemHistory(memHistoryCounts)",
        'id="memoryKnowledgeTotal"',
        "/api/watch-history?limit=50",
        "function enrichWatchHistory()",
        "openFavoriteVideoImport",
        "renderWatchHistoryCard",
        "删除本地观看记录",
        "移出本地收藏夹",
        "/api/comments/clear",
        'target="_blank"',
    ):
        assert marker in template


def test_panel_document_is_not_cached():
    response = _client().get("/")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, max-age=0"
    assert response.headers["Pragma"] == "no-cache"


def test_unauthenticated_watch_history_returns_json_instead_of_login_html(monkeypatch):
    web_panel.app.testing = False
    monkeypatch.setattr(web_panel, "CONFIG_FILE", Path(__file__).resolve().parents[1] / "config.example.json")
    client = web_panel.app.test_client()
    response = client.get("/api/watch-history")

    assert response.status_code == 401
    assert response.is_json
    assert response.get_json()["auth_required"] is True
