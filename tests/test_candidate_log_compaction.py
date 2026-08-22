import asyncio
from types import SimpleNamespace

from brain import _brain_loop


class _Brain:
    def __init__(self):
        self.interest_mgr = SimpleNamespace(get_interests=lambda: [])


def test_candidate_log_keeps_only_first_five_details(monkeypatch):
    messages = []
    monkeypatch.setattr(_brain_loop, "log", lambda message, *_args: messages.append(message))
    monkeypatch.setattr("services.interest_engine.InterestEngine", lambda: SimpleNamespace(get_keywords=lambda: []))
    items = [
        {"bvid": f"BV1AA{i:08d}", "title": f"视频 {i}", "owner": {"name": "测试"}}
        for i in range(7)
    ]

    selected = asyncio.run(_brain_loop.select_candidate_video(_Brain(), items))

    assert selected in items
    assert sum(message.startswith(("01.", "02.", "03.", "04.", "05.")) for message in messages) == 5
    assert any("已省略 2 条" in message for message in messages)
