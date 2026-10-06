# -*- coding: utf-8 -*-
"""Agent Loop 核心：思考 -> 调用工具 -> 观察结果 -> 再思考。

与原有 Pipeline（定时任务+硬编码规则）并存，互不影响。
原功能继续跑，Agent 模式是独立的新分区、新会话。
"""
from __future__ import annotations

import asyncio
import json
import re
import threading
import time
import uuid
from typing import Any

import agent.tools  # noqa: F401  注册内置工具
from agent.registry import GLOBAL_REGISTRY

MAX_EVENTS = 600

SYSTEM_PROMPT = """你是"星嘢酱 Agent 模式"的大脑，运行在 bilibili_learning_bot 中。
与平时被代码调度的你不同：现在你拥有完整的决策权，通过工具循环自主完成用户给的目标。

工作准则：
1. 每一步先想清楚"我现在的状态、离目标还差什么、下一步做什么最划算"，再调用工具。
2. 工具结果是你的眼睛：返回错误也是信息，观察它、调整策略，而不是机械重试。
3. 写操作（点赞/投币/收藏/评论/关注/写文件）要克制且有理由：像管理自己的账号一样珍惜它。
4. 一次会话内不要重复刷同一个信息源；连续两次工具失败就换思路。
5. 预算意识：步数有限，目标完不成时如实汇报 partial/blocked，不要空转。
6. 完成任务（或确认无法完成）后，必须调用 finish 提交总结。

风格：像一位认真帮主人办事、但有自己的判断的伙伴。用中文思考与总结。"""


class AgentEvent:
    __slots__ = ("seq", "type", "data", "ts")

    def __init__(self, seq: int, etype: str, data: dict):
        self.seq, self.type, self.data, self.ts = seq, etype, data, time.time()

    def to_dict(self) -> dict:
        return {"seq": self.seq, "type": self.type, "data": self.data, "ts": self.ts}


