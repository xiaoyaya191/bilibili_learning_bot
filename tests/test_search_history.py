"""AI 历史搜索模块测试：记录、查询、清空、待执行搜索队列。"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services import search_history as sh
from utils.storage import JsonStore


@pytest.fixture(autouse=True)
def _isolated_stores(tmp_path, monkeypatch):
    """隔离到临时目录：测试绝不能清空/污染开发者的真实搜索历史。"""
    monkeypatch.setattr(sh, "_history_store", JsonStore(tmp_path / "search_history.json"))
    monkeypatch.setattr(sh, "_pending_store", JsonStore(tmp_path / "pending_search.json"))


def _scenario():
    sh.clear_search_history()
    sh.clear_pending_search()


def test_record_and_query():
    _scenario()
    rec = sh.record_search(
        query="向量数据库",
        mode="bilibili",
        trigger="user",
        sources=[{"title": "v1", "url": "https://x", "type": "bilibili"}],
        videos_watched=3,
        status="completed",
        resumed="继续刷视频",
    )
    assert rec["query"] == "向量数据库"
    assert rec["videos_watched"] == 3
    assert rec["status"] == "completed"
    assert rec["id"].startswith("sh_")
    assert rec["display_time"]

    items = sh.get_search_history(limit=10)
    assert len(items) == 1
    assert items[0]["query"] == "向量数据库"
    assert items[0]["resumed"] == "继续刷视频"


def test_latest_first_order():
    _scenario()
    sh.record_search(query="A")
    sh.record_search(query="B")
    items = sh.get_search_history(limit=10)
    assert [i["query"] for i in items] == ["B", "A"]


def test_clear():
    _scenario()
    sh.record_search(query="A")
    sh.record_search(query="B")
    assert sh.clear_search_history() == 2
    assert sh.search_history_count() == 0


def test_pending_queue_lifecycle():
    _scenario()
    # 无待执行搜索时返回 None
    assert sh.pop_pending_search() is None

    item = sh.set_pending_search(query="注意力机制", mode="bilibili", video_count=6)
    assert item["query"] == "注意力机制"
    assert item["id"].startswith("ps_")

    # get 不消耗
    assert sh.get_pending_search()["query"] == "注意力机制"
    # pop 消耗后返回 None
    assert sh.pop_pending_search()["query"] == "注意力机制"
    assert sh.pop_pending_search() is None


def test_pending_video_count_clamped():
    _scenario()
    item = sh.set_pending_search(query="x", video_count=999)
    assert 1 <= item["video_count"] <= 20


def test_deep_dive_signature_has_trigger_and_resumed():
    """deep_dive.run_deep_dive 必须支持 trigger/resumed 以写入历史。"""
    from services.deep_dive import run_deep_dive
    import inspect
    sig = inspect.signature(run_deep_dive)
    assert "trigger" in sig.parameters
    assert "resumed" in sig.parameters


def test_web_panel_exposes_search_history_api():
    """web_panel 必须注册 AI 历史搜索相关 API 路由。"""
    import web_panel
    rules = {str(r) for r in web_panel.app.url_map.iter_rules()}
    assert "/api/search-history" in rules
    assert "/api/search-history/clear" in rules
    assert "/api/search-history/trigger" in rules
    assert "/api/search-history/status" in rules


def test_web_template_has_search_history_section():
    """web_panel.html 必须包含 AI 历史搜索分区。"""
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")
    for marker in (
        'data-pg="search-history"',
        'id="pg-search-history"',
        "searchHistoryInput",
        "triggerSearchHistory",
        "rf_search_history",
        "clearSearchHistory",
        "/api/search-history/trigger",
    ):
        assert marker in template


def test_brain_loop_consumes_pending_search():
    """主循环必须集成待执行搜索的消费逻辑。"""
    src = (Path(__file__).resolve().parents[1] / "brain/_brain_loop.py").read_text(encoding="utf-8")
    assert "pop_pending_search" in src
    assert "run_deep_dive" in src
    assert "resumed" in src