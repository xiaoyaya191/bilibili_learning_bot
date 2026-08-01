"""services/managers.py — 管理类（Persona/Mood/UserProfile/BotDiary/SelfEvolution/PrivateContext）

每个类通过 __init__(config) 接收配置，使用 core.config 中的路径常量。
"""
import os, json, random, time
from datetime import datetime, timedelta
from colorama import Fore, Style
from core.config import (
    PERSONAS_FILE, MOOD_STATE_FILE, USER_PROFILES_FILE,
    BOT_DIARY_FILE, SELF_EVOLUTION_FILE, PRIVATE_CONTEXT_FILE,
    AGENT_SKILL_LOG_FILE, load_json_file, save_json_file, config as _global_config
)


# ===== PrivateContextDB =====

class PrivateContextDB:
    """私信上下文数据库 - 每个用户的对话历史管理"""

    def __init__(self, config: dict = None):
        self._cfg = config or _global_config
        self.file_path = PRIVATE_CONTEXT_FILE
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _save(self):
        """原子写入 JSON 文件（tmp+replace 防止断电损坏）"""
        try:
            tmp = self.file_path + '.tmp'
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.file_path)
            return True
        except Exception:
            return False

    def get_context(self, user_id: str, max_messages: int = 20) -> list:
        ctx = self.data.get(user_id, [])
        return ctx[-max_messages:] if ctx else []

    def add_message(self, user_id: str, role: str, content: str):
        if user_id not in self.data:
            self.data[user_id] = []
        self.data[user_id].append({
            "role": role, "content": content,
            "time": datetime.now().isoformat()
        })
        self._save()

    def clear_context(self, user_id: str):
        if user_id in self.data:
            del self.data[user_id]
            self._save()

    def get_or_create(self, user_id: str) -> list:
        if user_id not in self.data:
            self.data[user_id] = []
            self._save()
        return self.data[user_id]


# ===== PersonaManager =====

class PersonaManager:
    """人格管理器 - 管理不同的人格设定与当前激活人格"""

    def __init__(self, config: dict = None):
        self._cfg = config or _global_config
        self.file_path = PERSONAS_FILE
        self.data = self._load()
        self.config = self._cfg

    def _load(self):
        return load_json_file(PERSONAS_FILE, {})

    def _save(self):
        return save_json_file(self.file_path, self.data)

    def _default_data(self):
        active = (self.config.get("persona", {}).get("active_persona", "默认人格")
                  if self.config else "默认人格")
        return {
            "active_persona": active,
            "personas": {
                "默认人格": {
                    "name": "AI小助手",
                    "greeting": "你好！我是你的AI小助手~",
                    "style": "热情、专业",
                    "system_prompt": ""
                }
            }
        }

    def get_active_persona(self) -> str:
        return self.data.get("active_persona", "默认人格")

    def set_active_persona(self, name: str):
        self.data["active_persona"] = name
        self._save()

    def get_persona(self, name: str = None) -> dict:
        name = name or self.get_active_persona()
        return self.data.get("personas", {}).get(name, {})

    def list_personas(self) -> list:
        return list(self.data.get("personas", {}).keys())

    def add_persona(self, name: str, info: dict):
        if "personas" not in self.data:
            self.data["personas"] = {}
        self.data["personas"][name] = info
        self._save()

    def delete_persona(self, name: str):
        if name in self.data.get("personas", {}):
            del self.data["personas"][name]
            if self.data.get("active_persona") == name:
                remaining = list(self.data["personas"].keys())
                self.data["active_persona"] = remaining[0] if remaining else "默认人格"
            self._save()

    def get_prompt_name(self) -> str:
        p = self.get_persona()
        return p.get("name", "AI小助手")

    def get_greeting(self) -> str:
        p = self.get_persona()
        return p.get("greeting", "你好！")

    def get_style(self) -> str:
        p = self.get_persona()
        return p.get("style", "热情、专业")

    def get_system_prompt(self) -> str:
        p = self.get_persona()
        return p.get("system_prompt", "")

    def build_prompt_block(self) -> str:
        """构建用于 prompt 的人格描述块"""
        p = self.get_persona()
        name = p.get("name", "AI小助手")
        style = p.get("style", "热情、专业")
        sp = p.get("system_prompt", "")
        lines = [f"【当前人格】{name}", f"风格: {style}"]
        if sp:
            lines.append(sp)
        return "\n".join(lines)

    def recheck(self):
        self.data = self._load()


