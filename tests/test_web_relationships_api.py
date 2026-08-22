# -*- coding: utf-8 -*-
"""tests/test_web_relationships_api.py — B 友画像保存回归测试（P1-9）

回归背景：POST /api/relationships 曾把 body.uid 与位置参数 uid 同时传给
MemoryBank.upsert_contact()，触发 "got multiple values for argument 'uid'"，
导致面板「长期记忆与 B 友画像」保存画像永远失败。
"""
import web_panel
import xingye_bot.state as xingye_state


def _client(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, "DATA_DIR", tmp_path)
    monkeypatch.setattr(xingye_state, "DATA_DIR", tmp_path)
    web_panel.app.testing = True
    return web_panel.app.test_client()


def test_relationships_post_accepts_uid_in_body(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        saved = client.post(
            "/api/relationships",
            json={"uid": "12345678", "name": "测试好友", "chat_style": "喜欢科技"},
        )
        assert saved.status_code == 200
        payload = saved.get_json()
        assert payload["ok"] is True
        assert payload["item"]["uid"] == "12345678"
        assert payload["item"]["name"] == "测试好友"

        listed = client.get("/api/relationships").get_json()
        uids = [str(row.get("uid")) for row in listed["items"]]
        assert "12345678" in uids


def test_relationships_update_and_delete(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        client.post("/api/relationships", json={"uid": "87654321", "name": "初始"})

        updated = client.post(
            "/api/relationships",
            json={"uid": "87654321", "name": "改名", "interest_types": ["科技", "编程"]},
        )
        assert updated.status_code == 200
        item = updated.get_json()["item"]
        assert item["name"] == "改名"
        assert item["interest_types"] == ["科技", "编程"]

        deleted = client.delete("/api/relationships", json={"uid": "87654321"})
        assert deleted.status_code == 200
        listed = client.get("/api/relationships").get_json()
        assert all(str(row.get("uid")) != "87654321" for row in listed["items"])


def test_relationships_post_rejects_missing_uid(tmp_path, monkeypatch):
    with _client(tmp_path, monkeypatch) as client:
        missing = client.post("/api/relationships", json={"name": "无UID"})
        assert missing.status_code == 400
        assert missing.get_json()["ok"] is False
