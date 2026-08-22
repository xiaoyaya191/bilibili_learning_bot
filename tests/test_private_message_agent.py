import asyncio
import json

from brain import private_msg
from services import utils as service_utils
from services.local_favorites import add_video
from services.utils import BiliToolbox


def test_private_agent_recognizes_sender_latest_video_request():
    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)

    plan = manager._heuristic_tool_plan("帮我看看我发的最新视频怎么样")

    assert plan["sender_videos"] is True
    assert plan["inspect_sender_latest"] is True
    assert plan["my_videos"] is False
    assert plan["video_search"] == ""


def test_private_agent_uses_real_watch_history_for_recent_video_question():
    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)

    plan = manager._heuristic_tool_plan("你最近刷到啥有意思的视频了")

    assert plan["recent_watched"] is True
    assert plan["recommend_videos"] is False
    assert plan["video_search"] == ""


def test_ai_plan_cannot_disable_required_heuristic_tools(monkeypatch):
    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)

    async def fake_call_ai(**_kwargs):
        return '{"sender_videos":false,"inspect_sender_latest":false,"reason":"no"}'

    monkeypatch.setattr(private_msg, "is_api_configured", lambda: True)
    monkeypatch.setattr("services._services_ai.call_ai", fake_call_ai)

    plan = asyncio.run(manager.plan_tools_for_message(
        {"content": "看看我发的最新视频"}, "没有更早的对话",
    ))

    assert plan["sender_videos"] is True
    assert plan["inspect_sender_latest"] is True


def test_toolbox_inspects_the_latest_sender_upload_and_recent_history():
    class Context:
        def __init__(self):
            self.cached = None

        def set_tool_cache(self, user_id, key, value):
            self.cached = (user_id, key, value)

    class Toolbox(BiliToolbox):
        async def user_videos(self, user_id, limit=5):
            assert str(user_id) == "42"
            return [{"title": "最新投稿", "bvid": "BV1AA1111111"}]

        async def video_details(self, bvid):
            assert bvid == "BV1AA1111111"
            return {"bvid": bvid, "subtitle_excerpt": "视频正文"}

        async def recent_watched(self, limit=8):
            return [{"title": "最近看过的视频"}]

    context = Context()
    toolbox = Toolbox(None, 1, context)
    result = asyncio.run(toolbox.run_plan(
        {"sender_videos": True, "inspect_sender_latest": True, "recent_watched": True},
        "", "42",
    ))

    assert result["sender_latest_video_details"]["subtitle_excerpt"] == "视频正文"
    assert result["recent_watched"][0]["title"] == "最近看过的视频"
    assert context.cached[1] == "last_tool_results"


def test_private_agent_splits_paced_messages_and_can_end_silently(monkeypatch):
    monkeypatch.setattr(private_msg, "ensure_ai_marker", lambda value: value)

    assert private_msg.PrivateMessageManager._split_reply_messages("END") == []
    assert private_msg.PrivateMessageManager._split_reply_messages(
        "我先看一下<NEXT_MESSAGE>字幕里这个观点挺有意思<NEXT_MESSAGE>第三段"
    ) == ["我先看一下", "字幕里这个观点挺有意思", "第三段"]


def test_private_agent_plans_perception_and_explicit_video_actions():
    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)

    perception = manager._heuristic_tool_plan("看看最近评论和私信记录，你学到了什么知识")
    action = manager._heuristic_tool_plan(
        "分析 https://www.bilibili.com/video/BV1AA1111111 然后给这个视频点赞收藏"
    )

    assert perception["recent_comments"] is True
    assert perception["private_history"] is True
    assert perception["knowledge_search"]
    assert action["inspect_video"] == "BV1AA1111111"
    assert action["like_video"] == "BV1AA1111111"
    assert action["favorite_video"] == "BV1AA1111111"
    assert action["coin_video"] == ""


def test_private_agent_flags_social_requests_for_a_second_grounded_decision():
    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)

    plan = manager._heuristic_tool_plan("可以关注我吗？我最近也在做 AI 工具视频")

    assert plan["social_follow_check"] is True
    assert plan["social_target_uid"] == ""


