"""Small file-backed notification bridge between the panel and desktop tray."""
from __future__ import annotations

import json
import threading
from datetime import datetime
from pathlib import Path

_LOCK = threading.Lock()
_FILENAME = "desktop_notifications.jsonl"


def enqueue(data_dir: Path, title: str, message: str) -> None:
    """Queue a concise, credential-free notification for the desktop host."""
    try:
        path = Path(data_dir) / _FILENAME
        row = {"time": datetime.now().isoformat(timespec="seconds"), "title": str(title)[:80], "message": str(message)[:240]}
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    except OSError:
        pass


def take_pending(data_dir: Path) -> list[dict]:
    """Return and clear queued notifications without exposing application data."""
    path = Path(data_dir) / _FILENAME
    with _LOCK:
        try:
            if not path.exists():
                return []
            lines = path.read_text(encoding="utf-8").splitlines()
            path.write_text("", encoding="utf-8")
        except OSError:
            return []
    rows = []
    for line in lines[-50:]:
        try:
            row = json.loads(line)
            if isinstance(row, dict) and row.get("title") and row.get("message"):
                rows.append(row)
        except json.JSONDecodeError:
            continue
    return rows
