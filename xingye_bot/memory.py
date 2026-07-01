from __future__ import annotations

import math
import re
import uuid
from collections import Counter, OrderedDict
from typing import Any

from .state import JsonStore, now_iso

# [SPEED] LRU cache for tokenization and vectorization (hot path in search)
_VECTOR_CACHE: OrderedDict[str, Counter] = OrderedDict()
_VECTOR_CACHE_MAX = 256
_SEARCH_CACHE: OrderedDict[str, list[dict[str, Any]]] = OrderedDict()
_SEARCH_CACHE_MAX = 64


def _tokens(text: str) -> list[str]:
    text = (text or "").lower()
    words = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", text)
    chunks = [text[i:i + 2] for i in range(max(0, len(text) - 1)) if text[i:i + 2].strip()]
    return words + chunks


def _vector(text: str) -> Counter:
    key = text[:200]  # cache key by prefix
    if key in _VECTOR_CACHE:
        _VECTOR_CACHE.move_to_end(key)
        return _VECTOR_CACHE[key]
    vec = Counter(_tokens(text))
    if len(_VECTOR_CACHE) >= _VECTOR_CACHE_MAX:
        _VECTOR_CACHE.popitem(last=False)
    _VECTOR_CACHE[key] = vec
    return vec


def _cosine(a: Counter, b: Counter) -> float:
    if not a or not b:
        return 0.0
    dot = sum(a[k] * b.get(k, 0) for k in a)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


class MemoryBank:
    def __init__(self):
        self.store = JsonStore("web_memories.json", {"items": []})

    def list(self, user_id: str = "", limit: int = 100) -> list[dict[str, Any]]:
        items = self.store.read().get("items", [])
        if user_id:
            items = [item for item in items if item.get("user_id") == user_id]
        return sorted(items, key=lambda item: item.get("updated_at", ""), reverse=True)[:limit]

    def add(self, content: str, user_id: str = "local", thread_id: str = "local", permanent: bool = False, tags: list[str] | None = None) -> dict[str, Any]:
        content = (content or "").strip()
        if not content:
            raise ValueError("content cannot be empty")
        data = self.store.read()
        item = {
            "id": uuid.uuid4().hex,
            "content": content,
            "summary": content[:160],
            "user_id": user_id or "local",
            "thread_id": thread_id or "local",
            "permanent": bool(permanent),
            "tags": tags or [],
            "created_at": now_iso(),
            "updated_at": now_iso(),
        }
        data.setdefault("items", []).append(item)
        data["items"] = data["items"][-1000:]
        self.store.write(data)
        # [SPEED] Invalidate search cache on add
        _SEARCH_CACHE.clear()
        return item

    def attach_embedding(self, memory_id: str, embedding: list[float]) -> bool:
        data = self.store.read()
        changed = False
        for item in data.get("items", []):
            if item.get("id") == memory_id:
                item["embedding"] = embedding
                item["updated_at"] = now_iso()
                changed = True
                break
        if changed:
            self.store.write(data)
        return changed

    def search(self, query: str, user_id: str = "", limit: int = 8) -> list[dict[str, Any]]:
        # [SPEED] LRU cache for repeated queries
        cache_key = f"{query[:100]}|{user_id}|{limit}"
        if cache_key in _SEARCH_CACHE:
            _SEARCH_CACHE.move_to_end(cache_key)
            return _SEARCH_CACHE[cache_key]
        
        qv = _vector(query)
        scored = []
        for item in self.store.read().get("items", []):
            if user_id and item.get("user_id") != user_id:
                continue
            score = _cosine(qv, _vector(item.get("content", "") + " " + " ".join(item.get("tags", []))))
            if score > 0:
                copy = item.copy()
                copy["score"] = round(score, 4)
                scored.append(copy)
        result = sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]
        
        if len(_SEARCH_CACHE) >= _SEARCH_CACHE_MAX:
            _SEARCH_CACHE.popitem(last=False)
        _SEARCH_CACHE[cache_key] = result
        return result

    def search_embedding(self, query_embedding: list[float], user_id: str = "", limit: int = 8) -> list[dict[str, Any]]:
        scored = []
        for item in self.store.read().get("items", []):
            if user_id and item.get("user_id") != user_id:
                continue
            embedding = item.get("embedding")
            if not embedding:
                continue
            score = _float_cosine(query_embedding, embedding)
            copy = item.copy()
            copy["score"] = round(score, 4)
            scored.append(copy)
        return sorted(scored, key=lambda item: item["score"], reverse=True)[:limit]

    def delete(self, memory_id: str) -> bool:
        data = self.store.read()
        before = len(data.get("items", []))
        data["items"] = [item for item in data.get("items", []) if item.get("id") != memory_id]
        self.store.write(data)
        return len(data["items"]) != before

    def prompt_block(self, query: str, user_id: str = "") -> str:
        matches = self.search(query, user_id=user_id, limit=5)
        if not matches:
            return "相关长期记忆：暂无"
        lines = [f"- {item['summary']} (score={item['score']})" for item in matches]
        return "相关长期记忆：\n" + "\n".join(lines)


def _float_cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    dot = sum(a[i] * b[i] for i in range(size))
    na = math.sqrt(sum(a[i] * a[i] for i in range(size)))
    nb = math.sqrt(sum(b[i] * b[i] for i in range(size)))
    return dot / (na * nb) if na and nb else 0.0