def test_short_burst_merge_only_waits_for_incomplete_chat_fragments():
    assert private_msg.PrivateMessageManager._needs_burst_merge("在吗") is True
    assert private_msg.PrivateMessageManager._needs_burst_merge("在吗？") is False
    assert private_msg.PrivateMessageManager._needs_burst_merge("帮我看看这个视频") is False
    assert private_msg.PrivateMessageManager._needs_burst_merge("BV1AA1111111") is False


def test_short_burst_messages_are_merged_before_ai_processing(monkeypatch):
    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)
    manager._burst_merge_settings = lambda: (True, 0.01)

    async def fake_get_new_messages():
        return [{
            "id": "m2", "talker_id": 42, "sender_uid": 42,
            "sender_name": "Creator", "content": "在干嘛", "image_urls": [],
        }]

    manager.get_new_messages = fake_get_new_messages
    monkeypatch.setattr(private_msg, "log", lambda *_args, **_kwargs: None)

    result = asyncio.run(manager._coalesce_incoming_burst({
        "id": "m1", "talker_id": 42, "sender_uid": 42,
        "sender_name": "Creator", "content": "在吗", "image_urls": [],
    }))

    assert result["content"] == "在吗\n在干嘛"
    assert result["merged_msg_ids"] == ["m1", "m2"]


def test_sender_public_context_includes_profile_uploads_and_dynamics(monkeypatch):
    class FakeUser:
        def __init__(self, _uid, _credential):
            pass

        async def get_user_info(self):
            return {"name": "Creator", "sign": "AI notes", "level": 6}

        async def get_videos(self, ps=3):
            assert ps == 3
            return {"list": {"vlist": [{"title": "Latest Agent", "bvid": "BV1AA1111111"}]}}

        async def get_dynamics_new(self):
            return {"items": [{"modules": {"module_dynamic": {"desc": {"text": "发布了新的上下文方案"}}}}]}

    monkeypatch.setattr(service_utils.user, "User", FakeUser)

    result = asyncio.run(BiliToolbox(None, 1).sender_public_context(42, name_hint="Fallback"))

    assert result["name"] == "Creator"
    assert result["latest_videos"][0]["bvid"] == "BV1AA1111111"
    assert result["latest_dynamics"] == ["发布了新的上下文方案"]


def test_private_agent_uses_memory_sources_for_history_based_recommendations():
    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)

    plan = manager._heuristic_tool_plan("给我推荐几个你看过、收藏过或者写进知识库的视频")

    assert plan["recommend_from_memory"] is True
    assert plan["recent_favorites"] is True
    assert plan["recommend_videos"] is False


def test_private_agent_can_follow_a_creator_space_link_and_interact_with_video():
    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)

    plan = manager._heuristic_tool_plan(
        "关注 https://space.bilibili.com/123456 ，再给 BV1AA1111111 互动一下"
    )

    assert plan["social_follow_check"] is True
    assert plan["social_target_uid"] == "123456"
    assert plan["like_video"] == "BV1AA1111111"
    assert plan["favorite_video"] == "BV1AA1111111"


def test_local_favorites_can_ground_agent_recommendations(tmp_path, monkeypatch):
    monkeypatch.setattr(service_utils, "DATA_DIR", tmp_path)
    add_video("AI 精选", {"bvid": "BV1AA1111111", "title": "Useful Agent", "up": "Creator"}, data_dir=tmp_path)

    rows = asyncio.run(BiliToolbox(None, 1).local_favorites(limit=5))

    assert rows[0]["title"] == "Useful Agent"
    assert rows[0]["folder"] == "AI 精选"


def test_non_owner_social_follow_is_queued_only_after_ai_decision(tmp_path, monkeypatch):
    toolbox = BiliToolbox(None, 1)
    monkeypatch.setattr(service_utils, "DATA_DIR", tmp_path)
    monkeypatch.setattr(toolbox, "is_owner", lambda _talker_id: False)

    async def fake_profile(_uid):
        return {"uid": 42, "name": "Creator", "sign": "AI videos", "latest_videos": [{"title": "Agent"}]}

    async def fake_call_ai(**_kwargs):
        return '{"action":"follow","reason":"对方持续分享相关创作，公开主页内容与当前互动自然匹配。"}'

    monkeypatch.setattr(toolbox, "social_profile", fake_profile)
    monkeypatch.setattr("core.config.load_config", lambda: {
        "private_message": {"agent": {"enabled": True, "allow_social_follow_actions": True}},
        "approval_review": {"enabled": True, "action_types": {"follow_up": True}},
    })
    monkeypatch.setattr("services._services_ai.call_ai", fake_call_ai)

    result = asyncio.run(toolbox.consider_social_relation(
        "可以关注我吗？我最近也在做 AI 工具视频", 42, display_name="Creator",
    ))

    assert result["ok"] is True
    assert result["queued"] is True
    inbox = json.loads((tmp_path / "approval_review_inbox.json").read_text(encoding="utf-8"))
    assert inbox[0]["action_type"] == "follow_up"
    assert inbox[0]["payload"]["uid"] == 42


