from __future__ import annotations

from dataclasses import dataclass

from .llm import ModelClient
from .memory import MemoryBank
from .safety import SafetyGuard
from .state import BotState
from .web_search import WebSearch


@dataclass
class VideoContext:
    title: str
    up_name: str = ""
    bvid: str = ""
    description: str = ""
    subtitles: str = ""
    comments: str = ""
    cover_url: str = ""


class BotSkills:
    def __init__(self, model: ModelClient, state: BotState, memory: MemoryBank | None = None, safety: SafetyGuard | None = None):
        self.model = model
        self.state = state
        self.memory = memory or MemoryBank()
        self.safety = safety or SafetyGuard()
        self.web_search = WebSearch()

    async def chat(self, text: str, user_id: str = "local", user_name: str = "本地用户") -> str:
        safety = self.safety.check(text, user_id=user_id, user_name=user_name)
        if safety["blocked"]:
            return "该用户已在本地黑名单中，已拒绝生成回复。"
        messages = [
            {"role": "system", "content": self.state.persona_prompt_block()},
            {"role": "system", "content": self.state.user_prompt_block(user_id, user_name)},
            {"role": "system", "content": self.memory.prompt_block(text, user_id=user_id)},
            {"role": "user", "content": text},
        ]
        answer = await self.model.chat(messages, purpose="web-chat")
        self.memory.add(f"用户 {user_name}: {text}\nbilibili_learning_bot: {answer}", user_id=user_id, thread_id="web-chat")
        if safety["risk"] == "low":
            self.state.adjust_affinity(user_id, user_name, 1, "正常互动")
            self.state.nudge_mood(1, event="完成一次正常聊天")
        elif safety["risk"] == "medium":
            self.state.adjust_affinity(user_id, user_name, -2, "互动里出现风险词")
            self.state.nudge_mood(-2, "警觉", "检测到中等风险互动")
        return answer

    async def plan_reply(self, comment_text: str, user_id: str = "", user_name: str = "") -> dict[str, str]:
        safety = self.safety.check(comment_text, user_id=user_id, user_name=user_name)
        if safety["blocked"] or safety["risk"] == "high":
            return {"raw": "{}", "risk": safety["risk"], "blocked": str(safety["blocked"])}
        template = str(self.state.templates().get("comment_reply") or "").strip()
        if not template:
            raise ValueError("请先在提示词设置中填写评论回复提示词")
        prompt = (
            f"{template}\n"
            "只返回 JSON，字段为 reply、tone、risk。risk 只能是 low/medium/high。\n"
            f"评论内容：{comment_text}"
        )
        text = await self.model.chat([
            {"role": "system", "content": self.state.persona_prompt_block()},
            {"role": "system", "content": self.state.user_prompt_block(user_id, user_name)},
            {"role": "system", "content": self.memory.prompt_block(comment_text, user_id=user_id)},
            {"role": "user", "content": prompt},
        ], purpose="comment-reply")
        self.memory.add(f"评论回复草稿对象 {user_name}: {comment_text}\n草稿: {text}", user_id=user_id or "comment", thread_id="comment")
        self.state.adjust_affinity(user_id or "comment", user_name or "评论用户", 1, "生成过评论回复草稿")
        return {"raw": text}

    async def plan_reply_with_image(self, comment_text: str, image_url: str, user_id: str = "", user_name: str = "") -> dict[str, str]:
        safety = self.safety.check(comment_text, user_id=user_id, user_name=user_name)
        if safety["blocked"] or safety["risk"] == "high":
            return {"raw": "{}", "risk": safety["risk"], "blocked": str(safety["blocked"])}
        text = await self.model.chat([
            {"role": "system", "content": self.state.persona_prompt_block()},
            {"role": "system", "content": self.memory.prompt_block(comment_text, user_id=user_id)},
            {"role": "user", "content": [
                {"type": "text", "text": "请按照当前人格和用户提示词，结合评论文字与图片的可确认事实生成回复。只返回 JSON：reply、tone、risk。"},
                {"type": "text", "text": f"评论：{comment_text}"},
                {"type": "image_url", "image_url": {"url": image_url}},
            ]},
        ], model_role="vision", purpose="comment-image-reply")
        self.memory.add(f"图片评论回复草稿对象 {user_name}: {comment_text}\n图片: {image_url}\n草稿: {text}", user_id=user_id or "comment", thread_id="comment-image")
        return {"raw": text}

    async def summarize_video(self, video: VideoContext) -> str:
        content = (
            f"标题：{video.title}\nUP：{video.up_name}\nBV：{video.bvid}\n"
            f"简介：{video.description[:1200]}\n字幕：{video.subtitles[:6000]}\n热门评论：{video.comments[:2000]}"
        )
        return await self.model.chat([
            {"role": "system", "content": "你是视频学习助手，擅长提炼知识点、争议点、情绪倾向和可行动笔记。"},
            {"role": "user", "content": content + "\n\n请输出：一句话总结、知识点、值得追问的问题、适合收藏的理由。"},
        ], purpose="video-summary")

    async def dynamic_draft(self, topic: str, source_note: str = "") -> str:
        template = str(self.state.templates().get("dynamic_draft") or "").strip()
        if not template:
            raise ValueError("请先在提示词设置中填写动态草稿提示词")
        return await self.model.chat([
            {"role": "system", "content": self.state.persona_prompt_block()},
            {"role": "user", "content": f"{template}\n主题：{topic}\n素材：{source_note}"},
        ], purpose="dynamic-draft")

    async def image_prompt(self, idea: str) -> str:
        return await self.model.chat([
            {"role": "system", "content": "你是视觉提示词设计师，输出适合图像模型的中文提示词，不要生成图片。"},
            {"role": "user", "content": f"把这个想法改写成图像生成提示词：{idea}"},
        ], model_role="image", purpose="image-prompt")

    async def generate_image(self, idea: str, size: str = "1024x1024") -> dict:
        prompt = await self.image_prompt(idea)
        image = await self.model.generate_image(prompt, size=size)
        return {"prompt": prompt, "image": image}

    async def search_brief(self, query: str) -> str:
        results = await self.web_search.search(query, limit=5)
        if results:
            context = "\n".join(f"{i + 1}. {r.title}\n{r.url}\n{r.snippet}" for i, r in enumerate(results))
            return await self.model.chat([
                {"role": "system", "content": "你是联网检索助手。必须基于给定搜索结果回答，并指出仍需核验的不确定点。"},
                {"role": "user", "content": f"问题：{query}\n\n搜索结果：\n{context}"},
            ], model_role="fast", purpose="web-search-answer")
        return await self.model.chat([
            {"role": "system", "content": "你是检索规划助手。当前没有搜索结果，请给出搜索关键词、可信来源类型和核验清单。"},
            {"role": "user", "content": query},
        ], model_role="fast", purpose="search-plan")


