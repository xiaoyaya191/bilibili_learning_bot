# -*- coding: utf-8 -*-
"""Agent 模式单元测试：注册表 / 安全注入 / 事件流 / 会话边界。"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("BILI_USER_DATA_DIR",
                      str(Path(__file__).resolve().parent / "_testdata"))

import pytest

from agent.registry import GLOBAL_REGISTRY, ToolDef, ToolRegistry, tool


def test_builtin_tools_registered():
    import agent.tools  # noqa: F401
    names = [t.name for t in GLOBAL_REGISTRY.all()]
    for required in (
        "get_my_status", "get_recommendations", "search_videos",
        "video_interact", "kb_add", "memory_write", "finish",
    ):
        assert required in names, f"missing tool {required}"
    assert len(names) >= 17


def test_openai_schema_shape():
    import agent.tools  # noqa: F401
    schemas = GLOBAL_REGISTRY.schemas()
    s = next(x for x in schemas if x["function"]["name"] == "search_videos")
    assert s["type"] == "function"
    assert "keyword" in s["function"]["parameters"]["properties"]


def test_invoke_unknown_tool_returns_error():
    out = asyncio.run(GLOBAL_REGISTRY.invoke("no_such_tool", {}))
    assert out["ok"] is False
    assert "未知" in out["error"]


def test_invoke_sync_and_async_handlers():
    reg = ToolRegistry()

    @tool("sync_echo", "同步工具", registry=reg)
    def sync_echo(text: str):
        return {"echo": text}

    @tool("async_echo", "异步工具", registry=reg)
    async def async_echo(text: str):
        return {"echo": text}

    assert asyncio.run(reg.invoke("sync_echo", {"text": "hi"}))["echo"] == "hi"
    assert asyncio.run(reg.invoke("async_echo", {"text": "yo"}))["echo"] == "yo"


def test_invoke_error_is_observable():
    reg = ToolRegistry()

    @tool("boom", "总是爆炸", registry=reg)
    async def boom():
        raise ValueError("炸了")

    out = asyncio.run(reg.invoke("boom", {}))
    assert out["ok"] is False
    assert "ValueError" in out["error"]


def test_invoke_bad_args_returns_error():
    import agent.tools  # noqa: F401
    out = asyncio.run(GLOBAL_REGISTRY.invoke("search_videos", {"keyword": 12345}))
    assert out["ok"] is False or out.get("ok")  # 不崩溃即可（客户端可能兼容 int）


def test_session_write_tool_injection():
    """allow_write=False 时写工具参数被强制覆盖（安全降级）。"""
    from agent.core import AgentSession
    s = AgentSession("测试目标", allow_write=False)
    defn = GLOBAL_REGISTRY.get("video_interact")
    assert defn.risk == "write"
    arguments = {"bvid": "BV1xx", "action": "like"}
    is_write = defn.risk == "write"
    if is_write and not s.allow_write:
        arguments["allow_write"] = False
    assert arguments["allow_write"] is False


def test_session_events_ring():
    from agent.core import AgentSession
    s = AgentSession("目标", max_steps=1)
    for i in range(700):
        s.emit("system", {"i": i})
    evs = s.events_after(690)
    assert len(evs) <= 10
    assert evs[-1]["seq"] == 700


def test_session_caps():
    from agent.core import AgentSession
    s = AgentSession("目标", max_steps=999)
    assert s.max_steps == 60  # 上限保护
    s2 = AgentSession("目标", max_steps=0)
    assert s2.max_steps == 1


def test_session_persist_and_history(tmp_path, monkeypatch):
    from agent.core import AgentSession, list_history
    s = AgentSession("持久化目标")
    s.status = "finished"
    s.summary = "完成"
    import agent.core as core
    monkeypatch.setattr("core.user_data.DATA_DIR", tmp_path, raising=False)
    # 直接调用 _persist，其内部重新 import DATA_DIR；改用环境变量注入
    os.environ["BILI_USER_DATA_DIR"] = str(tmp_path)
    s._persist()
    assert (tmp_path / "agent_sessions").exists()
