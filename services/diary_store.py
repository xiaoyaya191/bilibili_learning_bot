"""Cross-process diary JSON mutations shared by CLI, bot and Web panel."""
import json
import os
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

_LOCK = threading.RLock()


def read(path):
    path = Path(path)
    if not path.exists():
        return {"entries": []}
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("日记文件格式无效")
    entries = data.get("entries", data.get("diaries", []))
    if not isinstance(entries, list):
        raise ValueError("日记列表格式无效")
    return dict(data, entries=[dict(item) if isinstance(item, dict) else {"content": str(item)} for item in entries])


@contextmanager
def locked(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with _LOCK, path.with_suffix(".json.lock").open("a+b") as handle:
        handle.seek(0, 2)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def mutate(path, operation):
    path = Path(path)
    with locked(path):
        data = read(path)
        result = operation(data)
        data.pop("diaries", None)
        temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
        try:
            temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return result


def add(path, title, content, *, mood=None, tags=None, source="manual", entry_type=None, metadata=None, entry_id=None):
    mood = mood if isinstance(mood, dict) else {}
    entry = {
        "id": entry_id or "diary-" + uuid.uuid4().hex,
        "title": str(title or "日记记录")[:120], "content": str(content).strip(),
        "time": datetime.now().isoformat(), "type": entry_type or source, "source": source,
        "tags": [str(tag)[:40] for tag in (tags or [])][:12],
        "mood": mood.get("mood", ""), "energy": mood.get("energy", ""),
    }
    entry.update(metadata or {})
    def operation(data):
        existing = next((item for item in data["entries"] if item.get("id") == entry["id"]), None)
        if existing:
            return existing
        data["entries"].append(entry)
        return entry
    return mutate(path, operation)


def find_index(entries, entry_id):
    for index, item in enumerate(entries):
        if entry_id in (str(item.get("id") or ""), f"legacy-{index}-{item.get('time', '')}"):
            return index
    raise ValueError("未找到该日记")


def update(path, entry_id, title, content):
    def operation(data):
        item = data["entries"][find_index(data["entries"], entry_id)]
        item.update(id=item.get("id") or "diary-" + uuid.uuid4().hex, title=str(title or item.get("title") or "日记记录")[:120], content=content.strip(), updated_at=datetime.now().isoformat())
        return item
    return mutate(path, operation)


def delete(path, entry_id):
    return mutate(path, lambda data: data["entries"].pop(find_index(data["entries"], entry_id)))