# ===== 持久化技能库 =====
import json
from pathlib import Path
from datetime import datetime


class SkillBank:
    """持久化的 AI 技能库，越用越聪明。"""

    def __init__(self, data_dir=None):
        if data_dir is None:
            try:
                from core.user_data import DATA_DIR
                data_dir = DATA_DIR
            except Exception:
                data_dir = Path(".")
        self.data_dir = Path(data_dir)
        self.skills_file = self.data_dir / "skills.json"
        self.skills = self._load()

    def _load(self):
        try:
            if self.skills_file.exists():
                return json.loads(self.skills_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _save(self):
        try:
            self.skills_file.parent.mkdir(parents=True, exist_ok=True)
            self.skills_file.write_text(json.dumps(self.skills, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def add(self, topic, skill_text, source_bvid="", score=0):
        """添加一条技能。"""
        skill = {
            "topic": topic[:50],
            "skill": skill_text[:500],
            "source_bvid": source_bvid,
            "score": score,
            "created_at": datetime.now().isoformat(),
            "used_count": 0,
        }
        # 去重：同主题的更新
        existing = [s for s in self.skills if s.get("topic") == topic]
        if existing:
            existing[0].update(skill)
        else:
            self.skills.append(skill)
        self._save()

    def get_relevant(self, topic="", limit=5):
        """获取和主题相关的技能。"""
        if not self.skills:
            return []
        if topic:
            relevant = [s for s in self.skills if topic.lower() in s.get("topic", "").lower() or s.get("topic", "").lower() in topic.lower()]
            if relevant:
                return relevant[:limit]
        return sorted(self.skills, key=lambda x: x.get("used_count", 0), reverse=True)[:limit]

    def prompt_block(self, topic=""):
        """生成注入到 AI prompt 的技能块。"""
        relevant = self.get_relevant(topic)
        if not relevant:
            return ""
        lines = ["[已掌握的相关技能]"]
        for s in relevant:
            lines.append(f"- {s['topic']}: {s['skill'][:100]}")
        return "\n".join(lines)

    def increment_use(self, topic):
        """增加技能使用次数。"""
        for s in self.skills:
            if s.get("topic") == topic:
                s["used_count"] = s.get("used_count", 0) + 1
                break
        self._save()
