# -*- coding: utf-8 -*-
"""tests/test_mini_goal_pool.py — 目标池（计划清单）CRUD 与消费逻辑测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _isolate(tmp_path, monkeypatch):
    """把 mini_goal 的三个存储重定向到临时目录。"""
    from services import mini_goal
    from utils.storage import JsonStore
    monkeypatch.setattr(mini_goal, "_state_store", JsonStore(tmp_path / "mini_goal_state.json"))
    monkeypatch.setattr(mini_goal, "_history_store", JsonStore(tmp_path / "goal_history.json"))
    monkeypatch.setattr(mini_goal, "_pool_store", JsonStore(tmp_path / "goal_pool.json"))
    return mini_goal


def test_pool_crud_roundtrip(tmp_path, monkeypatch):
    mg = _isolate(tmp_path, monkeypatch)
    assert mg.list_pool() == []
    item = mg.add_pool_goal("Python 装饰器", category="编程", duration_minutes=45)
    assert item["topic"] == "Python 装饰器"
    assert item["duration_minutes"] == 45
    assert len(mg.list_pool()) == 1

    updated = mg.update_pool_goal(item["id"], {"duration_minutes": 90, "category": "Python"})
    assert updated["duration_minutes"] == 90
    assert updated["category"] == "Python"

    assert mg.delete_pool_goal(item["id"]) is True
    assert mg.list_pool() == []
    assert mg.delete_pool_goal(item["id"]) is False


def test_pool_add_rejects_empty_topic(tmp_path, monkeypatch):
    mg = _isolate(tmp_path, monkeypatch)
    try:
        mg.add_pool_goal("   ")
    except ValueError:
        pass
    else:
        raise AssertionError("empty topic should raise ValueError")


def test_update_pool_goal_missing_id(tmp_path, monkeypatch):
    mg = _isolate(tmp_path, monkeypatch)
    assert mg.update_pool_goal("no_such_id", {"topic": "x"}) is None


def test_pop_pool_goal_fifo(tmp_path, monkeypatch):
    mg = _isolate(tmp_path, monkeypatch)
    first = mg.add_pool_goal("第一个目标")
    second = mg.add_pool_goal("第二个目标")
    popped = mg.pop_pool_goal()
    assert popped["id"] == first["id"]
    remaining = mg.list_pool()
    assert len(remaining) == 1
    assert remaining[0]["id"] == second["id"]
    assert mg.pop_pool_goal()["id"] == second["id"]
    assert mg.pop_pool_goal() is None


def test_start_pool_goal_activates_and_removes(tmp_path, monkeypatch):
    mg = _isolate(tmp_path, monkeypatch)
    item = mg.add_pool_goal("基础物理", duration_minutes=30)
    active = mg.start_pool_goal(item["id"])
    assert active is not None
    assert active["topic"] == "基础物理"
    assert active["source"] == "user"
    assert mg.get_active()["topic"] == "基础物理"
    assert mg.list_pool() == []
    assert mg.start_pool_goal(item["id"]) is None


def test_clear_pool(tmp_path, monkeypatch):
    mg = _isolate(tmp_path, monkeypatch)
    mg.add_pool_goal("A")
    mg.add_pool_goal("B")
    assert mg.clear_pool() == 2
    assert mg.list_pool() == []


def test_history_delete_and_clear(tmp_path, monkeypatch):
    mg = _isolate(tmp_path, monkeypatch)
    mg.start_goal("历史目标")
    mg.stop_goal(completed=True)
    assert len(mg.load_history()) == 1
    entry = mg.load_history()[0]
    assert mg.delete_history(entry["topic"], entry["started_at"]) is True
    assert mg.load_history() == []
    assert mg.delete_history(entry["topic"], entry["started_at"]) is False

    mg.start_goal("再来一个")
    mg.stop_goal(completed=False)
    assert mg.clear_history() == 1
    assert mg.load_history() == []