# ===== MoodManager =====

class MoodManager:
    """心情系统 - 根据互动结果动态调整当前心情"""

    ALL_MOODS = ["兴奋", "愉快", "平静", "好奇", "慵懒", "深沉",
                 "调皮", "温柔", "毒舌", "学究", "中二", "佛系", "热血"]

    def __init__(self, config: dict = None):
        self._cfg = config or _global_config
        self.file_path = MOOD_STATE_FILE
        self.config = self._cfg
        self.data = self._load()

    def _load(self):
        return load_json_file(MOOD_STATE_FILE, {})

    def _save(self):
        return save_json_file(self.file_path, self.data)

    def _default_data(self):
        return {
            "current": (self.config.get("mood", {}).get("default_mood", "平静")
                       if self.config else "平静"),
            "volatility": (self.config.get("mood", {}).get("mood_volatility", 1.0)
                          if self.config else 1.0),
            "history": []
        }

    def get_current(self) -> str:
        return self.data.get("current", "平静")

    def set_mood(self, mood: str):
        if mood in self.ALL_MOODS:
            self.data["current"] = mood
            self.data.setdefault("history", []).append({
                "mood": mood, "time": datetime.now().isoformat()
            })
            self._save()
            return True
        return False

    def get_random_mood(self) -> str:
        return random.choice(self.ALL_MOODS)

    def get_style_modifier(self) -> str:
        mood = self.get_current()
        modifiers = {
            "兴奋": "语气非常兴奋，多用感叹号和表情符号",
            "愉快": "语气轻松愉快，带微笑",
            "平静": "语气平稳、理性",
            "好奇": "充满好奇心，多提问",
            "慵懒": "语气慵懒随意，有点不正经",
            "深沉": "语气深沉，有哲理性",
            "调皮": "语气调皮，爱开玩笑",
            "温柔": "语气温柔亲切",
            "毒舌": "毒舌模式，犀利幽默",
            "学究": "学究气，喜欢引经据典",
            "中二": "中二病模式，热血夸张",
            "佛系": "佛系模式，随缘淡然",
            "热血": "热血沸腾，充满激情"
        }
        return modifiers.get(mood, "语气平稳正常")

    def build_prompt_block(self) -> str:
        """构建用于 prompt 的心情描述块"""
        mood = self.get_current()
        modifier = self.get_style_modifier()
        return f"【当前心情】{mood}\n语气修饰: {modifier}"

    def shift(self, reason: str, delta: int):
        """根据事件偏移心情值。delta 为整数，正=上扬，负=下滑。
        心情按 ALL_MOODS 顺序从 0~12 编号，delta 会被 volatility 缩放。
        """
        mood = self.get_current()
        try:
            idx = self.ALL_MOODS.index(mood)
        except ValueError:
            idx = self.ALL_MOODS.index("平静")
        vol = float(self.data.get("volatility", 1.0))
        new_idx = max(0, min(len(self.ALL_MOODS) - 1, idx + int(round(delta * vol))))
        new_mood = self.ALL_MOODS[new_idx]
        if new_mood != mood:
            self.data["current"] = new_mood
            self.data.setdefault("history", []).append({
                "mood": new_mood, "time": datetime.now().isoformat(),
                "reason": reason, "delta": delta, "from": mood
            })
            self._save()

    def recheck(self):
        self.data = self._load()


# ===== UserProfileManager =====

