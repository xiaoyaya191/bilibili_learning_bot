"""Safe, user-controlled Bilibili social workspaces.

The module deliberately separates read operations and local drafts from any
write to a Bilibili account.  Callers must explicitly opt in before sending a
dynamic or changing the account's watch-later list.
"""
from __future__ import annotations

import asyncio
import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Awaitable

from core.user_data import DATA_DIR


_LOCK = threading.RLock()


def run_async(awaitable: Awaitable[Any]) -> Any:
    """Run an API coroutine from the Flask worker without reusing a stale loop."""
    return asyncio.run(awaitable)


def _store_path(name: str) -> Path:
    path = Path(DATA_DIR) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_rows(name: str) -> list[dict[str, Any]]:
    try:
        rows = json.loads(_store_path(name).read_text(encoding="utf-8"))
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write_rows(name: str, rows: list[dict[str, Any]]) -> None:
    path = _store_path(name)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(rows[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(path)


def _append_publish_log(entry: dict[str, Any]) -> None:
    """追加一条动态发布记录（dynamic_publish_log.json），供面板"发布记录"展示。"""
    try:
        path = _store_path("dynamic_publish_log.json")
        rows = []
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(existing, list):
                rows = existing
        except (OSError, json.JSONDecodeError):
            rows = []
        entry.setdefault("time", datetime.now().isoformat(timespec="seconds"))
        # 只保留可 JSON 序列化的字段，避免 B站原始响应含不可序列化对象导致整条日志丢失
        result = entry.get("result")
        if not isinstance(result, dict):
            entry["result"] = {"executed": bool(result)}
        else:
            safe = {}
            for k, v in result.items():
                try:
                    json.dumps(v, ensure_ascii=False)
                    safe[k] = v
                except (TypeError, ValueError):
                    safe[k] = str(v)[:200]
            entry["result"] = safe
        rows.append(entry)
        rows = rows[-500:]
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)
    except Exception:
        pass


def _credential():
    from xingye_bot.bilibili_ops import BilibiliAccount
    return BilibiliAccount().credential()


def _normalize_watch_item(item: dict[str, Any]) -> dict[str, Any]:
    owner = item.get("owner") if isinstance(item.get("owner"), dict) else {}
    progress = item.get("progress") if isinstance(item.get("progress"), dict) else {}
    return {
        "bvid": str(item.get("bvid") or item.get("bv_id") or ""),
        "aid": str(item.get("aid") or ""),
        "title": str(item.get("title") or "")[:240],
        "cover": str(item.get("pic") or item.get("cover") or "")[:1500],
        "up": str(owner.get("name") or item.get("owner_name") or "")[:120],
        "duration": int(item.get("duration") or 0),
        "progress": int(progress.get("progress") or item.get("progress") or 0),
        "watched": bool(progress.get("last_play_cid") or item.get("watched")),
        "added_at": int(item.get("add_at") or item.get("ctime") or 0),
    }


_WATCH_LATER_TTL_SECONDS = 30.0
_watch_later_cache: dict[str, Any] = {"fetched_at": 0.0, "items": []}


def invalidate_watch_later_cache() -> None:
    _watch_later_cache.update(fetched_at=0.0, items=[])


def list_watch_later(force: bool = False) -> list[dict[str, Any]]:
    """Read the currently logged-in account's watch-later entries.

    Each live fetch spins up a fresh event loop and Bilibili client, which is
    slow inside the long-lived panel process. Serve a short-lived cache for
    repeated visits; pass force=True to bypass it.
    """
    import time as _time

    if not force and (_time.time() - float(_watch_later_cache.get("fetched_at") or 0.0)) < _WATCH_LATER_TTL_SECONDS:
        return list(_watch_later_cache.get("items") or [])
    from bilibili_api import user
    result = run_async(user.get_toview_list(_credential()))
    if isinstance(result, dict):
        rows = result.get("list") or result.get("items") or result.get("data") or []
    else:
        rows = result or []
    items = [_normalize_watch_item(row) for row in rows if isinstance(row, dict)]
    _watch_later_cache.update(fetched_at=_time.time(), items=items)
    return list(items)


def add_watch_later(bvid: str) -> dict[str, Any]:
    from bilibili_api.video import Video
    result = run_async(Video(bvid=bvid, credential=_credential()).add_to_toview())
    invalidate_watch_later_cache()
    return result


def remove_watch_later(bvid: str) -> dict[str, Any]:
    from bilibili_api.video import Video
    result = run_async(Video(bvid=bvid, credential=_credential()).delete_from_toview())
    invalidate_watch_later_cache()
    return result


def clear_watch_later() -> dict[str, Any]:
    from bilibili_api import user
    result = run_async(user.clear_toview_list(_credential()))
    invalidate_watch_later_cache()
    return result


def list_dynamic_drafts() -> list[dict[str, Any]]:
    return sorted(_read_rows("dynamic_drafts.json"), key=lambda row: row.get("updated_at", ""), reverse=True)


def save_dynamic_draft(payload: dict[str, Any]) -> dict[str, Any]:
    text = str(payload.get("text") or "").strip()
    if not text:
        raise ValueError("Dynamic text cannot be empty")
    now = datetime.now().isoformat(timespec="seconds")
    draft_id = str(payload.get("id") or uuid.uuid4().hex[:12])
    row = {
        "id": draft_id,
        "text": text[:2000],
        "image_path": str(payload.get("image_path") or "")[:1200],
        "close_comment": bool(payload.get("close_comment")),
        "source": str(payload.get("source") or "manual")[:80],
        "due_at": str(payload.get("due_at") or "")[:40],
        "status": str(payload.get("status") or "draft"),
        "created_at": now,
        "updated_at": now,
        "published_at": "",
    }
    with _LOCK:
        rows = _read_rows("dynamic_drafts.json")
        for index, existing in enumerate(rows):
            if str(existing.get("id")) == draft_id:
                row["created_at"] = existing.get("created_at") or now
                row["published_at"] = existing.get("published_at") or ""
                rows[index] = row
                break
        else:
            rows.append(row)
        _write_rows("dynamic_drafts.json", rows)
    return row


def delete_dynamic_draft(draft_id: str) -> bool:
    with _LOCK:
        rows = _read_rows("dynamic_drafts.json")
        kept = [row for row in rows if str(row.get("id")) != str(draft_id)]
        if len(kept) == len(rows):
            return False
        _write_rows("dynamic_drafts.json", kept)
    return True


def publish_dynamic_draft(draft_id: str) -> dict[str, Any]:
    """Send a specific local draft.  The UI only invokes this after confirmation."""
    with _LOCK:
        rows = _read_rows("dynamic_drafts.json")
        draft = next((row for row in rows if str(row.get("id")) == str(draft_id)), None)
        if not draft:
            raise ValueError("Dynamic draft not found")
        if draft.get("status") == "published":
            raise ValueError("Dynamic draft was already published")
    from xingye_bot.bilibili_ops import BilibiliAccount
    import asyncio
    # send_dynamic 是同步函数；account 构造可能含异步初始化，稳妥起见仍用 run_async 触发
    account = BilibiliAccount()
    if hasattr(account, "ensure_login") and asyncio.iscoroutinefunction(account.ensure_login):
        run_async(account.ensure_login())
    result = account.send_dynamic(
        str(draft.get("text") or ""), str(draft.get("image_path") or ""),
        dry_run=False, allow_dynamic=True,
    )
    if not result.get("executed"):
        raise RuntimeError(str(result.get("reason") or "Bilibili did not accept the dynamic"))
    with _LOCK:
        rows = _read_rows("dynamic_drafts.json")
        for row in rows:
            if str(row.get("id")) == str(draft_id):
                row["status"] = "published"
                row["published_at"] = datetime.now().isoformat(timespec="seconds")
                row["updated_at"] = row["published_at"]
                break
        _write_rows("dynamic_drafts.json", rows)
    _append_publish_log({
        "source": "draft",
        "draft_id": str(draft_id),
        "text": str(draft.get("text") or "")[:500],
        "image_path": str(draft.get("image_path") or ""),
        "result": result,
    })
    return result

def publish_test_dynamic(text: str) -> dict[str, Any]:
    """Test-publish a dynamic directly (real publish)."""
    from xingye_bot.bilibili_ops import BilibiliAccount
    # send_dynamic 是同步函数，直接调用（不要套 run_async）
    result = BilibiliAccount().send_dynamic(
        str(text or ""), "", dry_run=False, allow_dynamic=True)
    _append_publish_log({
        "source": "test",
        "draft_id": "",
        "text": str(text or "")[:500],
        "image_path": "",
        "result": result,
    })
    return result
