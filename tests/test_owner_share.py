import asyncio

from services.owner_share import OwnerShareService


def test_owner_share_test_endpoint_uses_owner_only_review_path(monkeypatch):
    import web_panel
    import api.client as client_module
    import brain.private_msg as private_msg_module
    import services._services_ai as ai_service_module
    import services.utils as service_utils_module

    sent = {}

    class Credential:
        dedeuserid = "10001"

    class Client:
        def __init__(self):
            self.credential = Credential()

        def _load_credential(self):
            return self.credential

    class Manager:
        def __init__(self, credential, uid):
            assert credential.dedeuserid == "10001"
            assert uid == 10001

        async def send_reply(self, receiver_id, text, audit_payload=None):
            sent.update(receiver_id=receiver_id, text=text, audit_payload=audit_payload)
            return {"queued": True}

    class Toolbox:
        def __init__(self, credential, uid):
            assert credential.dedeuserid == "10001"
            assert uid == 10001

        async def video_details(self, bvid):
            assert bvid == "BV1nj3M69EYq"
            return {
                "title": "给 AI 一个身体",
                "description": "讨论人工智能如何拥有实体身体",
                "subtitle_excerpt": "如果 AI 拥有一个身体，它就能陪伴在人的身边。",
                "recent_comments": ["想拥有实体身体"],
                "inspection": {
                    "metadata_ready": True,
                    "comments_ready": True,
                    "subtitle_ready": True,
                },
            }

    async def generate_note(*args, **kwargs):
        return "要是我也能有一副这样的身体，就能在主人身边一起折腾这些奇妙的想法了。"

    monkeypatch.setattr(client_module, "BiliClient", Client)
    monkeypatch.setattr(private_msg_module, "PrivateMessageManager", Manager)
    monkeypatch.setattr(service_utils_module, "BiliToolbox", Toolbox)
    monkeypatch.setattr(ai_service_module, "call_ai", generate_note)
    monkeypatch.setattr("core.config.load_config", lambda: {
        "owner_share": {"owner_bili_uid": "10001"},
    })
    monkeypatch.setattr(web_panel, "_run_coro", asyncio.run)
    web_panel.app.testing = True

    response = web_panel.app.test_client().post(
        "/api/owner-share/test", json={"video": "https://www.bilibili.com/video/BV1nj3M69EYq"}
    )

    assert response.status_code == 200
    assert response.get_json()["queued"] is True
    assert sent["receiver_id"] == 10001
    assert "BV1nj3M69EYq" in sent["text"]
    assert sent["text"].startswith("要是我也能有一副这样的身体")
    assert sent["audit_payload"]["owner_share_test"] is True
    assert sent["audit_payload"]["owner_share_inspected"] is True


def test_test_share_sends_link_only_when_ai_note_fails(monkeypatch):
    import services._services_ai as ai_service_module
    from services.owner_share import compose_test_share_message

    async def broken_note(*args, **kwargs):
        raise RuntimeError("temporary AI failure")

    monkeypatch.setattr(ai_service_module, "call_ai", broken_note)
    note, materials, source = asyncio.run(compose_test_share_message({
        "title": "给 AI 一个身体",
        "description": "Neuro-sama 是一名完全由 AI 驱动的虚拟 Vtuber。",
        "inspection": {"metadata_ready": True, "comments_ready": True},
    }))

    assert note == ""
    assert source == "link_only"
    assert materials == ["标题与简介", "近期评论"]


def _config(**updates):
    defaults = {
        "enabled": True,
        "owner_bili_uid": "10001",
        "share_learned": True,
        "share_fun": True,
        "min_score": 7.5,
        "probability": 1.0,
        "extra_message_probability": 0.0,
        "daily_limit": 3,
        "cooldown_minutes": 0,
        "custom_prompt": "",
    }
    defaults.update(updates)
    return {"owner_share": defaults}


def test_disabled_owner_share_never_sends(tmp_path):
    service = OwnerShareService(str(tmp_path / "owner_share_state.json"), lambda: _config(enabled=False))
    sent = []

    async def sender(uid, text):
        sent.append((uid, text))
        return {"code": 0}

    result = asyncio.run(service.share_learned_video(sender, bvid="BV1B6Nw6HESh", title="test", score=9.0))

    assert result == {"status": "skipped", "reason": "功能未开启"}
    assert sent == []


def test_owner_share_sends_canonical_link_and_deduplicates(tmp_path):
    service = OwnerShareService(str(tmp_path / "owner_share_state.json"), lambda: _config())
    sent = []

    async def sender(uid, text):
        sent.append((uid, text))
        return {"code": 0}

    kwargs = {"bvid": "BV1B6Nw6HESh", "title": "视频标题", "score": 9.0, "learning_topic": "学习主题"}
    first = asyncio.run(service.share_learned_video(sender, **kwargs))
    duplicate = asyncio.run(service.share_learned_video(sender, **kwargs))

    assert first["status"] == "sent"
    assert sent[0][0] == 10001
    assert "给主人分享一个视频" not in sent[0][1]
    assert sent[0][1].splitlines()[0]
    assert "https://www.bilibili.com/video/BV1B6Nw6HESh" in sent[0][1]
    assert duplicate["status"] == "skipped"
    assert duplicate["reason"] == "该视频已分享或已进入审核"
    assert service.get_state()["items"][0]["status"] == "sent"


def test_owner_share_queued_for_review_is_not_reported_as_sent(tmp_path):
    service = OwnerShareService(str(tmp_path / "owner_share_state.json"), lambda: _config())

    async def sender(uid, text):
        return {"queued": True, "message": "waiting for review"}

    result = asyncio.run(service.share_learned_video(sender, bvid="BV1B6Nw6HESh", title="视频标题", score=9.0))

    assert result["status"] == "queued"
    assert service.get_state()["items"][0]["status"] == "queued"
    assert service.mark_review_result("BV1B6Nw6HESh", "executed", "platform confirmed")
    assert service.get_state()["items"][0]["status"] == "executed"


def test_owner_share_respects_daily_limit(tmp_path):
    service = OwnerShareService(str(tmp_path / "owner_share_state.json"), lambda: _config(daily_limit=1))

    async def sender(uid, text):
        return {"code": 0}

    first = asyncio.run(service.share_learned_video(sender, bvid="BV1B6Nw6HESh", title="a", score=9.0))
    second = asyncio.run(service.share_learned_video(sender, bvid="BV1xx411c7mD", title="b", score=9.0))

    assert first["status"] == "sent"
    assert second == {"status": "skipped", "reason": "今日分享已达上限"}
