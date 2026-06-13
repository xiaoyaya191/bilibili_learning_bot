from __future__ import annotations

from typing import Any

from .llm import ModelClient
from .memory import MemoryBank
from .state import BotState, JsonStore, now_iso


class EvolutionEngine:
    def __init__(self, model: ModelClient, state: BotState, memory: MemoryBank):
        self.model = model
        self.state = state
        self.memory = memory
        self.store = JsonStore("web_growth_log.json", {"items": []})

    def logs(self) -> dict[str, Any]:
        return self.store.read()

    async def reflect(self) -> dict[str, Any]:
        persona = self.state.active_persona()
        memories = self.memory.list(limit=20)
        prompt = (
            "请根据最近互动为这个 AI 角色做一次每日反思。只输出 JSON，字段：reflection、style_delta、new_rule、mood。\n"
            f"当前人格：{persona}\n最近记忆：{memories}"
        )
        text = await self.model.chat([
            {"role": "system", "content": "你是角色成长记录员，只提出温和、可控的性格演化建议。"},
            {"role": "user", "content": prompt},
        ], purpose="personality-evolution")
        item = {"raw": text, "created_at": now_iso()}
        data = self.store.read()
        data.setdefault("items", []).insert(0, item)
        data["items"] = data["items"][:200]
        self.store.write(data)
        return item
