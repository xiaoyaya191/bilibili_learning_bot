"""
services/search_history.py — AI 历史搜索记录与即时搜索队列

功能：
1. 记录 AI 为深入了解某个主题而进行的每一次搜索：具体时间、搜索内容、
   搜索到的视频/网页来源、观看数量、触发方式（用户/自动）等。
2. Web 面板的"AI 历史搜索"分区读取这些记录并展示。
3. 提供"待执行搜索"队列：用户输入主题后写入队列文件，主循环（bot 子进程）
   读到后立即暂停当前任务去深入搜索并观看相关视频，完成后恢复原任务。

设计：
- 历史记录持久化到 Data/search_history.json（线程安全 JsonStore）。
- 待执行搜索持久化到 Data/pending_search.json，供跨进程（web 面板 Flask 服务
  与 bot 主循环子进程）通信。
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from core.user_data import DATA_DIR
from utils.storage import JsonStore

# ── 数据文件 ──
SEARCH_HISTORY_FILE = DATA_DIR / "search_history.json"
PENDING_SEARCH_FILE = DATA_DIR / "pending_search.json"

_history_store = JsonStore(SEARCH_HISTORY_FILE)
_pending_store = JsonStore(PENDING_SEARCH_FILE)

MAX_HISTORY_RECORDS = 500


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _now_display() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def record_search(
    *,
    query: str,
    mode: str = "bilibili",
    trigger: str = "user",
    sources: list[dict[str, Any]] | None = None,
    videos_watched: int = 0,
    status: str = "completed",
    error: Any = None,
    report_path: str = "",
    resumed: str = "",
    ts: str = "",
    display_time: str = "",
) -> dict[str, Any]:
    """追加一条搜索历史记录，返回写入的记录。

    ts / display_time 允许手动补录时自定义时间（面板"手动添加记录"用）。
    """
    query = (query or "").strip()
    record: dict[str, Any] = {
        "id": "sh_" + uuid.uuid4().hex[:12],
        "ts": ts or _now_iso(),
        "display_time": display_time or _now_display(),
        "query": query,
        "mode": mode,
        "trigger": trigger,
        "sources": [dict(s) for s in (sources or [])],
        "videos_watched": int(videos_watched or 0),
        "status": status,
        "error": str(error) if error else None,
        "report_path": report_path,
        "resumed": resumed,
    }

    def _mutate(data: dict[str, Any]) -> None:
        records = data.get("records") if isinstance(data, dict) else None
        if not isinstance(records, list):
            records = []
            data.clear()
            data["records"] = records
        records.append(record)
        # 只保留最近 MAX_HISTORY_RECORDS 条，避免无界增长
        if len(records) > MAX_HISTORY_RECORDS:
            del records[: len(records) - MAX_HISTORY_RECORDS]

    _history_store.update(_mutate)
    return record


def get_search_history(limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    """读取搜索历史记录（最新的在前）。"""
    data = _history_store.read({})
    records = data.get("records") if isinstance(data, dict) else []
    if not isinstance(records, list):
        records = []
    # 最新的在前
    ordered = list(reversed(records))
    limit = max(1, min(500, int(limit or 50)))
    offset = max(0, int(offset or 0))
    return [dict(r) for r in ordered[offset:offset + limit]]


def search_history_count() -> int:
    data = _history_store.read({})
    records = data.get("records") if isinstance(data, dict) else []
    return len(records) if isinstance(records, list) else 0


def clear_search_history() -> int:
    """清空搜索历史，返回被清除的记录数。"""
    removed = [0]

    def _mutate(data: dict[str, Any]) -> None:
        records = data.get("records") if isinstance(data, dict) else []
        removed[0] = len(records) if isinstance(records, list) else 0
        data.clear()
        data["records"] = []

    _history_store.update(_mutate)
    return removed[0]


def delete_search_record(record_id: str) -> bool:
    """按 id 删除单条搜索历史记录。"""
    record_id = str(record_id or "").strip()
    if not record_id:
        return False
    hit = [False]

    def _mutate(data: dict[str, Any]) -> None:
        records = data.get("records") if isinstance(data, dict) else []
        if not isinstance(records, list):
            return
        kept = [r for r in records if str((r or {}).get("id") or "") != record_id]
        hit[0] = len(kept) != len(records)
        data["records"] = kept

    _history_store.update(_mutate)
    return hit[0]


def set_pending_search(
    *,
    query: str,
    mode: str = "bilibili",
    sort_by: str = "default",
    video_count: int = 6,
    trigger: str = "user",
) -> dict[str, Any]:
    """写入一条待执行搜索。主循环读到后立即执行。"""
    item = {
        "id": "ps_" + uuid.uuid4().hex[:12],
        "query": (query or "").strip(),
        "mode": mode,
        "sort_by": sort_by,
        "video_count": max(1, min(20, int(video_count or 6))),
        "trigger": trigger,
        "created_at": _now_iso(),
    }
    _pending_store.write(item)
    return item


def get_pending_search() -> dict[str, Any] | None:
    """读取当前待执行搜索（不删除）。"""
    item = _pending_store.read(None)
    if not isinstance(item, dict) or not (item.get("query") or "").strip():
        return None
    return dict(item)


def pop_pending_search() -> dict[str, Any] | None:
    """弹出并清除待执行搜索。返回待执行搜索项，无则返回 None。

    使用读-删两步完成；由于写入是原子替换，跨进程也能安全消费。
    """
    item = get_pending_search()
    if item is None:
        return None
    _pending_store.write({})
    return item


def clear_pending_search() -> None:
    _pending_store.write({})