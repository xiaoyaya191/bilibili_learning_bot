import asyncio
from datetime import datetime
from types import SimpleNamespace

from brain import _brain_session
from core.config import DEFAULT_CONFIG


def test_active_chat_is_disabled_by_default_and_has_an_optional_whitelist():
    active_chat = DEFAULT_CONFIG["active_chat"]
    assert active_chat["enabled"] is False
    assert active_chat["whitelist_enabled"] is False
    assert active_chat["whitelist_uids"] == []


def test_active_chat_does_not_contact_a_user_outside_the_whitelist(monkeypatch):
    session = _brain_session.BrainSessionMixin()
    session._active_chat_count = 0
    session._last_active_chat_at = datetime.min
    session.bili = object()
    session.private_message_mgr = SimpleNamespace(
        get_chat_target=lambda _bili: _async_value({"uid": 1001, "name": "test-user"})
    )
    session._compose_active_chat = lambda *_args: (_ for _ in ()).throw(AssertionError("must not compose"))
    monkeypatch.setitem(_brain_session.config, "active_chat", {
        "enabled": True,
        "prob_initiate": 1.0,
        "cooldown_minutes": 0,
        "max_initiate_per_session": 3,
        "quiet_hours_enabled": False,
        "whitelist_enabled": True,
        "whitelist_uids": ["2002"],
    })
    asyncio.run(session.maybe_initiate_chat())


async def _async_value(value):
    return value
