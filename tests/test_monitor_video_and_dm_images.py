from brain.monitor import MonitorBot
from brain.comment import (
    CommentInteractionManager,
    _is_bili_risk_control,
    _reply_comment_like_probability,
    _safe_platform_error,
)
from brain.private_msg import PrivateMessageManager


def test_at_notification_extracts_bvid_and_av_reference():
    item = {
        "id": "mention-1",
        "item": {"title": "推荐这个视频", "uri": "https://www.bilibili.com/video/av123456"},
        "user": {"nickname": "tester", "mid": 7},
    }

    notification = MonitorBot._at_notification(item)

    assert notification["aid"] == "123456"
    assert notification["user"] == "tester"


def test_at_notification_uses_source_id_as_comment_reply_target():
    """source_id 是真实评论 rpid（大数字），business_id 只是业务类型号（1/12等）"""
    notification = MonitorBot._at_notification({
        "id": "at-1",
        "item": {"subject_id": 123, "business_id": 1, "source_id": 301563030896},
        "user": {"nickname": "tester", "mid": 7},
    })

    assert notification["aid"] == 123
    assert notification["comment_id"] == 301563030896


def test_private_message_image_payload_is_not_discarded():
    manager = object.__new__(PrivateMessageManager)
    text, urls = manager._message_payload({
        "content": '{"url":"https://i0.hdslb.com/bfs/image/test.jpg","height":720}'
    })

    assert text == "[用户发送了一张图片]"
    assert urls == ["https://i0.hdslb.com/bfs/image/test.jpg"]


def test_private_message_text_and_image_are_kept_together():
    manager = object.__new__(PrivateMessageManager)
    text, urls = manager._message_payload({
        "content": '{"content":"这张图是什么？","image_url":"https://i0.hdslb.com/bfs/image/test.png"}'
    })

    assert text == "这张图是什么？"
    assert urls == ["https://i0.hdslb.com/bfs/image/test.png"]


def test_private_message_history_check_prevents_replaying_sent_images():
    manager = object.__new__(PrivateMessageManager)
    manager.log_data = {"history": [{"msg_id": 123, "sent": True}]}

    assert manager._has_history_entry(123) is True
    assert manager._has_history_entry(456) is False


def test_reply_notification_becomes_a_forced_conversation_reply():
    parsed = CommentInteractionManager._reply_notification_to_comment({
        "id": 12,
        "reply_time": 100,
        "user": {"mid": 7, "nickname": "tester"},
        "item": {
            "business": "评论", "subject_id": 123, "source_id": 456,
            "root_id": 400, "source_content": "接着说说这个观点",
            "root_reply_content": "原来的讨论", "target_reply_content": "收到的旧回复",
        },
    })

    assert parsed["id"] == 456
    assert parsed["aid"] == 123
    assert parsed["root_id"] == 400
    assert parsed["parent_id"] == 456
    assert parsed["force_reply"] is True
    assert parsed["thread_context"] == "原来的讨论\n收到的旧回复"


def test_reply_notifications_are_not_filtered_by_monitor_start_time():
    parsed = CommentInteractionManager._reply_notification_to_comment({
        "reply_time": 1,
        "user": {"mid": 7, "nickname": "tester"},
        "item": {
            "business": "评论", "subject_id": 123, "source_id": 456,
            "root_id": 400, "source_content": "重启前发出的续聊",
        },
    })

    assert parsed["time"] == 1
    assert parsed["force_reply"] is True


def test_platform_html_error_is_condensed_for_logs():
    message = _safe_platform_error("网络错误，状态码：412 - <!DOCTYPE html><html>huge page</html>")

    assert message == "B站安全风控（HTTP 412），本轮跳过并将在后续轮询重试"
    assert _is_bili_risk_control("网络错误，状态码：412") is True


def test_reply_comment_like_probability_is_clamped(monkeypatch):
    import brain.comment as comment_module

    monkeypatch.setattr(comment_module, "config", {"interaction": {"prob_reply_comment_like": 3}})
    assert _reply_comment_like_probability() == 1.0
    monkeypatch.setattr(comment_module, "config", {"interaction": {"prob_reply_comment_like": -1}})
    assert _reply_comment_like_probability() == 0.0


def test_comment_thread_memory_keeps_first_question_and_recent_turns(monkeypatch):
    manager = object.__new__(CommentInteractionManager)
    manager.comment_log = {"conversations": {}}
    manager._save_comment_log = lambda: None
    comment_data = {"aid": 1, "root_id": 2, "id": 3, "user_id": 4}

    manager.record_comment_turn(comment_data, "user", "第一个问题是什么？", "u1")
    manager.record_comment_turn(comment_data, "assistant", "第一个回答", "a1")
    manager.record_comment_turn(comment_data, "user", "继续解释一下", "u2")
    prompt = manager.comment_conversation_prompt(comment_data)

    assert "【首条用户问题】第一个问题是什么？" in prompt
    assert "助手: 第一个回答" in prompt
    assert "用户: 继续解释一下" in prompt


def test_comment_thread_memory_keeps_up_to_one_thousand_turns():
    manager = object.__new__(CommentInteractionManager)
    manager.comment_log = {"conversations": {}}
    manager._save_comment_log = lambda: None
    comment_data = {"aid": 1, "root_id": 2, "id": 3, "user_id": 4}

    for index in range(1001):
        manager.record_comment_turn(comment_data, "user", f"第 {index} 条", f"u{index}")

    thread = manager.comment_log["conversations"][manager._conversation_key(comment_data)]
    assert len(thread["turns"]) == 1000
    assert thread["first_user_message"] == "第 0 条"