class UserProfileManager:
    """用户档案与好感度系统"""

    def __init__(self, config: dict = None):
        self._cfg = config or _global_config
        self.file_path = USER_PROFILES_FILE
        self.data = self._load()

    def _load(self):
        return load_json_file(USER_PROFILES_FILE, {})

    def _save(self):
        return save_json_file(self.file_path, self.data)

    def get_profile(self, user_id: str) -> dict:
        return self.data.get(user_id, {})

    def update_profile(self, user_id: str, updates: dict):
        if user_id not in self.data:
            self.data[user_id] = {
                "first_seen": datetime.now().isoformat(),
                "interactions": 0, "affinity": 0.0
            }
        self.data[user_id].update(updates)
        self.data[user_id]["interactions"] = self.data[user_id].get("interactions", 0) + 1
        self.data[user_id]["last_seen"] = datetime.now().isoformat()
        self._save()

    def get_affinity(self, user_id: str) -> float:
        return self.data.get(user_id, {}).get("affinity", 0.0)

    def add_affinity(self, user_id: str, delta: float):
        prof = self.get_profile(user_id)
        new_val = max(-1.0, min(1.0, prof.get("affinity", 0.0) + delta))
        self.update_profile(user_id, {"affinity": new_val})

    def adjust_affinity(self, user_id: str, user_name: str, delta: int, note: str) -> dict:
        """调整用户好感度（兼容 xingye_bot/state.py 调用约定）"""
        prof = self.get_profile(user_id)
        if not prof:
            self.update_profile(user_id, {"name": user_name or "未知用户"})
            prof = self.get_profile(user_id)
        new_val = max(-1.0, min(1.0, prof.get("affinity", 0.0) + delta * 0.01))
        self.update_profile(user_id, {"affinity": new_val, "name": user_name or prof.get("name", "")})
        return prof

    def update_impression(self, user_id: str, user_name: str, impression: str) -> dict:
        """记录对用户的印象/评价"""
        prof = self.get_profile(user_id)
        if not prof:
            self.update_profile(user_id, {"name": user_name})
            prof = self.get_profile(user_id)
        if impression:
            prof["impression"] = impression[:120]
            self._save()
        return prof

    def get_all_users(self) -> list:
        return list(self.data.keys())

    def build_prompt_block(self, user_id: str, user_name: str = None) -> str:
        """构建用于 prompt 的用户档案描述块"""
        prof = self.get_profile(user_id)
        if not prof:
            return f"【用户档案】{user_name or user_id}: 新用户，尚无互动记录"
        affinity = prof.get("affinity", 0.0)
        interactions = prof.get("interactions", 0)
        first_seen = prof.get("first_seen", "未知")
        lines = [f"【用户档案】{user_name or user_id}: 好感度={affinity:.2f}, 互动次数={interactions}, 首次见面={first_seen}"]
        return "\n".join(lines)

    def recheck(self):
        self.data = self._load()


# ===== BotDiaryManager =====

class BotDiaryManager:
    """机器人日记 - 保存人工日记和自动复盘日记"""

    def __init__(self, config: dict = None):
        self._cfg = config or _global_config
        self.file_path = BOT_DIARY_FILE
        self.data = self._load()

    def _load(self):
        return load_json_file(BOT_DIARY_FILE, {"diaries": []})

    def _save(self):
        return save_json_file(self.file_path, self.data)

    def add_entry(self, content: str, entry_type: str = "auto"):
        self.data.setdefault("diaries", []).append({
            "type": entry_type, "content": content,
            "time": datetime.now().isoformat()
        })
        self._save()

    def get_entries(self, limit: int = 20, entry_type: str = None) -> list:
        entries = self.data.get("diaries", [])
        if entry_type:
            entries = [e for e in entries if e.get("type") == entry_type]
        return entries[-limit:]

    def get_recent_summary(self, count: int = 5) -> str:
        entries = self.get_entries(count)
        if not entries:
            return "暂无日记记录"
        return "\n---\n".join(e.get("content", "") for e in entries)

    def recheck(self):
        self.data = self._load()


# ===== SelfEvolutionManager =====

