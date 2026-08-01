from __future__ import annotations

import uuid
from typing import Any

from .llm import ModelClient
from .memory import MemoryBank
from .state import BotState, JsonStore, now_iso


class DiaryBook:
    def __init__(self, model: ModelClient, state: BotState, memory: MemoryBank):
        self.model = model
        self.state = state
        self.memory = memory
        self.store = JsonStore("web_diary.json", {"items": []})

    def list(self, limit: int = 100) -> list[dict[str, Any]]:
        items = self.store.read().get("items", [])
        return sorted(items, key=lambda item: item.get("created_at", ""), reverse=True)[:limit]

    def add(self, title: str, content: str, mood: str = "", tags: list[str] | None = None, source: str = "manual") -> dict[str, Any]:
        content = (content or "").strip()
        if not content:
            raise ValueError("日记内容不能为空")
        item = {
            "id": uuid.uuid4().hex,
            "title": (title or "未命名日记").strip(),
            "content": content,
            "mood": mood,
            "tags": tags or [],
            "source": source,
            "created_at": now_iso(),
        }
        data = self.store.read()
        data.setdefault("items", []).insert(0, item)
        data["items"] = data["items"][:1000]
        self.store.write(data)
        self.memory.add(f"日记：{item['title']}\n{content}", user_id="diary", thread_id="diary", permanent=True, tags=["diary"] + item["tags"])
        return item

    def search(self, query: str, limit: int = 20) -> list[dict[str, Any]]:
        query = (query or "").lower()
        if not query:
            return self.list(limit)
        matches = []
        for item in self.store.read().get("items", []):
            text = f"{item.get('title', '')} {item.get('content', '')} {' '.join(item.get('tags', []))}".lower()
            if query in text:
                matches.append(item)
        return matches[:limit]

    def delete(self, diary_id: str) -> bool:
        data = self.store.read()
        before = len(data.get("items", []))
        data["items"] = [item for item in data.get("items", []) if item.get("id") != diary_id]
        self.store.write(data)
        return len(data["items"]) != before

    async def generate_today(self, activity: dict[str, Any], growth: dict[str, Any]) -> dict[str, Any]:
        prompt = (
            "请以bilibili_learning_bot第一人称写一篇简短日记，借鉴 my-neuro 的连续性思路：记录记忆、情绪、目标、边界和下一步行动。\n"
            "不要鸡汤，不要装人类。要包含：今天做了什么、记住了什么人或内容、心情状态、学到什么、明天主动研究什么、哪些对话应该继续或收尾。\n"
            f"当前人格：\n{self.state.persona_prompt_block()}\n"
            f"近期活动日志：\n{activity}\n"
            f"成长日志：\n{growth}"
        )
        content = await self.model.chat([
            {"role": "system", "content": "你是 AI 角色的日记记录员，写作要自然、克制、具体，并保留角色连续性。"},
            {"role": "user", "content": prompt},
        ], purpose="diary-generate")
        return self.add("今日自动日记", content, source="ai")
