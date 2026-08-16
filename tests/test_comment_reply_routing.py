import asyncio

import brain.comment as comment_module


class _SafetyGuard:
    def review(self, *_args, **_kwargs):
        return True, "", []


def _manager():
    manager = comment_module.CommentInteractionManager.__new__(comment_module.CommentInteractionManager)
    manager.safety_guard = _SafetyGuard()
    manager.credential = object()
    manager.log_interaction = lambda *_args, **_kwargs: None
    manager._mark_user_replied = lambda *_args, **_kwargs: None
    manager.last_reply_failure = {}
    return manager


def test_top_level_comment_reply_omits_parent(monkeypatch):
    calls = []

    async def fake_throttle():
        return None

    async def fake_send_comment(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(comment_module, "public_commenting_enabled", lambda: True)
    monkeypatch.setattr(comment_module, "COMMENT_MODE", "real")
    monkeypatch.setattr(comment_module, "_bili_throttle", fake_throttle)
    monkeypatch.setattr(comment_module.comment, "send_comment", fake_send_comment)
    monkeypatch.setattr(comment_module, "ensure_ai_marker", lambda value: value)

    result = asyncio.run(_manager().reply_to_comment(
        None,
        {"id": 42, "aid": 7, "content": "hello", "user": "tester", "user_id": 9},
        "reply",
    ))

    assert result is True
    assert calls[0]["root"] == 42
    assert calls[0]["parent"] is None


def test_nested_comment_reply_keeps_root_and_parent(monkeypatch):
    calls = []

    async def fake_throttle():
        return None

    async def fake_send_comment(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(comment_module, "public_commenting_enabled", lambda: True)
    monkeypatch.setattr(comment_module, "COMMENT_MODE", "real")
    monkeypatch.setattr(comment_module, "_bili_throttle", fake_throttle)
    monkeypatch.setattr(comment_module.comment, "send_comment", fake_send_comment)
    monkeypatch.setattr(comment_module, "ensure_ai_marker", lambda value: value)

    result = asyncio.run(_manager().reply_to_comment(
        None,
        {
            "id": 42, "aid": 7, "root_id": 10, "parent_id": 42,
            "content": "hello", "user": "tester", "user_id": 9,
        },
        "reply",
    ))

    assert result is True
    assert calls[0]["root"] == 10
    assert calls[0]["parent"] == 42


def test_comment_tool_plan_searches_similar_projects_and_inspects_explicit_video():
    plan = comment_module.CommentInteractionManager._comment_tool_plan({
        "content": "这个项目有类似教程吗？顺便分析 BV1ab411c7mD 的简介和评论区",
    })

    assert plan["inspect_video"] == "BV1ab411c7mD"
    assert plan["video_search"]


def test_comment_tool_plan_uses_current_video_for_description_and_comments():
    plan = comment_module.CommentInteractionManager._comment_tool_plan({
        "content": "能看看这个视频的简介和评论区吗？",
        "bvid": "BV1ab411c7mD",
    })

    assert plan["inspect_video"] == "BV1ab411c7mD"


def test_comment_tool_runner_passes_read_only_plan_to_toolbox(monkeypatch):
    manager = comment_module.CommentInteractionManager.__new__(comment_module.CommentInteractionManager)
    calls = []

    class _Toolbox:
        async def run_plan(self, plan, text, user_id):
            calls.append((plan, text, user_id))
            return {"video_search": [{"title": "similar project"}]}

    manager.toolbox = _Toolbox()
    monkeypatch.setattr(comment_module, "config", {"interaction": {"comment_agent_tools_enabled": True}})
    monkeypatch.setattr(comment_module, "log", lambda *_args, **_kwargs: None)

    plan, results = asyncio.run(manager._run_comment_tools({
        "content": "有没有类似项目推荐？",
        "user": "tester",
        "user_id": 9,
    }))

    assert plan["video_search"]
    assert results["video_search"][0]["title"] == "similar project"
    assert calls[0][1:] == ("有没有类似项目推荐？", 9)
