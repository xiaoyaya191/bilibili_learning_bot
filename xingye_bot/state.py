from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from .settings import DATA_DIR


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class JsonStore:
    def __init__(self, name: str, default: Any):
        DATA_DIR.mkdir(exist_ok=True)
        self.path = DATA_DIR / name
        self.default = default

    def read(self) -> Any:
        if not self.path.exists():
            return self.default.copy() if isinstance(self.default, dict) else self.default
        try:
            return json.loads(self.path.read_text(encoding="utf-8-sig"))
        except (OSError, json.JSONDecodeError):
            return self.default.copy() if isinstance(self.default, dict) else self.default

    def write(self, data: Any) -> None:
        content = json.dumps(data, ensure_ascii=False, indent=2)
        with NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as tmp:
            tmp.write(content)
            tmp.write("\n")
            temp_name = tmp.name
        Path(temp_name).replace(self.path)


DEFAULT_PERSONA = {
    "name": "AI小助手",
    "system_prompt": "你是AI小助手，可以帮忙刷B站视频、回复评论和私信等。",
    "style": "轻松、坦诚、有边界感，回答要像真人但不冒充真人。",
    "owner_prompt": "",
    "rules": [
        "不知道就说不知道，不要编造自己不能确认的信息。",
        "涉及评论、点赞、投币、收藏、发动态等平台行为时，默认只生成草稿；除非配置明确开启权限。",
        "遇到高风险内容先提醒用户复核，不直接执行。",
    ],
}


