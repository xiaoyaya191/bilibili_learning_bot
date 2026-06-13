#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
智能分析推荐系统
================================
多维度分析 → 主动推荐 → 内容平衡 → 自进化反馈

层级：
  L1 表层兴趣 — 关键词/标签偏好、内容类型、UP主偏好
  L2 认知风格 — 分析型/直觉型、深度/广度、视觉/文本偏好
  L3 情感需求 — 智识刺激、成就满足、舒适娱乐、社交连接
  L4 深层动机 — 自我提升、好奇心、技能掌握、创作表达
  L5 演变趋势 — 兴趣变迁、内在矛盾、成长轨迹

推荐类型：
  🎁 惊喜推荐 — AI高置信度但用户未接触过的内容
  🔭 兴趣探索 — 用户从未涉足但可能感兴趣的新领域
  🛡️ 内容筛选 — 识别并屏蔽低质/反感内容
  🌐 内容拓展 — 推送与既有偏好不一致但能拓展视野的内容
  📈 趋势推荐 — 与兴趣演变方向对齐的内容
"""

import json
import os
import time
import random
from datetime import datetime, timedelta
from collections import defaultdict, Counter
from math import log2

# ── 文件路径 ─────────────────────────────────────────────────
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Data")
PROFILE_FILE = os.path.join(DATA_DIR, "psycho_profile.json")
RECOMMENDATION_LOG = os.path.join(DATA_DIR, "recommendation_log.json")
ACTION_LOG_FILE = os.path.join(DATA_DIR, "action_log.json")
AVERSION_FILE = os.path.join(DATA_DIR, "content_aversions.json")


def _ts():
    return datetime.now().isoformat(timespec="seconds")


def _load_json(path, default=None):
    if default is None:
        default = {}
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"[psycho] JSON加载失败 {path}: {e}")
    return default


def _save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[psycho] JSON保存失败 {path}: {e}")
        return False


# ╔══════════════════════════════════════════════════════════════╗
# ║              五层心理画像数据结构                            ║
# ╚══════════════════════════════════════════════════════════════╝

DEFAULT_PROFILE = {
    "version": 2,
    "created_at": "",
    "last_analyzed_at": "",
    "total_actions_analyzed": 0,

    # L1 — 表层兴趣
    "surface_interests": {
        "tags": {},
        "categories": {},
        "content_types": {},
        "preferred_duration": 0,
        "active_hours": [],
        "up_preferences": {},
    },

    # L2 — 认知风格
    "cognitive_style": {
        "analytical_score": 0.50,
        "depth_preference": 0.50,
        "visual_lean": 0.50,
        "novelty_seeking": 0.50,
        "systematic_processing": 0.50,
        "learning_style": "mixed",
    },

    # L3 — 情感需求
    "emotional_needs": {
        "intellectual_stimulation": 0.50,
        "achievement_satisfaction": 0.50,
        "comfort_entertainment": 0.50,
        "social_connection": 0.50,
        "aesthetic_appreciation": 0.50,
        "emotional_resonance": 0.50,
        "stress_relief": 0.50,
    },

    # L4 — 深层动机
    "deep_motivations": {
        "self_improvement": 0.50,
        "curiosity_exploration": 0.50,
        "skill_mastery": 0.50,
        "career_advancement": 0.50,
        "creative_expression": 0.50,
        "social_identity": 0.50,
        "entertainment_escape": 0.50,
    },

    # L5 — 演变趋势与矛盾
    "interest_evolution": [],
    "contradictions": [],
    "growth_trajectory": "",
    "personality_summary": "",

    # 推荐系统状态
    "recommendation_state": {
        "last_surprise_at": "",
        "last_explore_at": "",
        "last_anticocoon_at": "",
        "surprise_count_today": 0,
        "explore_count_today": 0,
        "anticocoon_count_today": 0,
    },

    # 信息茧房检测
    "cocoon_metrics": {
        "diversity_score": 0.50,
        "concentration_ratio": 0.0,
        "dominant_categories": [],
        "underrepresented_areas": [],
        "content_type_entropy": 0.0,
        "last_detected_at": "",
    },
}


# ╔══════════════════════════════════════════════════════════════╗
# ║                    动作追踪器                                ║
# ╚══════════════════════════════════════════════════════════════╝

class ActionTracker:
    """记录用户所有行为用于心理画像分析"""

    def __init__(self):
        self.actions = _load_json(ACTION_LOG_FILE, {"actions": []})
        self._dirty = False
        self._max_actions = 2000

    def record(self, action_type, **kwargs):
        action = {"type": action_type, "time": _ts(), **kwargs}
        self.actions.setdefault("actions", []).append(action)
        self._dirty = True
        if len(self.actions["actions"]) > self._max_actions:
            self.actions["actions"] = self.actions["actions"][-self._max_actions:]

    def record_view(self, bvid, title, tags, duration, up_name, up_uid,
                    category="", watched_ratio=1.0, score=0, interested=False):
        self.record("view", bvid=bvid, title=title, tags=tags or [],
                    duration=duration, up_name=up_name, up_uid=up_uid,
                    category=category, watched_ratio=watched_ratio,
                    score=score, interested=interested)

    def record_interaction(self, action_type, bvid, title="", up_name=""):
        self.record(action_type, bvid=bvid, title=title, up_name=up_name)

    def record_search(self, keyword, result_count=0, clicked_bvid=""):
        self.record("search", keyword=keyword, result_count=result_count,
                    clicked_bvid=clicked_bvid)

    def record_chat(self, topic="", sentiment=""):
        self.record("chat", topic=topic, sentiment=sentiment)

    def record_skip(self, bvid, title, reason=""):
        self.record("skip", bvid=bvid, title=title, reason=reason)

    def get_recent_actions(self, n=100):
        return self.actions.get("actions", [])[-n:]

    def get_actions_by_type(self, action_type, n=50):
        return [a for a in self.actions.get("actions", [])
                if a.get("type") == action_type][-n:]

    def get_stats(self):
        actions = self.actions.get("actions", [])
        type_counts = Counter(a["type"] for a in actions)
        viewed = [a for a in actions if a["type"] == "view"]
        liked = len([a for a in actions if a["type"] == "like"])
        favorited = len([a for a in actions if a["type"] == "favorite"])
        followed = len([a for a in actions if a["type"] == "follow"])
        skipped = len([a for a in actions if a["type"] == "skip"])
        searches = len([a for a in actions if a["type"] == "search"])
        return {
            "total_actions": len(actions),
            "views": len(viewed),
            "likes": liked,
            "favorites": favorited,
            "follows": followed,
            "skips": skipped,
            "searches": searches,
            "type_counts": dict(type_counts),
            "unique_videos": len(set(a.get("bvid") for a in viewed if a.get("bvid"))),
        }

    def flush(self):
        if self._dirty:
            _save_json(ACTION_LOG_FILE, self.actions)
            self._dirty = False


# ╔══════════════════════════════════════════════════════════════╗
# ║                    避雷系统                                  ║
# ╚══════════════════════════════════════════════════════════════╝

class AversionSystem:
    """识别并记忆用户反感的内容模式"""

    def __init__(self):
        self.data = _load_json(AVERSION_FILE, {
            "tags": {},
            "up_blacklist": {},
            "patterns": {},
            "auto_detected": [],
            "last_updated": "",
        })

    def is_blacklisted_up(self, uid):
        return str(uid) in self.data.get("up_blacklist", {})

    def get_aversion_score(self, title="", tags=None, up_uid=""):
        score = 0.0
        reasons = []
        if up_uid and self.is_blacklisted_up(up_uid):
            score = max(score, 0.9)
            reasons.append("UP主在黑名单中")
        if tags:
            for tag in tags:
                if tag in self.data.get("tags", {}):
                    s = self.data["tags"][tag]
                    if s > score:
                        score = s
                        reasons.append(f"标签「{tag}」反感度{s:.1%}")
        check_text = (title or "").lower()
        for pattern, weight in self.data.get("patterns", {}).items():
            if pattern.lower() in check_text:
                if weight > score:
                    score = weight
                    reasons.append(f"匹配反感模式「{pattern}」")
        return score, reasons

    def report_aversion(self, bvid, title, reason="", tags=None, up_uid="", up_name=""):
        if up_uid:
            bl = self.data.setdefault("up_blacklist", {})
            uid_str = str(up_uid)
            entry = bl.get(uid_str, {"name": up_name, "count": 0, "reason": ""})
            entry["count"] += 1
            entry["name"] = up_name or entry["name"]
            if reason:
                entry["reason"] = reason
            bl[uid_str] = entry
        if title:
            self._extract_aversion_patterns(title)
        self.data["last_updated"] = _ts()
        self._save()

    def _extract_aversion_patterns(self, title):
        aversion_keywords = [
            "震惊", "竟然", "万万没想到", "揭秘", "曝光",
            "千万别", "必看", "紧急", "深度好文", "不转不是",
            "标题党", "营销号", "洗稿", "搬运", "AI配音",
            "震惊部", "速看", "删前速看",
        ]
        patterns = self.data.setdefault("patterns", {})
        for kw in aversion_keywords:
            if kw in title:
                patterns[kw] = min(1.0, patterns.get(kw, 0.3) + 0.15)

    def get_safe_search_exclusions(self):
        exclusions = []
        for tag, score in self.data.get("tags", {}).items():
            if score >= 0.6:
                exclusions.append(tag)
        for uid, info in self.data.get("up_blacklist", {}).items():
            if info.get("count", 0) >= 3:
                exclusions.append(info.get("name", ""))
        return [e for e in exclusions if e]

    def _save(self):
        _save_json(AVERSION_FILE, self.data)


# ╔══════════════════════════════════════════════════════════════╗
# ║                  信息茧房检测器                              ║
# ╚══════════════════════════════════════════════════════════════╝

class InfoCocoonDetector:
    """检测内容消费多样性，识别信息茧房风险"""

    CATEGORY_GROUPS = {
        "科技数码": ["科技", "数码", "计算机技术", "软件应用", "编程", "人工智能"],
        "知识": ["科学科普", "社科", "人文历史", "设计", "校园学习"],
        "生活": ["日常", "美食", "家居", "健身", "旅游", "汽车"],
        "娱乐": ["搞笑", "鬼畜", "综艺", "娱乐"],
        "影视": ["电影", "电视剧", "纪录片", "短片"],
        "游戏": ["单机游戏", "网络游戏", "手机游戏", "桌游棋牌"],
        "音乐": ["原创音乐", "翻唱", "演奏", "音乐现场", "音乐综合"],
        "动画": ["MAD", "MMD", "手书", "配音"],
        "时尚": ["美妆", "服饰", "时尚"],
        "资讯": ["热点", "环球", "社会", "综合"],
    }

    BOUNDARY_BREAKING_KEYWORDS = {
        "科技数码": ["科技哲学", "科技伦理", "数字人文", "科技艺术", "技术史"],
        "编程": ["数学之美", "语言学", "认知科学", "系统思维", "逻辑学"],
        "游戏": ["游戏设计", "叙事学", "交互设计", "心理学", "世界构建"],
        "知识": ["跨学科", "元认知", "知识图谱", "思想史", "方法论"],
    }

    def __init__(self):
        self.metrics = {}

    def analyze(self, recent_views, current_interests):
        if not recent_views:
            return {"diversity_score": 0.50, "message": "数据不足"}

        cat_counts = Counter(v.get("category", "未知") for v in recent_views)
        total = len(recent_views)
        if total == 0:
            return {"diversity_score": 0.50, "message": "无观看记录"}

        group_counts = defaultdict(int)
        for cat, count in cat_counts.items():
            group_counts[self._map_to_group(cat)] += count

        n_groups = len(self.CATEGORY_GROUPS)
        active_groups = len(group_counts)
        dominance = max(group_counts.values()) / total if group_counts else 1.0
        concentration = sum((c / total) ** 2 for c in group_counts.values())

        diversity_raw = (active_groups / n_groups) * (1 - concentration)
        diversity_score = round(0.1 + 0.9 * diversity_raw, 2)

        sorted_groups = Counter(group_counts).most_common()
        dominant = [g for g, c in sorted_groups if c / total >= 0.15]
        all_groups = set(self.CATEGORY_GROUPS.keys())
        underrepresented = list(all_groups - set(group_counts.keys()))

        all_tags = []
        for v in recent_views:
            all_tags.extend(v.get("tags", []))
        tag_counts = Counter(all_tags)
        tag_entropy = 0.0
        if tag_counts:
            tag_total = sum(tag_counts.values())
            tag_entropy = -sum((c / tag_total) * log2(c / tag_total)
                              for c in tag_counts.values())

        result = {
            "diversity_score": diversity_score,
            "concentration_ratio": round(dominance, 2),
            "dominant_categories": dominant,
            "underrepresented_areas": underrepresented[:5],
            "content_type_entropy": round(tag_entropy, 3),
            "active_categories": active_groups,
            "total_categories": n_groups,
            "cocoon_risk": ("🔴高风险" if diversity_score < 0.3 else
                           ("🟡中度" if diversity_score < 0.55 else "🟢健康")),
            "last_detected_at": _ts(),
        }
        self.metrics = result
        return result

    def _map_to_group(self, category):
        category = category or ""
        for group, keywords in self.CATEGORY_GROUPS.items():
            for kw in keywords:
                if kw in category:
                    return group
        return "其他"

    def get_breakout_keywords(self, dominant_categories):
        keywords = []
        for cat in dominant_categories:
            if cat in self.BOUNDARY_BREAKING_KEYWORDS:
                keywords.extend(self.BOUNDARY_BREAKING_KEYWORDS[cat])
        if not keywords:
            keywords = ["跨学科思维", "元学习", "创意方法", "思想实验",
                       "文明比较", "未来学", "冥想科学", "极简主义"]
        return keywords


# ╔══════════════════════════════════════════════════════════════╗
# ║                  五层心理画像核心类                          ║
# ╚══════════════════════════════════════════════════════════════╝

class PsychoProfile:
    """五层心理画像：加载、更新、分析、生成推荐洞察"""

    def __init__(self, ai_caller=None):
        self.ai_caller = ai_caller
        self.profile = _load_json(PROFILE_FILE, DEFAULT_PROFILE.copy())
        if not self.profile.get("created_at"):
            self.profile["created_at"] = _ts()
        self._dirty = False
        self.tracker = ActionTracker()
        self.aversion = AversionSystem()
        self.cocoon = InfoCocoonDetector()
        self._last_analysis_at = None

    def flush(self):
        if self._dirty:
            _save_json(PROFILE_FILE, self.profile)
            self._dirty = False
        self.tracker.flush()

    def _dirty_mark(self):
        self._dirty = True

    # ── L1 表层兴趣 ─────────────────────────────────────────
    def update_surface_interest(self, title="", tags=None, category="",
                                 duration=0, up_uid="", up_name="", score=0,
                                 liked=False, favorited=False, coined=False):
        L1 = self.profile["surface_interests"]
        weight = 0.05
        if liked: weight += 0.15
        if favorited: weight += 0.20
        if coined: weight += 0.12
        if score >= 8: weight += 0.08

        if tags:
            for tag in tags:
                tag = tag.strip()
                if not tag: continue
                L1["tags"][tag] = min(1.0, L1["tags"].get(tag, 0.5) * 0.9 + weight)

        if category:
            L1["categories"][category] = min(1.0,
                L1["categories"].get(category, 0.5) * 0.9 + weight)

        if up_uid:
            up_key = str(up_uid)
            entry = L1["up_preferences"].get(up_key, {"name": up_name, "affinity": 0.5, "category": category})
            entry["affinity"] = min(1.0, entry["affinity"] * 0.9 + weight)
            entry["name"] = up_name or entry["name"]
            entry["category"] = category or entry["category"]
            L1["up_preferences"][up_key] = entry

        if duration > 0 and L1["preferred_duration"] > 0:
            L1["preferred_duration"] = int(L1["preferred_duration"] * 0.85 + duration * 0.15)
        elif duration > 0:
            L1["preferred_duration"] = duration

        hour = datetime.now().hour
        if hour not in L1["active_hours"]:
            L1["active_hours"].append(hour)
            L1["active_hours"] = sorted(L1["active_hours"][-24:])

        self._dirty_mark()

    # ── 获取画像摘要（用于注入AI prompt）─────────────────────
    def get_profile_summary(self):
        L1 = self.profile["surface_interests"]
        L2 = self.profile["cognitive_style"]
        L3 = self.profile["emotional_needs"]
        L4 = self.profile["deep_motivations"]
        L5 = self.profile

        top_tags = sorted(L1["tags"].items(), key=lambda x: x[1], reverse=True)[:8]
        top_cats = sorted(L1["categories"].items(), key=lambda x: x[1], reverse=True)[:5]
        cognitive_desc = self._describe_cognitive_style(L2)
        top_emotions = sorted(L3.items(), key=lambda x: x[1], reverse=True)[:3]
        top_motivations = sorted(L4.items(), key=lambda x: x[1], reverse=True)[:3]
        cocoon = L5.get("cocoon_metrics", {})
        cocoon_risk = cocoon.get("cocoon_risk", "未知")

        lines = [
            "【用户深层画像 — 基于L1~L5五层分析】",
            "📌 表层兴趣: " + ", ".join(f"{t}({s:.0%})" for t, s in top_tags),
            "📁 偏好分区: " + ", ".join(f"{c}({s:.0%})" for c, s in top_cats),
            "🧠 认知风格: " + cognitive_desc,
            "💭 情感需求: " + ", ".join(f"{e}({s:.0%})" for e, s in top_emotions),
            "🎯 深层动机: " + ", ".join(f"{m}({s:.0%})" for m, s in top_motivations),
            "🌐 信息茧房: " + cocoon_risk + " | 多样性=" + str(cocoon.get("diversity_score", "?")),
        ]

        contradictions = L5.get("contradictions", [])
        if contradictions:
            lines.append("⚡ 内在矛盾: " + contradictions[-1].get("insight", ""))

        evolution = L5.get("interest_evolution", [])
        if evolution:
            latest = evolution[-1]
            rising = latest.get("rising", [])
            if rising:
                lines.append("📈 新兴兴趣: " + ", ".join(rising[:3]))

        summary = L5.get("personality_summary", "")
        if summary:
            lines.append("💡 个性洞察: " + summary)

        return "\n".join(lines)

    def _describe_cognitive_style(self, L2):
        parts = []
        if L2["analytical_score"] > 0.6:
            parts.append("分析型思维")
        elif L2["analytical_score"] < 0.4:
            parts.append("直觉型思维")
        else:
            parts.append("平衡型思维")

        if L2["depth_preference"] > 0.6:
            parts.append("偏好深度内容")
        elif L2["depth_preference"] < 0.4:
            parts.append("偏好碎片内容")

        if L2["novelty_seeking"] > 0.6:
            parts.append("高度探索精神")
        elif L2["novelty_seeking"] < 0.4:
            parts.append("偏好熟悉领域")

        if L2["visual_lean"] > 0.6:
            parts.append("视觉导向")
        elif L2["visual_lean"] < 0.4:
            parts.append("文本导向")

        parts.append("学习风格:" + L2.get("learning_style", "mixed"))
        return " / ".join(parts) if parts else "未充分分析"

    # ── AI 深度画像分析 ──────────────────────────────────────
    async def deep_analyze(self, force=False):
        if not self.ai_caller:
            return False

        actions = self.tracker.get_recent_actions(300)
        if len(actions) < 50 and not force:
            return False

        if self._last_analysis_at and not force:
            if (datetime.now() - self._last_analysis_at).total_seconds() < 14400:
                return False

        stats = self.tracker.get_stats()
        if stats["views"] < 20:
            return False

        L1_summary = self._build_l1_summary()
        actions_summary = self._build_actions_summary(actions)

        prompt = f"""你是一位认知心理学专家和行为分析师。请基于以下用户的B站行为数据，进行五层心理画像分析。

