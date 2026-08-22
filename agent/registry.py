# -*- coding: utf-8 -*-
"""Agent 工具注册表 - 插件市场的地基。

所有 Agent 能力都以"工具"形式注册在这里：B站操作、知识库、记忆、
未来的 QQ/外部项目插件，只要实现同一个 ToolDef 接口并注册进来，
Agent 的大脑就能直接调用，无需改动 Agent Loop 本身。

插件示例：

    from agent.registry import tool

    @tool(name="qq_send_message", description="给指定 QQ 好友发消息",
          risk="write", category="plugin:qq")
    async def qq_send_message(qq: str, text: str) -> dict:
        ...
"""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass, field
from typing import Callable

Handler = Callable[..., object]


@dataclass
class ToolDef:
    """一个可被 Agent 调用的工具。"""

    name: str
    description: str
    handler: Handler
    parameters: dict = field(default_factory=dict)  # JSON Schema
    risk: str = "read"          # read=只读 / write=有副作用
    category: str = "builtin"   # builtin / plugin:<name>
    enabled: bool = True

    def openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters
                or {"type": "object", "properties": {}},
            },
        }


class ToolRegistry:
    """线程安全的工具注册表。"""

    def __init__(self) -> None:
        self._tools: dict = {}
        self._lock = threading.Lock()

    def register(self, defn: ToolDef) -> ToolDef:
        with self._lock:
            self._tools[defn.name] = defn
        return defn

    def unregister(self, name: str) -> bool:
        with self._lock:
            return self._tools.pop(name, None) is not None

    def get(self, name: str):
        return self._tools.get(name)

    def all(self) -> list:
        return [t for t in self._tools.values() if t.enabled]

    def schemas(self, include_write: bool = True) -> list:
        return [
            t.openai_schema()
            for t in self._tools.values()
            if t.enabled and (include_write or t.risk == "read")
        ]

    async def invoke(self, name: str, arguments: dict) -> dict:
        """执行工具；任何异常都转成可观察的错误结果（喂回 LLM 自行调整）。"""
        # 兼容 gpt-oss 等模型的特殊 token 泄漏（如 finish<|channel|>commentary）
        import re as _re
        name = _re.sub(r"<\|[^|]*\|>\w*", "", str(name)).strip() or name
        defn = self._tools.get(name)
        if defn is None or not defn.enabled:
            return {"ok": False, "error": "未知或未启用的工具: " + str(name)}
        try:
            import inspect
            if inspect.iscoroutinefunction(defn.handler):
                out = await defn.handler(**arguments)
            else:
                out = await asyncio.to_thread(defn.handler, **arguments)
            if not isinstance(out, dict):
                out = {"ok": True, "data": out}
            return out
        except TypeError as exc:
            return {"ok": False, "error": "参数不匹配: " + str(exc)}
        except Exception as exc:  # 错误也是观察结果
            return {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}


GLOBAL_REGISTRY = ToolRegistry()


def tool(name, description, *, parameters=None, risk="read",
         category="builtin", registry=None):
    """把函数注册成 Agent 工具的装饰器。"""
    reg = registry or GLOBAL_REGISTRY

    def _wrap(fn):
        reg.register(ToolDef(
            name=name, description=description, handler=fn,
            parameters=parameters or {"type": "object", "properties": {}},
            risk=risk, category=category,
        ))
        return fn

    return _wrap