class SelfEvolutionManager:
    """自我进化 - 根据近期行为生成可控的人格微调建议"""

    def __init__(self, config: dict = None):
        self._cfg = config or _global_config
        self.file_path = SELF_EVOLUTION_FILE
        self.config = self._cfg
        self.data = self._load()

    def _load(self):
        return load_json_file(SELF_EVOLUTION_FILE, {"items": []})

    def _save(self):
        return save_json_file(self.file_path, self.data)

    def add_item(self, suggestion: str, category: str = "general"):
        self.data.setdefault("items", []).append({
            "category": category, "suggestion": suggestion,
            "time": datetime.now().isoformat()
        })
        self._save()

    def get_items(self, limit: int = 20) -> list:
        return self.data.get("items", [])[-limit:]

    def clear_items(self):
        self.data["items"] = []
        self._save()

    def get_active_suggestions(self) -> list:
        return [i for i in self.data.get("items", [])
                if i.get("status", "pending") == "pending"]

    def mark_applied(self, index: int):
        items = self.data.get("items", [])
        if 0 <= index < len(items):
            items[index]["status"] = "applied"
            self._save()

    def recheck(self):
        self.data = self._load()

    async def reflect(self, session_events, persona_prompt, current_mood, diary_entries=None):
        """自我反思进化 — AI生成人格微调建议
        Args:
            session_events: 本次会话事件列表
            persona_prompt: 当前人格提示
            current_mood: 当前心情
            diary_entries: 近期日记条目列表
        Returns:
            dict with keys: id, parsed{reflection, style_delta, relationship_delta, new_rule, mood_delta}
        """
        from openai import OpenAI
        import re as _re
        
        api_cfg = self._cfg.get("api", {})
        base_url = api_cfg.get("base_url", "")
        api_key = api_cfg.get("api_key", "")
        model = api_cfg.get("model_brain", "")
        
        if not base_url or not api_key:
            return {"id": len(self.data.get("items", [])), "parsed": {}, "raw": "API未配置"}
        
        # 构建事件摘要
        events_text = ""
        for i, evt in enumerate(session_events[-20:]):
            if isinstance(evt, dict):
                events_text += f"- {evt.get('type','event')}: {str(evt.get('summary',evt.get('text','')))[:200]}\n"
            else:
                events_text += f"- {str(evt)[:200]}\n"
        
        diary_text = ""
        if diary_entries:
            for d in diary_entries[-5:]:
                diary_text += f"- {str(d.get('content', d))[:200]}\n"
        
        prompt = (
            "你是一个AI角色的成长记录员。根据最近的互动和行为日志，对角色人格进行温和可控的微调建议。\n"
            "只输出严格JSON，字段：reflection(反思), style_delta(风格调整建议), "
            "relationship_delta(关系边界调整), new_rule(新增约束), mood_delta(心情变化值,-2到+2)。\n"
            f"当前人格：{persona_prompt}\n当前心情：{current_mood}\n"
            f"---\n最近互动记录：\n{events_text}\n"
            f"---\n近期日记：\n{diary_text}\n"
            "请分析趋势并给出建议JSON："
        )
        
        try:
            client = OpenAI(base_url=base_url, api_key=api_key, timeout=60.0)
            resp = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": "你是角色成长记录员，只提出温和、可控的性格演化建议。只输出JSON。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.5,
                max_tokens=600
            )
            raw = resp.choices[0].message.content.strip()
            # 尝试提取 JSON
            raw = raw.strip()
            if raw.startswith("```"):
                raw = _re.sub(r'^```\w*\n?', '', raw)
                raw = _re.sub(r'\n?```$', '', raw)
            parsed = json.loads(raw) if raw else {}
            
            item = {
                "id": len(self.data.get("items", [])),
                "category": "auto_reflect",
                "suggestion": parsed.get("reflection", ""),
                "parsed": parsed,
                "raw": raw,
                "time": datetime.now().isoformat(),
                "status": "pending"
            }
            self.data.setdefault("items", []).append(item)
            self._save()
            return item
        except Exception as e:
            from utils.display import log
            log(f"[EVOLVE] 自我进化反思失败: {e}", "WARN")
            return {"id": len(self.data.get("items", [])), "parsed": {
                "reflection": f"反思失败: {e}", "style_delta": "", "relationship_delta": "", "new_rule": "", "mood_delta": 0
            }, "raw": str(e)}