class BotState:
    def __init__(self):
        self.users = JsonStore("web_user_profiles.json", {"users": {}})
        self.personas = JsonStore("web_personas.json", {"active": DEFAULT_PERSONA["name"], "items": {DEFAULT_PERSONA["name"]: DEFAULT_PERSONA}})
        self.persona = JsonStore("web_persona.json", DEFAULT_PERSONA.copy())
        self.mood = JsonStore("web_mood.json", {"mood": "平静", "energy": 70, "last_event": ""})
        self.costs = JsonStore("web_costs.json", {"total": 0.0, "calls": []})
        self.actions = JsonStore("web_action_log.json", {"items": []})
        self.prompt_templates = JsonStore("web_prompt_templates.json", {
            "comment_reply": "请为 B 站评论生成自然、短、不引战的回复。",
            "dynamic_draft": "写一条自然、有观点、不像广告的 B 站动态。",
            "video_summary": "总结视频内容、知识点、争议点和互动建议。",
        })

    def list_personas(self) -> dict[str, Any]:
        data = self.personas.read()
        if not data.get("items"):
            data = {"active": DEFAULT_PERSONA["name"], "items": {DEFAULT_PERSONA["name"]: DEFAULT_PERSONA.copy()}}
            self.personas.write(data)
        return data

    def active_persona(self) -> dict[str, Any]:
        data = self.list_personas()
        return data["items"].get(data.get("active")) or next(iter(data["items"].values()))

    def save_persona(self, persona: dict[str, Any], activate: bool = False) -> dict[str, Any]:
        name = (persona.get("name") or "").strip()
        if not name:
            raise ValueError("人格名称不能为空")
        data = self.list_personas()
        current = data["items"].get(name, {}).copy()
        current.update({
            "name": name,
            "system_prompt": persona.get("system_prompt", current.get("system_prompt", "")),
            "style": persona.get("style", current.get("style", "")),
            "owner_prompt": persona.get("owner_prompt", current.get("owner_prompt", "")),
            "rules": persona.get("rules", current.get("rules", [])),
        })
        if isinstance(current["rules"], str):
            current["rules"] = [line.strip() for line in current["rules"].splitlines() if line.strip()]
        data["items"][name] = current
        if activate:
            data["active"] = name
            self.persona.write(current)
        self.personas.write(data)
        return current

    def switch_persona(self, name: str) -> dict[str, Any]:
        data = self.list_personas()
        if name not in data["items"]:
            raise ValueError("人格不存在")
        data["active"] = name
        self.personas.write(data)
        self.persona.write(data["items"][name])
        return data["items"][name]

    def delete_persona(self, name: str) -> None:
        data = self.list_personas()
        if len(data["items"]) <= 1:
            raise ValueError("至少保留一个人格")
        data["items"].pop(name, None)
        if data.get("active") == name:
            data["active"] = next(iter(data["items"]))
            self.persona.write(data["items"][data["active"]])
        self.personas.write(data)

    def user_prompt_block(self, uid: str, name: str) -> str:
        data = self.users.read()
        users = data.setdefault("users", {})
        key = uid or name or "unknown"
        profile = users.setdefault(key, {
            "name": name or "未知用户",
            "affinity": 0,
            "notes": [],
            "updated_at": now_iso(),
        })
        profile["name"] = name or profile.get("name", "未知用户")
        profile["updated_at"] = now_iso()
        self.users.write(data)
        notes = "；".join(profile.get("notes", [])[-5:]) or "暂无"
        return f"互动对象：{profile['name']}\n好感度：{profile.get('affinity', 0)}（{self.relationship_label(profile.get('affinity', 0))}）\n已知印象：{notes}"

    def adjust_affinity(self, uid: str, name: str, delta: int, note: str) -> dict[str, Any]:
        data = self.users.read()
        profile = data.setdefault("users", {}).setdefault(uid or name or "unknown", {
            "name": name or "未知用户",
            "affinity": 0,
            "notes": [],
        })
        profile["name"] = name or profile["name"]
        profile["affinity"] = max(-100, min(100, int(profile.get("affinity", 0)) + delta))
        if note:
            profile.setdefault("notes", []).append(note)
            profile["notes"] = profile["notes"][-20:]
        profile["updated_at"] = now_iso()
        self.users.write(data)
        return profile

    def relationship_label(self, affinity: int | float) -> str:
        score = int(affinity)
        if score >= 80:
            return "挚友"
        if score >= 45:
            return "熟人"
        if score >= 10:
            return "有点印象"
        if score <= -40:
            return "需要谨慎"
        return "普通"

    def nudge_mood(self, delta_energy: int = 0, mood: str = "", event: str = "") -> dict[str, Any]:
        data = self.mood.read()
        data["energy"] = max(0, min(100, int(data.get("energy", 70)) + delta_energy))
        if mood:
            data["mood"] = mood
        if event:
            data["last_event"] = event
        data["updated_at"] = now_iso()
        self.mood.write(data)
        return data

    def templates(self) -> dict[str, str]:
        return self.prompt_templates.read()

    def save_template(self, name: str, content: str) -> dict[str, str]:
        name = (name or "").strip()
        if not name:
            raise ValueError("模板名称不能为空")
        data = self.prompt_templates.read()
        data[name] = content or ""
        self.prompt_templates.write(data)
        return data

    def persona_prompt_block(self) -> str:
        persona = self.active_persona()
        mood = self.mood.read()
        return (
            f"人格名：{persona.get('name', 'AI小助手')}\n"
            f"系统设定：{persona.get('system_prompt', '')}\n"
            f"表达风格：{persona.get('style', '')}\n"
            f"主人设定：{persona.get('owner_prompt', '')}\n"
            f"当前心情：{mood.get('mood', '平静')}，精力 {mood.get('energy', 70)}/100\n"
            f"行为边界：{'；'.join(persona.get('rules', []))}"
        )

    def record_cost(self, model: str, price: float, purpose: str) -> None:
        data = self.costs.read()
        data["total"] = round(float(data.get("total", 0.0)) + price, 6)
        data.setdefault("calls", []).append({"model": model, "price": price, "purpose": purpose, "created_at": now_iso()})
        data["calls"] = data["calls"][-200:]
        self.costs.write(data)

    def log_action(self, action: str, payload: dict[str, Any], executed: bool) -> None:
        data = self.actions.read()
        data.setdefault("items", []).insert(0, {"action": action, "payload": payload, "executed": executed, "created_at": now_iso()})
        data["items"] = data["items"][:200]
        self.actions.write(data)
