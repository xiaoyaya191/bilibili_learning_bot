import asyncio
from types import SimpleNamespace

from brain import _brain_loop


class _Brain:
    def __init__(self):
        self.interest_mgr = SimpleNamespace(get_interests=lambda: ["Python"])

    async def _call_ai_with_retry(self, **_kwargs):
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="BV1AA1111111"))]
        )


def test_candidate_selection_deduplicates_bvid_before_ai_selection(monkeypatch):
    monkeypatch.setitem(_brain_loop.config.setdefault("video", {}), "candidate_pool_size", 20)
    class _Engine:
        def get_keywords(self):
            return ["Python"]

        def match(self, **_kwargs):
            return SimpleNamespace(matched_keywords=["Python"])

    monkeypatch.setattr("services.interest_engine.InterestEngine", _Engine)
    items = [
        {"bvid": "BV1AA1111111", "title": "Python 教程", "owner": {"name": "甲"}},
        {"bvid": "BV1AA1111111", "title": "重复项", "owner": {"name": "乙"}},
        {"bvid": "BV1BB2222222", "title": "其他内容", "owner": {"name": "丙"}},
    ]
    selected = asyncio.run(_brain_loop.select_candidate_video(_Brain(), items))
    assert selected["bvid"] == "BV1AA1111111"
