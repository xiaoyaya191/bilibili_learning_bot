"""Small local reminder store shared by the chat Agent and Windows launchers."""
from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path

from core.user_data import DATA_DIR


_LOCK = threading.RLock()


def _path(data_dir=None) -> Path:
    return Path(data_dir or DATA_DIR) / "reminders.json"


def _read(data_dir=None) -> list[dict]:
    try:
        rows = json.loads(_path(data_dir).read_text(encoding="utf-8"))
        return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def _write(rows: list[dict], data_dir=None) -> None:
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rows[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def parse_reminder_time(text: str, now: datetime | None = None) -> datetime | None:
    """Parse the common Chinese reminder forms without pretending ambiguous text is precise."""
    now = now or datetime.now()
    value = str(text or "")
    if re.search(r"半\s*(?:个)?\s*小时(?:后|之后)", value, re.I):
        return now + timedelta(minutes=30)
    relative = re.search(
        r"(?:(\d{1,3})\s*(?:小时|时|hours?|hrs?))?\s*"
        r"(?:(\d{1,4})\s*(?:分钟|分|mins?|minutes?))?\s*(?:后|之后)",
        value,
        re.I,
    )
    if relative and (relative.group(1) or relative.group(2)):
        return now + timedelta(hours=int(relative.group(1) or 0), minutes=int(relative.group(2) or 0))
    clock = re.search(r"(?:(\d{1,2})\s*[:：]\s*(\d{1,2})|(\d{1,2})\s*点\s*(半|(\d{1,2})\s*分?)?)", value)
    if not clock:
        return None
    hour = int(clock.group(1) or clock.group(3) or 0)
    minute = int(clock.group(2) or clock.group(5) or (30 if clock.group(4) == "半" else 0))
    if hour > 23 or minute > 59:
        return None
    if any(marker in value for marker in ("下午", "晚上", "傍晚", "今晚")) and hour < 12:
        hour += 12
    if any(marker in value for marker in ("凌晨", "早上", "早晨", "上午")) and hour == 12:
        hour = 0
    target_date = now.date()
    if "明天" in value:
        target_date += timedelta(days=1)
    candidate = datetime.combine(target_date, datetime.min.time()).replace(hour=hour, minute=minute)
    if "今天" not in value and "明天" not in value and candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def create_from_text(text: str, *, owner_uid: str, now: datetime | None = None, data_dir=None) -> dict:
    when = parse_reminder_time(text, now=now)
    if when is None:
        return {"ok": False, "message": "没有识别到明确时间，请写成“明天 8 点提醒我……”或“20 分钟后提醒我……”"}
    content = re.sub(r".*?(?:提醒我|叫我|到点提醒)", "", str(text or ""), count=1).strip(" ，,。！!：:")
    content = content or str(text or "").strip()
    row = {
        "id": uuid.uuid4().hex[:12], "owner_uid": str(owner_uid), "content": content[:240],
        "due_at": when.isoformat(timespec="minutes"), "created_at": (now or datetime.now()).isoformat(timespec="seconds"),
        "status": "pending", "delivered_at": "",
    }
    with _LOCK:
        rows = _read(data_dir)
        rows.append(row)
        _write(rows, data_dir)
    return {"ok": True, "reminder": row, "message": f"已设定 {when:%Y-%m-%d %H:%M} 提醒：{content[:80]}"}


def take_due(now: datetime | None = None, data_dir=None) -> list[dict]:
    now = now or datetime.now()
    due = []
    with _LOCK:
        rows = _read(data_dir)
        for row in rows:
            if row.get("status") != "pending":
                continue
            try:
                due_at = datetime.fromisoformat(str(row.get("due_at") or ""))
            except ValueError:
                continue
            if due_at <= now:
                row["status"] = "delivered"
                row["delivered_at"] = now.isoformat(timespec="seconds")
                due.append(dict(row))
        if due:
            _write(rows, data_dir)
    return due