def test_non_owner_cannot_request_an_unfollow(monkeypatch):
    toolbox = BiliToolbox(None, 1)
    monkeypatch.setattr(toolbox, "is_owner", lambda _talker_id: False)
    monkeypatch.setattr("core.config.load_config", lambda: {
        "private_message": {"agent": {"allow_social_follow_actions": True}},
    })

    result = asyncio.run(toolbox.request_social_relation(
        "unfollow", 42, 42, "请取消关注我", "用户请求取消关注", profile={"name": "Creator"},
    ))

    assert result["ok"] is False
    assert "主人" in result["message"]


def test_agent_can_proactively_queue_a_follow_after_a_valuable_chat(tmp_path, monkeypatch):
    toolbox = BiliToolbox(None, 1)
    monkeypatch.setattr(service_utils, "DATA_DIR", tmp_path)
    monkeypatch.setattr(toolbox, "is_owner", lambda _talker_id: False)

    async def fake_profile(_uid):
        return {"uid": 42, "name": "Creator", "sign": "open source AI", "latest_videos": [{"title": "Agent"}]}

    async def fake_call_ai(**_kwargs):
        return '{"action":"follow","reason":"对方持续分享可验证的开源实践，讨论内容与公开投稿高度一致。"}'

    monkeypatch.setattr(toolbox, "social_profile", fake_profile)
    monkeypatch.setattr("core.config.load_config", lambda: {
        "private_message": {"agent": {
            "enabled": True, "allow_social_follow_actions": True,
            "allow_proactive_social_follow": True, "social_follow_daily_limit": 1,
        }},
        "approval_review": {"enabled": True, "action_types": {"follow_up": True}},
    })
    monkeypatch.setattr("services._services_ai.call_ai", fake_call_ai)

    result = asyncio.run(toolbox.consider_social_relation(
        "你上次提到的上下文存储方案我已经补了测试，这里是实现取舍。", 42,
        context="双方已经连续讨论了视频 Agent 的记忆设计和测试方案。",
        display_name="Creator",
    ))

    assert result["ok"] is True
    assert result["queued"] is True
    assert BiliToolbox._proactive_social_follow_count_today() == 1


def test_recent_watched_reads_real_history_not_only_learning_log(tmp_path, monkeypatch):
    monkeypatch.setattr(service_utils, "DATA_DIR", tmp_path)
    (tmp_path / "history_videos.json").write_text(json.dumps({"videos": [
        {"bvid": "BV1AA1111111", "title": "first", "action": "view", "time": "2026-07-30T10:00:00"},
        {"bvid": "BV1BB2222222", "title": "second", "action": "like", "time": "2026-07-30T10:01:00"},
        {"bvid": "BV1AA1111111", "title": "first", "action": "fav", "time": "2026-07-30T10:02:00"},
    ]}, ensure_ascii=False), encoding="utf-8")

    rows = asyncio.run(BiliToolbox(None, 1).recent_watched(limit=10))

    assert [row["bvid"] for row in rows] == ["BV1AA1111111", "BV1BB2222222"]
    assert rows[0]["action"] == "fav"


def test_platform_action_rejects_non_owner_without_side_effect(monkeypatch):
    toolbox = BiliToolbox(None, 1)
    monkeypatch.setattr(toolbox, "is_owner", lambda _talker_id: False)

    result = asyncio.run(toolbox.request_video_action(
        "video_like", "BV1AA1111111", "requested", "给这个视频点赞", "42"))

    assert result["ok"] is False
    assert "主人" in result["message"]


