import asyncio
from datetime import datetime


def test_live_ai_config_reads_current_config(monkeypatch):
    import core.config
    from services import _services_ai

    monkeypatch.setattr(core.config, "load_config", lambda: {
        "api": {
            "unified_api_key": "runtime-key",
            "unified_base_url": "https://api.deepseek.example/v1",
            "model_brain": "deepseek-chat",
        }
    })

    live = _services_ai._live_config()
    assert live["base_url"] == "https://api.deepseek.example/v1"
    assert live["model_brain"] == "deepseek-chat"


def test_private_message_platform_rejection_is_not_a_success(monkeypatch):
    import core.config
    from brain import private_msg

    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)
    manager.credential = object()
    monkeypatch.setattr(core.config, "load_config", lambda: {
        "approval_review": {"enabled": False, "action_types": {"private_reply": False}}
    })

    async def _no_throttle():
        return None

    async def _rejected(**_kwargs):
        return {"code": 21047, "message": "platform limit"}

    monkeypatch.setattr(private_msg, "_bili_throttle", _no_throttle)
    monkeypatch.setattr(private_msg.bili_session, "send_msg", _rejected)

    result = asyncio.run(manager.send_reply(42, "test reply"))
    assert result["sent"] is False
    assert result["code"] == 21047


def test_proactive_private_message_is_saved_as_follow_up_context(monkeypatch):
    import core.config
    from brain import private_msg

    class Context:
        def __init__(self):
            self.messages = []
            self.memories = []
            self.profile = {}

        def get_context(self, *_args, **_kwargs):
            return list(self.messages)

        def add_message(self, _uid, role, content, **kwargs):
            self.messages.append({"role": role, "content": content, **kwargs})

        def add_memory(self, _uid, content, **kwargs):
            self.memories.append({"content": content, **kwargs})

        def update_profile(self, _uid, **kwargs):
            self.profile.update(kwargs)

    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)
    manager.credential = object()
    manager.context_db = Context()
    monkeypatch.setattr(core.config, "load_config", lambda: {
        "approval_review": {"enabled": False, "action_types": {"private_reply": False}}
    })

    async def _no_throttle():
        return None

    async def _accepted(**_kwargs):
        return {"code": 0}

    monkeypatch.setattr(private_msg, "_bili_throttle", _no_throttle)
    monkeypatch.setattr(private_msg.bili_session, "send_msg", _accepted)

    message = "《给 AI 一个身体》\nhttps://www.bilibili.com/video/BV1nj3M69EYq"
    result = asyncio.run(manager.send_reply(
        42, message,
        audit_payload={"owner_share": True, "owner_share_bvid": "BV1nj3M69EYq", "owner_share_title": "给 AI 一个身体"},
    ))

    assert result["code"] == 0
    assert manager.context_db.messages[-1]["content"] == message
    assert manager.context_db.messages[-1]["metadata"]["owner_share_bvid"] == "BV1nj3M69EYq"
    assert manager.context_db.memories[-1]["metadata"]["owner_share"] is True


def test_vague_reply_to_shared_video_inspects_the_shared_bvid():
    from brain.private_msg import PrivateMessageManager

    manager = PrivateMessageManager.__new__(PrivateMessageManager)
    plan = manager._heuristic_tool_plan(
        "这是什么？",
        "【最近对话】\n助手: 《给 AI 一个身体》 https://www.bilibili.com/video/BV1nj3M69EYq",
    )

    assert plan["inspect_video"] == "BV1nj3M69EYq"
    assert plan["video_search"] == ""


def test_short_video_request_waits_for_a_follow_up_message():
    from brain.private_msg import PrivateMessageManager

    assert PrivateMessageManager._needs_burst_merge("快看看这个视频") is True


def test_video_inspection_sends_one_contextual_progress_update(monkeypatch):
    from brain import private_msg

    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)
    sent = []

    async def _send(receiver_id, text, **kwargs):
        sent.append((receiver_id, text, kwargs))
        return {"code": 0}

    monkeypatch.setattr(private_msg.random, "choice", lambda values: values[0])
    manager.send_reply = _send

    asyncio.run(manager._send_video_inspection_progress(
        {"talker_id": 42, "_auto_reply_enabled": True},
        {"inspect_video": "BV1nj3M69EYq"},
        "助手: 《给 AI 一个身体》 https://www.bilibili.com/video/BV1nj3M69EYq",
    ))

    assert sent[0][0] == 42
    assert "《给 AI 一个身体》" in sent[0][1]
    assert sent[0][2]["audit_payload"]["progress_bvid"] == "BV1nj3M69EYq"


def test_monitor_backs_off_for_ten_seconds_after_rate_limit(monkeypatch):
    from brain import monitor

    bot = monitor.MonitorBot()
    bot.private_msg_mgr = type("Manager", (), {})()

    async def _limited(**_kwargs):
        raise RuntimeError("code: -509")

    bot.private_msg_mgr.process_new_messages = _limited
    monkeypatch.setattr(monitor, "log", lambda *args, **kwargs: None)

    assert asyncio.run(bot._check_messages()) == 0
    assert bot._rate_limit_until["messages"] is not None
    assert (bot._rate_limit_until["messages"] - datetime.now()).total_seconds() >= 8


def test_monitor_passes_live_reply_controls_to_private_message_manager(monkeypatch):
    from brain import monitor

    bot = monitor.MonitorBot()
    bot.cfg = {"max_replies_per_check": 7, "auto_reply": False}
    captured = {}

    async def _process(_self, **kwargs):
        captured.update(kwargs)
        return 0

    bot.private_msg_mgr = type("Manager", (), {"process_new_messages": _process})()
    monkeypatch.setattr(monitor, "log", lambda *args, **kwargs: None)

    assert asyncio.run(bot._check_messages()) == 0
    assert captured == {"max_replies": 7, "auto_reply": False}