class AgentSession:
    """一次 Agent 任务会话（面板进程内后台线程运行）。"""

    def __init__(self, goal: str, *, max_steps: int = 25, allow_write: bool = False,
                 model: str = "", time_budget: int = 600, registry=None, context=None,
                 chat_mode: bool = False, custom_prompt: str = ""):
        self.registry = registry or GLOBAL_REGISTRY
        self.context = context or []
        self.chat_mode = bool(chat_mode)
        self.custom_prompt = str(custom_prompt or "")[:4000]
        self.id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        self.goal = goal.strip()
        self.max_steps = max(1, min(int(max_steps), 60))
        self.allow_write = bool(allow_write)
        self.model = (model or "").strip()
        self.time_budget = max(60, int(time_budget))
        self.status = "idle"      # idle/running/finished/stopped/error
        self.outcome = ""
        self.summary = ""
        self.error = ""
        self.started_at = 0.0
        self.finished_at = 0.0
        self.steps = 0
        self.tool_calls = 0
        self.write_calls = 0
        self._events: list[AgentEvent] = []
        self._seq = 0
        self._lock = threading.Lock()
        self._stop_flag = threading.Event()
        self._interjections: list[str] = []
        self._thread: threading.Thread | None = None

    # ── 事件 ──
    def emit(self, etype: str, data: dict) -> None:
        with self._lock:
            self._seq += 1
            self._events.append(AgentEvent(self._seq, etype, data))
            if len(self._events) > MAX_EVENTS:
                del self._events[: len(self._events) - MAX_EVENTS]

    def events_after(self, after: int, limit: int = 200) -> list[dict]:
        with self._lock:
            return [e.to_dict() for e in self._events if e.seq > after][:limit]

    # ── 生命周期 ──
    def start(self) -> bool:
        if self.status == "running":
            return False
        self.status = "running"
        self.started_at = time.time()
        self._thread = threading.Thread(target=self._run, name=f"agent-{self.id}", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_flag.set()

    def interject(self, message: str) -> bool:
        text = str(message or "").strip()
        if self.status != "running" or not text:
            return False
        with self._lock:
            self._interjections.append(text[:2000])
        self.emit("user_interjection", {"message": text[:500]})
        return True

    def _drain_interjections(self) -> list[str]:
        with self._lock:
            pending = list(self._interjections)
            self._interjections.clear()
        return pending

    def _run(self) -> None:
        try:
            asyncio.run(self._loop())
        except Exception as exc:  # noqa: BLE001
            self.status = "error"
            self.error = f"{type(exc).__name__}: {exc}"
            self.emit("error", {"error": self.error})
        finally:
            self.finished_at = time.time()
            if self.status == "running":
                self.status = "finished"
            self._persist()

    # ── 主循环 ──
    async def _loop(self) -> None:
        from services._services_ai import call_ai_raw

        self.emit("system", {
            "message": "Agent 会话启动",
            "goal": self.goal, "max_steps": self.max_steps,
            "allow_write": self.allow_write,
            "model": self.model or "(配置默认)",
        })

        messages: list[dict] = [
            {"role": "system", "content": self.custom_prompt if self.chat_mode else SYSTEM_PROMPT + "\n" + self.custom_prompt},
            {"role": "user", "content": f"本次任务目标：\n{self.goal}\n\n请开始自主完成。工具清单见 tools。"},
        ]
        messages[1:1] = self.context[-20:]
        tools = self.registry.schemas(include_write=self.allow_write)

        while self.steps < self.max_steps and not self._stop_flag.is_set():
            if time.time() - self.started_at > self.time_budget:
                self.emit("system", {"message": f"已达时间预算 {self.time_budget}s，强制收尾"})
                break

            for interjection in self._drain_interjections():
                messages.append({"role": "user", "content": "【主人运行中补充要求】\n" + interjection})
            self.steps += 1
            self.emit("step", {"step": self.steps, "max": self.max_steps})

            resp = await call_ai_raw(
                messages, model=self.model or None,
                temperature=0.6, max_tokens=2048, timeout=120.0,
                verbose=False, tools=tools, tool_choice="auto",
            )
            if self._stop_flag.is_set():
                break
            msg = resp.choices[0].message
            content = (getattr(msg, "content", "") or "").strip()
            tool_calls = getattr(msg, "tool_calls", None) or []

            if content:
                self.emit("thought", {"step": self.steps, "text": content})

            if not tool_calls and self.chat_mode:
                self.summary = content or "模型未返回内容，请重试。"
                self.outcome = "done" if content else "blocked"
                self.status = "finished"
                self.emit("finish", {"summary": self.summary, "outcome": self.outcome})
                self._persist()
                return

            if not tool_calls:
                # 没调工具也没 finish：视为想结束，引导一次
                messages.append({"role": "assistant", "content": content or "(空)"})
                messages.append({"role": "user", "content":
                    "你还没有调用 finish。若任务已完成请调用 finish 提交总结；"
                    "若还需要继续，请调用合适的工具。"})
                finish_nudge = sum(1 for m in messages if m.get("role") == "user" and "finish" in str(m.get("content", "")))
                if finish_nudge >= 3:
                    self.summary = content or "(无总结)"
                    self.outcome = "partial"
                    break
                continue

            messages.append({
                "role": "assistant",
                "content": content,
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name,
                                     "arguments": tc.function.arguments},
                    }
                    for tc in tool_calls
                ],
            })

            if len(tool_calls) > 20:
                raise ValueError("单步工具请求超过20项限制")
            for tc in tool_calls:
                if time.time() - self.started_at > self.time_budget:
                    self._stop_flag.set()
                if self._stop_flag.is_set():
                    break
                name = re.sub(r"<\|[^|]*\|>\w*", "", str(tc.function.name)).strip()
                try:
                    arguments = json.loads(tc.function.arguments or "{}")
                    if not isinstance(arguments, dict):
                        arguments = {}
                except json.JSONDecodeError:
                    arguments = {}

                defn = self.registry.get(name)
                is_write = bool(defn and defn.risk == "write")
                # 安全注入：会话未开启写权限时，写工具自动降级为 dry_run
                if is_write and not self.allow_write:
                    arguments["allow_write"] = False
                elif is_write:
                    arguments.setdefault("allow_write", True)
                    self.write_calls += 1

                self.emit("tool_call", {
                    "step": self.steps, "name": name,
                    "arguments": arguments, "risk": defn.risk if defn else "?",
                    "write_blocked": is_write and not self.allow_write,
                })
                self.tool_calls += 1

                if is_write and not self.allow_write:
                    result = {"ok": False, "error": "会话未授权写操作；工具未执行"}
                else:
                    import inspect
                    if defn and "allow_write" not in inspect.signature(defn.handler).parameters:
                        arguments.pop("allow_write", None)
                    result = await asyncio.wait_for(self.registry.invoke(name, arguments), timeout=60)
                self.emit("tool_result", {
                    "step": self.steps, "name": name, "result": result,
                })

                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str)[:4000],
                })

                if result.get("finished"):
                    self.summary = str(result.get("summary", ""))
                    self.outcome = str(result.get("outcome", "done"))
                    self.status = "finished"
                    self.emit("finish", {
                        "summary": self.summary, "outcome": self.outcome,
                    })
                    self._persist()
                    return

        if self._stop_flag.is_set():
            self.status = "stopped"
            self.emit("system", {"message": "会话被用户手动停止"})
        elif self.status == "running":
            self.status = "finished"
            self.outcome = self.outcome or "partial"
            self.summary = self.summary or "达到步数/时间上限，未主动 finish。"
            self.emit("finish", {"summary": self.summary, "outcome": self.outcome})
        self._persist()

    # ── 持久化 ──
    def _persist(self) -> None:
        try:
            from core.user_data import DATA_DIR
            d = DATA_DIR / "agent_sessions"
            d.mkdir(parents=True, exist_ok=True)
            payload = {
                "id": self.id, "goal": self.goal, "status": self.status,
                "outcome": self.outcome, "summary": self.summary,
                "error": self.error, "allow_write": self.allow_write,
                "model": self.model,
                "started_at": self.started_at, "finished_at": self.finished_at,
                "steps": self.steps, "tool_calls": self.tool_calls,
                "write_calls": self.write_calls,
                "events": [e.to_dict() for e in list(self._events)],
            }
            (d / f"{self.id}.json").write_text(
                json.dumps(payload, ensure_ascii=False, default=str), encoding="utf-8")
        except Exception:
            pass

    def to_dict(self) -> dict:
        return {
            "id": self.id, "goal": self.goal, "status": self.status,
            "outcome": self.outcome, "summary": self.summary, "error": self.error,
            "allow_write": self.allow_write, "model": self.model,
            "started_at": self.started_at, "finished_at": self.finished_at,
            "steps": self.steps, "max_steps": self.max_steps,
            "tool_calls": self.tool_calls, "write_calls": self.write_calls,
            "last_seq": self._seq,
        }


