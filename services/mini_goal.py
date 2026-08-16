"""
services/mini_goal.py — 学习小目标（Mini Goal）状态管理：web 面板与机器人子进程共享。

- Data/mini_goal_state.json  当前进行中的小目标（单例状态）
- Data/goal_history.json     已结束目标的历史，存储格式 {"history": [...]}（新的在后）

时间统一使用 datetime.now().isoformat()。
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from core.user_data import DATA_DIR
from utils.storage import JsonStore

# ── 数据文件 ──
STATE_FILE = DATA_DIR / "mini_goal_state.json"
HISTORY_FILE = DATA_DIR / "goal_history.json"

_state_store = JsonStore(STATE_FILE)
_history_store = JsonStore(HISTORY_FILE)

MAX_HISTORY_RECORDS = 50


def _now_iso() -> str:
    return datetime.now().isoformat()


def _parse_iso(value: Any) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return None


def load_state() -> dict:
    """读取 state 文件，异常返回 {}。"""
    data = _state_store.read({})
    return data if isinstance(data, dict) else {}


def save_state(state: dict) -> None:
    """原子写（先写 .tmp 再 os.replace，由 JsonStore 保证）。"""
    _state_store.write(state if isinstance(state, dict) else {})


def get_active() -> dict | None:
    """返回 active=True 且未过期的目标，否则 None（不修改文件）。"""
    state = load_state()
    if not state.get("active"):
        return None
    expires = _parse_iso(state.get("expires_at"))
    if expires is None or expires <= datetime.now():
        return None
    return dict(state)


def start_goal(
    topic: str,
    duration_minutes: int = 60,
    skip_watched: bool = False,
    max_videos: int = 10,
    source: str = "user",
    category: str = "",
) -> dict:
    """创建新的小目标；若已有 active 目标，先 stop_goal(completed=False) 再创建。"""
    if get_active() is not None:
        stop_goal(completed=False)
    now = datetime.now()
    duration_minutes = int(duration_minutes or 60)
    goal: dict = {
        "active": True,
        "topic": str(topic or "").strip(),
        "category": str(category or ""),
        "started_at": now.isoformat(),
        "expires_at": (now + timedelta(minutes=duration_minutes)).isoformat(),
        "duration_minutes": duration_minutes,
        "skip_watched": bool(skip_watched),
        "max_videos": int(max_videos or 10),
        "source": str(source or "user"),
        "watched": [],
        "watched_count": 0,
    }
    save_state(goal)
    return goal


def stop_goal(completed: bool = False) -> dict | None:
    """结束当前 active 目标：追加到历史并清空 state（保留 last_auto_set_at 键）。

    返回写入的历史条目；无 active 目标返回 None。
    """
    state = load_state()
    if not state.get("active"):
        return None
    entry: dict = {
        "topic": state.get("topic", ""),
        "category": state.get("category", ""),
        "started_at": state.get("started_at", ""),
        "ended_at": _now_iso(),
        "duration_minutes": state.get("duration_minutes", 0),
        "watched_count": state.get("watched_count", 0),
        "max_videos": state.get("max_videos", 0),
        "skip_watched": bool(state.get("skip_watched", False)),
        "source": state.get("source", ""),
        "completed": bool(completed),
        "watched": [str(b) for b in (state.get("watched") or []) if b],
    }

    def _mutate(data: dict) -> None:
        if not isinstance(data, dict):
            return
        records = data.get("history")
        if not isinstance(records, list):
            data.clear()
            records = []
            data["history"] = records
        records.append(entry)
        # 只保留最近 MAX_HISTORY_RECORDS 条，避免无界增长
        if len(records) > MAX_HISTORY_RECORDS:
            del records[: len(records) - MAX_HISTORY_RECORDS]

    _history_store.update(_mutate)

    new_state: dict = {"active": False}
    if state.get("last_auto_set_at"):
        new_state["last_auto_set_at"] = state["last_auto_set_at"]
    save_state(new_state)
    return entry


def append_watched(bvid: str) -> int:
    """去重追加 bvid 到 watched 并更新 watched_count。

    达到 max_videos 时不自动停止（由调用方判断）；返回最新 watched_count；
    无 active 目标返回 -1。
    """
    state = load_state()
    if not state.get("active"):
        return -1
    watched = state.get("watched") if isinstance(state.get("watched"), list) else []
    bvid = str(bvid or "").strip()
    if bvid and bvid not in watched:
        watched.append(bvid)
    state["watched"] = watched
    state["watched_count"] = len(watched)
    save_state(state)
    return state["watched_count"]


def load_history() -> list:
    """读取历史（最近 50 条，新的在前）。"""
    data = _history_store.read({})
    records = data.get("history") if isinstance(data, dict) else None
    if not isinstance(records, list):
        return []
    return [dict(r) for r in reversed(records[-MAX_HISTORY_RECORDS:])]


def touch_auto_set() -> None:
    """记录 AI 自动设定目标的时间戳（用于自动设定的冷却判断）。"""
    state = load_state()
    state["last_auto_set_at"] = _now_iso()
    save_state(state)


def auto_set_cooldown_ok(hours: float = 6.0) -> bool:
    """距 last_auto_set_at 超过 hours 小时返回 True（可再次自动设定）。"""
    last = _parse_iso(load_state().get("last_auto_set_at"))
    if last is None:
        return True
    return datetime.now() - last >= timedelta(hours=hours)