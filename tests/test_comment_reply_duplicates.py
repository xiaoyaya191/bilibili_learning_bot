"""Regression tests for comment dedup, empty replies and one-click-three."""
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
    manager.comment_log = {}
    manager.processed_comments = set()
    manager._save_comment_log = lambda: None
    return manager


def test_own_comments_are_not_candidates():
    replies = [
        {"rpid": 1, "member": {"mid": 100}, "ctime": 999},
        {"rpid": 2, "member": {"mid": 100}, "ctime": 999},
        {"rpid": 3, "member": {"mid": 42}, "ctime": 999},
        {"rpid": None, "member": {"mid": 100}, "ctime": 999},
    ]
    candidates = comment_module.CommentInteractionManager._collect_video_comment_candidates(
        replies, aid=7, bvid="BV1xx411c7mD", uid=42, since_ts=0,
        is_processed=lambda _cid: False,
    )
    assert [candidate["id"] for candidate in candidates] == [1, 2]


def test_replied_and_liked_ids_are_loaded_into_processed_set():
    ids = comment_module._processed_ids_from_log({
        "processed_comments": ["1"],
        "replied_comments": [2],
        "liked_comments": [3],
    })
    assert ids == {"1", "2", "3"}


def test_empty_reply_is_rejected_before_send(monkeypatch):
    calls = []

    async def fake_send_comment(**_kwargs):
        calls.append(_kwargs)

    monkeypatch.setattr(comment_module, "public_commenting_enabled", lambda: True)
    monkeypatch.setattr(comment_module, "COMMENT_MODE", "real")
    monkeypatch.setattr(comment_module.comment, "send_comment", fake_send_comment)

    result = asyncio.run(_manager().reply_to_comment(
        None,
        {"id": 1, "aid": 2, "content": "hi", "user": "u"},
        "   ",
    ))

    assert result is False
    assert calls == []


def test_comment_tool_plan_inspects_video_for_summary_mentions():
    plan = comment_module.CommentInteractionManager._comment_tool_plan({
        "content": "能总结这个视频吗？",
        "bvid": "BV1xx411c7mD",
    })
    assert plan["inspect_video"] == "BV1xx411c7mD"


def test_one_click_three_skips_already_done_video():
    manager = _manager()
    manager.comment_log = {
        "three_action_done": {
            "three:BV1xx411c7mD": {
                "date": "2026-08-04", "coin": "ok", "like": "ok", "favorite": "ok",
            }
        }
    }
    result = asyncio.run(manager._one_click_three_for_video(
        {"bvid": "BV1xx411c7mD", "aid": 7}
    ))
    assert result == {"skipped": "already_done"}


def test_one_click_three_can_be_disabled(monkeypatch):
    interaction = comment_module.config.setdefault("interaction", {})
    monkeypatch.setitem(interaction, "comment_reply_three_actions", {"enabled": False})
    result = asyncio.run(_manager()._one_click_three_for_video(
        {"bvid": "BV1xx411c7mD", "aid": 7}
    ))
    assert result == {}