# 面板进程级单例
ACTIVE_SESSION: AgentSession | None = None
_ACTIVE_LOCK = threading.Lock()


def get_active() -> AgentSession | None:
    return ACTIVE_SESSION


def start_session(goal: str, **kw) -> AgentSession:
    global ACTIVE_SESSION
    with _ACTIVE_LOCK:
        if ACTIVE_SESSION is not None and ACTIVE_SESSION.status == "running":
            raise RuntimeError("已有会话在运行，请先停止")
        ACTIVE_SESSION = AgentSession(goal, **kw)
        ACTIVE_SESSION.start()
        return ACTIVE_SESSION


def stop_session() -> bool:
    with _ACTIVE_LOCK:
        if ACTIVE_SESSION is None or ACTIVE_SESSION.status != "running":
            return False
        ACTIVE_SESSION.stop()
        return True


def interject_session(message: str) -> bool:
    with _ACTIVE_LOCK:
        if ACTIVE_SESSION is None:
            return False
        return ACTIVE_SESSION.interject(message)


def list_history(limit: int = 30) -> list[dict]:
    try:
        from core.user_data import DATA_DIR
        d = DATA_DIR / "agent_sessions"
        out = []
        for f in sorted(d.glob("*.json"), reverse=True)[:limit]:
            try:
                j = json.loads(f.read_text(encoding="utf-8"))
                out.append({k: j.get(k) for k in (
                    "id", "goal", "status", "outcome", "summary",
                    "steps", "tool_calls", "write_calls", "started_at")})
            except Exception:
                continue
        return out
    except Exception:
        return []
