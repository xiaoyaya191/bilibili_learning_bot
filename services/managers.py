"""services/managers.py — 管理类（Persona/Mood/UserProfile/BotDiary/SelfEvolution/PrivateContext/Entertainment）

每个类通过 __init__(config) 接收配置，使用 core.config 中的路径常量。
"""
import os, json, random, time
from datetime import datetime, timedelta
from colorama import Fore, Style
from core.config import (
    PERSONAS_FILE, MOOD_STATE_FILE, USER_PROFILES_FILE,
    BOT_DIARY_FILE, SELF_EVOLUTION_FILE, PRIVATE_CONTEXT_FILE,
    AGENT_SKILL_LOG_FILE, load_json_file, save_json_file
)


# ===== PrivateContextDB =====

class PrivateContextDB:
    """私信上下文数据库 - 每个用户的对话历史管理"""

    def __init__(self, config: dict = None):
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
        try:
            with open(self.file_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
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
        self.file_path = PERSONAS_FILE
        self.data = self._load()
        self.config = config or {}

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

    def recheck(self):
        self.data = self._load()


# ===== MoodManager =====

class MoodManager:
    """心情系统 - 根据互动结果动态调整当前心情"""

    ALL_MOODS = ["兴奋", "愉快", "平静", "好奇", "慵懒", "深沉",
                 "调皮", "温柔", "毒舌", "学究", "中二", "佛系", "热血"]

    def __init__(self, config: dict = None):
        self.file_path = MOOD_STATE_FILE
        self.config = config or {}
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

    def recheck(self):
        self.data = self._load()


# ===== UserProfileManager =====

class UserProfileManager:
    """用户档案与好感度系统"""

    def __init__(self, config: dict = None):
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

    def get_all_users(self) -> list:
        return list(self.data.keys())

    def recheck(self):
        self.data = self._load()


# ===== BotDiaryManager =====

class BotDiaryManager:
    """机器人日记 - 保存人工日记和自动复盘日记"""

    def __init__(self, config: dict = None):
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
        self.file_path = SELF_EVOLUTION_FILE
        self.config = config or {}
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


# ===== EntertainmentModule =====

class EntertainmentModule:
    """娱乐功能 - 每日运势、段子、热梗追踪等"""

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.enabled = self.config.get("entertainment", {}).get("enabled", False) if config else False
        self.fortune_count = 0
        self.max_daily_fortune = self.config.get("entertainment", {}).get("max_daily_fortune", 3) if config else 3

    def get_daily_fortune(self) -> str:
        fortunes = [
            "今天运势极佳，适合学习新知识！",
            "宜交友，可能会有有趣的评论互动~",
            "推荐看科技类视频，会有意外收获",
            "保持好奇心，今天会发现有趣的新UP主",
            "适合回顾老知识，温故而知新",
            "运程平稳，平常心刷视频就好",
            "今天适合尝试新的视频类型，拓宽视野",
        ]
        return random.choice(fortunes)

    def get_random_joke(self, mode: str = "normal") -> str:
        jokes = {
            "normal": [
                "为什么程序员总是搞混万圣节和圣诞节？因为 Oct 31 == Dec 25",
                "AI 和人的区别：AI 不会假装自己懂了",
            ],
            "geek": [
                "SIGINT 和 SIGTERM 的区别：一个是你妈喊你吃饭，一个是你爸关你电脑",
            ]
        }
        return random.choice(jokes.get(mode, jokes["normal"]))
