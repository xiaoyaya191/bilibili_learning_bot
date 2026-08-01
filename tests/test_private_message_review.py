import asyncio

from brain import private_msg


class _Context:
    def __init__(self):
        self.profile = {"consecutive_ai_replies": 0}

    def add_message(self, *args, **kwargs):
        return None

    def add_memory(self, *args, **kwargs):
        return None

    def get_profile(self, *args, **kwargs):
        return dict(self.profile)

    def get_context(self, *args, **kwargs):
        return []

    def conversation_prompt(self, *args, **kwargs):
        return "no previous messages"

    def update_profile(self, *args, **kwargs):
        self.profile.update(kwargs)


class _Safety:
    block_on_incoming = False

    def find_hits(self, text):
        return []

    def detect_injection(self, text):
        return False, []

    def review(self, incoming, outgoing):
        return True, "", []


def test_review_queued_private_message_is_not_logged_as_sent(monkeypatch):
    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)
    manager.log_data = {"history": []}
    manager.context_db = _Context()
    manager.safety_guard = _Safety()
    manager.processed_msg_ids = set()
    manager.last_check_time = None

    async def get_new_messages():
        return [{"id": "m1", "talker_id": 42, "sender_uid": 42, "content": "hello"}]

    async def generate_reply(message):
        return "reply text"

    async def send_reply(receiver_id, reply, **_kwargs):
        return {"queued": True, "message": "waiting for review"}

    manager.get_new_messages = get_new_messages
    manager.generate_reply = generate_reply
    manager.send_reply = send_reply
    manager._should_reply_by_pacing = lambda message: (True, "ok")
    manager._mark_processed = lambda message_id: manager.processed_msg_ids.add(str(message_id))

    monkeypatch.setattr(private_msg, "PRIVATE_MESSAGE_ENABLED", True)
    monkeypatch.setattr(private_msg, "human_reply_delay", lambda: 0)
    original_sleep = asyncio.sleep
    monkeypatch.setattr(private_msg.asyncio, "sleep", lambda seconds: original_sleep(0))
    logs = []
    monkeypatch.setattr(private_msg, "log", lambda message, category=None: logs.append((message, category)))

    processed = asyncio.run(manager.process_new_messages(max_replies=1, auto_reply=True))

    entry = manager.log_data["history"][0]
    assert processed == 1
    assert entry["queued"] is True
    assert entry["sent"] is False
    log_text = "\n".join(message for message, _category in logs)
    assert "私信已接收，开始安全检查" in log_text
    assert "正在交给 AI 处理" in log_text
    assert "AI 已生成私信拟回复" in log_text
    assert "正在发送私信回复" in log_text
    assert "尚未发送" in log_text


def test_private_reply_rewrites_generic_intro_when_history_exists(monkeypatch):
    class _ConversationContext(_Context):
        def get_context(self, *args, **kwargs):
            return [
                {"role": "user", "content": "之前聊过视频"},
                {"role": "assistant", "content": "可以继续说"},
            ]

        def conversation_prompt(self, *args, **kwargs):
            return "用户: 之前聊过视频\n助手: 可以继续说"

    class _PromptBlock:
        def build_prompt_block(self, *args, **kwargs):
            return ""

    manager = private_msg.PrivateMessageManager.__new__(private_msg.PrivateMessageManager)
    manager.context_db = _ConversationContext()
    manager.user_profile_mgr = _PromptBlock()
    manager.persona_mgr = _PromptBlock()
    manager.mood_mgr = _PromptBlock()
    manager.toolbox = type("Toolbox", (), {"run_plan": lambda *args: asyncio.sleep(0, result={})})()
    manager.safety_guard = type(
        "Safety", (), {"detect_leak": lambda *args: (False, [])}
    )()
    manager.previous_seen_at = None

    calls = []

    async def fake_call_ai(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return "我是B站小助手，有什么可以帮你？"
        return "接着聊刚才的视频吧，你想先看哪部分？"

    monkeypatch.setattr("services._services_ai.call_ai", fake_call_ai)
    monkeypatch.setattr(private_msg, "is_api_configured", lambda: False)
    monkeypatch.setattr(private_msg, "ensure_ai_marker", lambda value: value)
    monkeypatch.setattr(private_msg, "log", lambda *args, **kwargs: None)

    reply = asyncio.run(manager.generate_reply({
        "talker_id": "42", "sender_uid": "42", "content": "继续讲讲",
    }))

    assert reply == "接着聊刚才的视频吧，你想先看哪部分？"
    assert len(calls) == 2
