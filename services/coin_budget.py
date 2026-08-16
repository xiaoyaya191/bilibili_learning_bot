"""services/coin_budget.py — 跨模块共享的每日投币预算（评论三连与视频投币共用）"""
import json
import os
import threading
from datetime import datetime

_LOCK = threading.Lock()


def _file_path() -> str:
    from core.config import DATA_DIR
    return os.path.join(DATA_DIR, "coin_budget.json")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _read() -> dict:
    try:
        with open(_file_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("date") == _today():
            return data
    except Exception:
        pass
    return {"date": _today(), "spent": 0}


def coins_today() -> int:
    with _LOCK:
        return int(_read().get("spent") or 0)


def add_coin(n: int = 1) -> int:
    with _LOCK:
        data = _read()
        data["spent"] = int(data.get("spent") or 0) + int(n)
        path = _file_path()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
        os.replace(tmp, path)
        return data["spent"]