def test_autonomous_coin_requires_abundant_balance_and_reason(monkeypatch):
    toolbox = BiliToolbox(None, 1)
    monkeypatch.setattr(toolbox, "is_owner", lambda _talker_id: True)
    monkeypatch.setattr(toolbox, "self_status", lambda **_kwargs: asyncio.sleep(0, result={"coin_balance": 12}))
    monkeypatch.setattr("core.config.load_config", lambda: {
        "private_message": {"agent": {"coin_reserve": 5, "coin_abundant_threshold": 50}}
    })

    result = asyncio.run(toolbox.request_video_action(
        "coin", "BV1AA1111111", "看起来还行", "这个视频挺有意思", "42"))

    assert result["ok"] is False
    assert result["coin_balance"] == 12
    assert "保守" in result["message"]


def test_owner_explicit_like_is_queued_when_review_is_enabled(tmp_path, monkeypatch):
    toolbox = BiliToolbox(None, 1)
    monkeypatch.setattr(service_utils, "DATA_DIR", tmp_path)
    monkeypatch.setattr(toolbox, "is_owner", lambda _talker_id: True)
    monkeypatch.setattr(
        toolbox, "self_status",
        lambda **_kwargs: asyncio.sleep(0, result={"coin_balance": 80}),
    )
    monkeypatch.setattr("core.config.load_config", lambda: {
        "private_message": {"agent": {"allow_account_actions": True}},
        "approval_review": {
            "enabled": True,
            "action_types": {"video_like": True},
        },
    })

    result = asyncio.run(toolbox.request_video_action(
        "video_like", "BV1AA1111111", "主人明确要求点赞", "给这个视频点赞", "42"))

    assert result["ok"] is True
    assert result["queued"] is True
    assert "executed" not in result
    inbox = json.loads((tmp_path / "approval_review_inbox.json").read_text(encoding="utf-8"))
    assert inbox[0]["action_type"] == "video_like"
    assert inbox[0]["payload"]["bvid"] == "BV1AA1111111"


def test_owner_explicit_actions_call_platform_only_when_review_is_disabled(monkeypatch):
    calls = []

    class Credential:
        dedeuserid = "10001"

    class FakeVideo:
        def __init__(self, bvid, credential):
            self.bvid = bvid

        async def has_liked(self):
            return False

        async def like(self, status=True):
            calls.append(("video_like", self.bvid, status))

        async def has_favoured(self):
            return False

        async def set_favorite(self, add_media_ids=None):
            calls.append(("favorite", self.bvid, add_media_ids))

        async def pay_coin(self, num=1, like=False):
            calls.append(("coin", self.bvid, num, like))

    async def no_throttle():
        return None

    async def fake_favorite_folders(**_kwargs):
        return {"list": [{"id": 9876}]}

    toolbox = BiliToolbox(Credential(), 1)
    monkeypatch.setattr(toolbox, "is_owner", lambda _talker_id: True)
    monkeypatch.setattr(
        toolbox, "self_status",
        lambda **_kwargs: asyncio.sleep(0, result={"coin_balance": 80}),
    )
    monkeypatch.setattr(service_utils.bili_video, "Video", FakeVideo)
    monkeypatch.setattr("api.throttle._bili_throttle", no_throttle)
    monkeypatch.setattr(
        "bilibili_api.favorite_list.get_video_favorite_list", fake_favorite_folders)
    monkeypatch.setattr("core.config.load_config", lambda: {
        "private_message": {
            "agent": {
                "allow_account_actions": True,
                "coin_reserve": 5,
                "coin_abundant_threshold": 50,
            },
        },
        "approval_review": {"enabled": False},
    })

    cases = [
        ("video_like", "给这个视频点赞"),
        ("favorite", "把这个视频收藏"),
        ("coin", "给这个视频投币"),
    ]
    for action, message in cases:
        result = asyncio.run(toolbox.request_video_action(
            action, "BV1AA1111111", "主人明确指定平台互动", message, "42"))
        assert result["ok"] is True
        assert result["executed"] is True
        assert result.get("queued") is not True

    assert calls == [
        ("video_like", "BV1AA1111111", True),
        ("favorite", "BV1AA1111111", [9876]),
        ("coin", "BV1AA1111111", 1, False),
    ]