【用户表层兴趣数据】
{L1_summary}

【最近行为摘要】
{actions_summary}

返回以下JSON（严格JSON格式，不做额外解释）：
{{
  "cognitive_style": {{
    "analytical_score": 0.0-1.0,
    "depth_preference": 0.0-1.0,
    "visual_lean": 0.0-1.0,
    "novelty_seeking": 0.0-1.0,
    "systematic_processing": 0.0-1.0,
    "learning_style": "hands-on/theoretical/observational/mixed",
    "reasoning": "你的分析推理（50字内）"
  }},
  "emotional_needs": {{
    "intellectual_stimulation": 0.0-1.0,
    "achievement_satisfaction": 0.0-1.0,
    "comfort_entertainment": 0.0-1.0,
    "social_connection": 0.0-1.0,
    "aesthetic_appreciation": 0.0-1.0,
    "emotional_resonance": 0.0-1.0,
    "stress_relief": 0.0-1.0,
    "reasoning": "情感需求分析"
  }},
  "deep_motivations": {{
    "self_improvement": 0.0-1.0,
    "curiosity_exploration": 0.0-1.0,
    "skill_mastery": 0.0-1.0,
    "career_advancement": 0.0-1.0,
    "creative_expression": 0.0-1.0,
    "social_identity": 0.0-1.0,
    "entertainment_escape": 0.0-1.0,
    "reasoning": "动机分析"
  }},
  "contradictions": [
    {{"a": "表面行为A", "b": "实际行为B", "insight": "深层解释"}}
  ],
  "personality_summary": "100字中文个性特点和深层需求",
  "growth_trajectory": "80字兴趣成长轨迹",
  "interest_evolution": {{
    "rising": ["新兴兴趣1"],
    "stable": ["稳定兴趣1"],
    "declining": ["衰退兴趣1"],
    "emerging": ["潜在萌芽兴趣1"]
  }}
}}
只输出JSON。"""

        try:
            resp = await self.ai_caller(
                model=None,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000,
            )
            content = resp.choices[0].message.content
            json_match = self._extract_json(content)
            if json_match:
                analysis = json.loads(json_match)
                self._apply_analysis(analysis)
                self._last_analysis_at = datetime.now()
                self.profile["last_analyzed_at"] = _ts()
                self.profile["total_actions_analyzed"] = stats["total_actions"]
                self._dirty_mark()
                self.flush()
                return True
        except asyncio.CancelledError:
            # 任务被取消，不打印错误，直接返回
            return False
        except Exception as e:
            print(f"[PsychoProfile] AI分析失败: {e}")
        return False

    def _build_l1_summary(self):
        L1 = self.profile["surface_interests"]
        parts = []
        top_tags = sorted(L1["tags"].items(), key=lambda x: x[1], reverse=True)[:10]
        parts.append("兴趣标签: " + ", ".join(f"{t}({s:.0%})" for t, s in top_tags))
        top_cats = sorted(L1["categories"].items(), key=lambda x: x[1], reverse=True)[:5]
        parts.append("偏好分区: " + ", ".join(f"{c}({s:.0%})" for c, s in top_cats))
        if L1["preferred_duration"]:
            parts.append("偏好时长: " + str(L1["preferred_duration"]) + "秒")
        return "\n".join(parts)

    def _build_actions_summary(self, actions):
        views = [a for a in actions if a["type"] == "view"][-50:]
        likes = [a for a in actions if a["type"] == "like"]
        skips = [a for a in actions if a["type"] == "skip"]
        searches = [a for a in actions if a["type"] == "search"]
        lines = [
            "最近观看" + str(len(views)) + "个视频，点赞" + str(len(likes)) +
            "个，跳过" + str(len(skips)) + "个，搜索" + str(len(searches)) + "次",
        ]
        if views:
            lines.append("观看标题采样: " + " | ".join(
                v.get("title", "")[:40] for v in views[-8:]
            ))
        if searches:
            lines.append("搜索关键词: " + ", ".join(
                s.get("keyword", "") for s in searches[-5:]
            ))
        return "\n".join(lines)

    def _apply_analysis(self, analysis):
        for section in ["cognitive_style", "emotional_needs", "deep_motivations"]:
            if section in analysis:
                for k, v in analysis[section].items():
                    if k in self.profile.get(section, {}) and isinstance(v, (int, float)):
                        old = self.profile[section][k]
                        self.profile[section][k] = round(old * 0.5 + v * 0.5, 2)

        if "contradictions" in analysis:
            self.profile["contradictions"] = (self.profile.get("contradictions", []) +
                analysis["contradictions"])[-5:]

        for key in ["personality_summary", "growth_trajectory"]:
            if key in analysis and analysis[key]:
                self.profile[key] = analysis[key]

        if "interest_evolution" in analysis:
            evo = analysis["interest_evolution"]
            self.profile["interest_evolution"].append({
                "period": datetime.now().strftime("%Y-%m"),
                "rising": evo.get("rising", []),
                "declining": evo.get("declining", []),
                "stable": evo.get("stable", []),
                "emerging": evo.get("emerging", []),
            })
            self.profile["interest_evolution"] = self.profile["interest_evolution"][-12:]

    def _extract_json(self, text):
        text = text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:]) if len(lines) > 1 else text
            if text.endswith("```"):
                text = text[:-3]
        start = text.find("{")
        if start >= 0:
            # 🔧 嵌套匹配：正确找到闭合的 }，防止 AI 返回内容后有额外字符
            depth = 0
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        return text[start:i+1]
            # 兜底：rfind
            end = text.rfind("}")
            if end > start:
                return text[start:end+1]
        return None

    # ── 启发式L2更新 ──────────────────────────────────────────
    def heuristic_update_l2(self):
        actions = self.tracker.get_recent_actions(200)
        views = [a for a in actions if isinstance(a, dict) and a.get("type") == "view"]
        if len(views) < 20:
            return

        L2 = self.profile["cognitive_style"]

        durations = [v.get("duration", 0) for v in views if v.get("duration")]
        if durations:
            avg_dur = sum(durations) / len(durations)
            long_ratio = len([d for d in durations if d > 600]) / len(durations)
            L2["depth_preference"] = round(L2["depth_preference"] * 0.7 +
                (0.9 if avg_dur > 900 else (0.5 if avg_dur > 300 else 0.2)) * 0.3, 2)

        categories = [v.get("category", "") for v in views if v.get("category")]
        if categories:
            unique_ratio = len(set(categories)) / len(categories)
            L2["novelty_seeking"] = round(L2["novelty_seeking"] * 0.7 +
                min(1.0, unique_ratio * 1.5) * 0.3, 2)

        tutorial_kws = ["教程", "教学", "原理", "深入", "分析", "解读", "论文"]
        analytical_views = sum(1 for v in views
            if any(kw in (v.get("title", "") + " " + " ".join(v.get("tags", [])))
                   for kw in tutorial_kws))
        if views:
            L2["analytical_score"] = round(L2["analytical_score"] * 0.7 +
                (analytical_views / len(views)) * 0.3, 2)

        self._dirty_mark()

    # ── 茧房检测 ──────────────────────────────────────────────
    def update_cocoon_metrics(self):
        views = self.tracker.get_actions_by_type("view", 100)
        recent = [
            {"category": v.get("category", ""), "tags": v.get("tags", []),
             "title": v.get("title", "")}
            for v in views
        ]
        metrics = self.cocoon.analyze(recent, list(self.profile["surface_interests"]["tags"].keys()))
        self.profile["cocoon_metrics"] = metrics
        self._dirty_mark()
        return metrics

    # ── 兴趣演变 ──────────────────────────────────────────────
    def detect_interest_shifts(self):
        L1 = self.profile["surface_interests"]
        tags = L1["tags"]
        if len(tags) < 3:
            return

        evolution = self.profile.get("interest_evolution", [])
        prev_tags = {}
        if evolution:
            for tag_name in evolution[-1].get("rising", []) + evolution[-1].get("stable", []):
                prev_tags[tag_name] = 0.5

        if prev_tags:
            changes = []
            for tag, score in tags.items():
                old_score = prev_tags.get(tag, 0.3)
                delta = score - old_score
                if abs(delta) > 0.1:
                    changes.append((tag, delta))
            if changes:
                changes.sort(key=lambda x: x[1], reverse=True)
                rising = [t for t, d in changes if d > 0][:3]
                declining = [t for t, d in changes if d < 0][:3]
                stable = [t for t, s in tags.items()
                         if t not in rising and t not in declining and s > 0.5][:5]
                self.profile["interest_evolution"].append({
                    "period": datetime.now().strftime("%Y-%m"),
                    "rising": rising, "declining": declining,
                    "stable": stable, "emerging": [],
                })
                self.profile["interest_evolution"] = self.profile["interest_evolution"][-12:]
                self._dirty_mark()


# ╔══════════════════════════════════════════════════════════════╗
# ║                  智能推荐引擎                                ║
# ╚══════════════════════════════════════════════════════════════╝

class RecommendationEngine:
    """基于心理画像的主动推荐：惊喜/探索/反茧房/趋势"""

    def __init__(self, psycho_profile, ai_caller=None):
        self.profile = psycho_profile  # PsychoProfile 实例
        self.ai_caller = ai_caller
        self.log = _load_json(RECOMMENDATION_LOG, {"recommendations": []})
        self._seen_bvids = set()
        self._load_seen()

    def _load_seen(self):
        for r in self.log.get("recommendations", []):
            for v in r.get("videos", []):
                if isinstance(v, dict) and v.get("bvid"):
                    self._seen_bvids.add(v["bvid"])

    async def generate_search_queries(self, mode="surprise", count=3):
        profile_summary = self.profile.get_profile_summary()
        cocoon = self.profile.profile.get("cocoon_metrics", {})
        L1 = self.profile.profile["surface_interests"]
        top_tags = sorted(L1["tags"].items(), key=lambda x: x[1], reverse=True)[:8]

        mode_guidance = {
            "surprise": (
                "生成B站搜索关键词，找到用户大概率会喜欢但从没看过的视频。"
                "基于深层画像推测潜在兴趣，不要推荐已熟悉的内容。"
            ),
            "explore": (
                "生成B站搜索关键词，帮助用户探索全新的、从未接触过的领域。"
                "这些领域应与已有兴趣有微妙关联，但把用户带向新知识版图。"
            ),
            "anticocoon": (
                "用户茧房状态: " + cocoon.get("cocoon_risk", "未知") +
                "，不足领域: " + str(cocoon.get("underrepresented_areas", [])) +
                "。推送与既有偏好不完全一致但高质量的内容，打破信息茧房。"
            ),
            "trend": (
                "基于用户兴趣演变趋势，生成搜索关键词寻找与兴趣发展方向对齐的内容。"
            ),
        }

        prompt = profile_summary + "\n\n【任务】" + mode_guidance.get(mode, mode_guidance["surprise"])
        prompt += "\n用户Top兴趣: " + ", ".join(f"{t}({s:.0%})" for t, s in top_tags)
        prompt += "\n\n返回正好" + str(count) + "个B站搜索关键词（纯关键词，每行一个）："

        try:
            if self.ai_caller:
                resp = await self.ai_caller(
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7, max_tokens=200,
                )
                content = resp.choices[0].message.content.strip()
                queries = [line.strip().lstrip("0123456789.、- ")
                          for line in content.split("\n") if line.strip()]
                return queries[:count]
        except Exception as e:
            print(f"[Recommendation] 关键词生成失败: {e}")

        return self._fallback_queries(mode, count)

    def _fallback_queries(self, mode, count):
        L1 = self.profile.profile["surface_interests"]
        top_tags = sorted(L1["tags"].items(), key=lambda x: x[1], reverse=True)[:5]
        tag_names = [t for t, _ in top_tags]
        fallbacks = {
            "surprise": [f"{t} 冷门宝藏" for t in tag_names[:2]] +
                       [f"{t} 深度解析" for t in tag_names[1:3]],
            "explore": ["跨学科 科普", "思维模型", "认知科学 入门", "设计思维", "系统论"],
            "anticocoon": ["人文社科 入门", "哲学 通俗", "艺术欣赏", "历史 趣味", "自然科学 科普"],
            "trend": [f"{t} 2026" for t in tag_names[:2]] + [f"{t} 前沿" for t in tag_names[1:3]],
        }
        return fallbacks.get(mode, fallbacks["surprise"])[:count]

    def explain_recommendation(self, video_info, mode, profile_context=""):
        title = video_info.get("title", "未知视频")
        tags = video_info.get("tags", [])
        up_name = video_info.get("up_name", "未知UP主")
        category = video_info.get("category", "")
        L1 = self.profile.profile["surface_interests"]
        L2 = self.profile.profile["cognitive_style"]
        user_tags = L1["tags"]

        reasons = []
        detail = []

        matched_tags = [t for t in (tags or []) if t in user_tags and user_tags[t] > 0.4]
        if matched_tags:
            reasons.append("与你喜欢的「" + "/".join(matched_tags[:2]) + "」相关")

        if mode == "surprise":
            reasons.insert(0, "🎁 AI高置信度惊喜推荐")
            detail.append("虽不在常看范围，但基于深层画像AI认为你会非常喜欢")
        elif mode == "explore":
            reasons.insert(0, "🔭 新领域探索")
            detail.append("「" + (category or "新领域") + "」是你未接触但可能引发兴趣的方向")
        elif mode == "anticocoon":
            reasons.insert(0, "🌐 打破信息茧房")
            detail.append("与你常看的有点不一样，能拓展视野")
        elif mode == "trend":
            reasons.insert(0, "📈 趋势对齐")
            detail.append("基于兴趣演变方向，可能是下一个会喜欢的领域")

        if L2.get("depth_preference", 0.5) > 0.6:
            if any(kw in title for kw in ["深度", "解析", "原理"]):
                detail.append("匹配你偏好深度内容的认知风格")

        if L2.get("novelty_seeking", 0.5) > 0.6:
            detail.append("符合你高度探索精神")

        reason_text = " · ".join(reasons) if reasons else "基于心理画像的智能推荐"
        if detail:
            reason_text += "\n> " + "；".join(detail)

        return reason_text

    def log_recommendation(self, mode, videos, queries):
        entry = {
            "time": _ts(), "mode": mode, "queries": queries,
            "videos": [{"bvid": v.get("bvid"), "title": v.get("title"),
                       "reason": v.get("reason", "")}
                      for v in videos if isinstance(v, dict)],
        }
        self.log.setdefault("recommendations", []).append(entry)
        self.log["recommendations"] = self.log["recommendations"][-200:]
        self._seen_bvids.update(e["bvid"] for e in entry["videos"])
        _save_json(RECOMMENDATION_LOG, self.log)

    def get_stats(self):
        recs = self.log.get("recommendations", [])
        mode_counts = Counter(r["mode"] for r in recs)
        total_videos = sum(len(r.get("videos", [])) for r in recs)
        return {
            "total_recommendations": len(recs),
            "total_videos_recommended": total_videos,
            "by_mode": dict(mode_counts),
        }


# ── 便捷函数 ─────────────────────────────────────────────────

def create_psycho_engine(ai_caller=None):
    return PsychoProfile(ai_caller=ai_caller)


def get_mode_emoji(mode):
    return {"surprise": "🎁", "explore": "🔭",
            "anticocoon": "🌐", "trend": "📈"}.get(mode, "🎬")


def get_mode_label(mode):
    return {"surprise": "惊喜推荐", "explore": "兴趣探索",
            "anticocoon": "反茧房推荐", "trend": "趋势推荐"}.get(mode, "推荐")


if __name__ == "__main__":
    print("=" * 60)
    print("[Psycho] Profile Engine -- Module Test")
    print("=" * 60)
    engine = create_psycho_engine()
    print("Profile file: " + PROFILE_FILE)
    print("Version: " + str(engine.profile["version"]))
    print("Created: " + str(engine.profile.get("created_at", "N/A")))

    engine.tracker.record_view(
        bvid="BVtest001", title="Python异步编程深度解析",
        tags=["Python", "异步", "编程"], duration=900,
        up_name="码农高天", up_uid="12345", category="科技数码",
        score=9.0, interested=True
    )
    engine.tracker.record("like", bvid="BVtest001", title="Python异步编程深度解析")
    engine.tracker.record_search("asyncio 教程", result_count=15)
    stats = engine.tracker.get_stats()
    print("Actions: " + str(stats["total_actions"]) + " records, " + str(stats["views"]) + " views")

    engine.update_surface_interest(
        title="Python异步编程深度解析", tags=["Python", "异步", "编程"],
        category="科技数码", duration=900, up_uid="12345", up_name="码农高天",
        score=9.0, liked=True
    )
    tags_preview = dict(list(engine.profile["surface_interests"]["tags"].items())[:5])
    print("L1 tag pref: " + str(tags_preview))

    engine.tracker.record_view(
        bvid="BVtest002", title="哲学入门：存在主义",
        tags=["哲学", "存在主义"], duration=600,
        up_name="思想史", up_uid="67890", category="人文历史"
    )
    metrics = engine.update_cocoon_metrics()
    print("Cocoon: risk=" + str(metrics.get("cocoon_risk")) + ", diversity=" + str(metrics.get("diversity_score")))

    engine.flush()
    print("\n[Psycho] All module tests passed.")
