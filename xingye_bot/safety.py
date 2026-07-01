from __future__ import annotations

from typing import Any

from .state import JsonStore, now_iso


DEFAULT_BAD_WORDS = [
    "去死",
    "傻逼",
    "垃圾",
    "废物",
    "脑残",
    "滚",
]


class SafetyGuard:
    def __init__(self):
        self.store = JsonStore("web_safety.json", {"bad_words": DEFAULT_BAD_WORDS, "blacklist": {}, "events": []})

    def check(self, text: str, user_id: str = "", user_name: str = "") -> dict[str, Any]:
        data = self.store.read()
        bad_words = data.get("bad_words", DEFAULT_BAD_WORDS)
        hits = [word for word in bad_words if word and word in (text or "")]
        blocked = bool(user_id and user_id in data.get("blacklist", {}))
        risk = "high" if blocked or len(hits) >= 2 else "medium" if hits else "low"
        event = {
            "user_id": user_id,
            "user_name": user_name,
            "text": text,
            "hits": hits,
            "risk": risk,
            "blocked": blocked,
            "created_at": now_iso(),
        }
        data.setdefault("events", []).insert(0, event)
        data["events"] = data["events"][:300]
        self.store.write(data)
        return event

    def block(self, user_id: str, user_name: str = "", reason: str = "") -> dict[str, Any]:
        if not user_id:
            raise ValueError("用户 ID 不能为空")
        data = self.store.read()
        data.setdefault("blacklist", {})[user_id] = {"user_name": user_name, "reason": reason, "created_at": now_iso()}
        self.store.write(data)
        return data["blacklist"][user_id]

    def unblock(self, user_id: str) -> bool:
        data = self.store.read()
        existed = user_id in data.get("blacklist", {})
        data.setdefault("blacklist", {}).pop(user_id, None)
        self.store.write(data)
        return existed

    def snapshot(self) -> dict[str, Any]:
        return self.store.read()
