"""
services/interest_engine.py — 智能兴趣引擎 v2.0

整合方案A/B/C/D全部功能，可配置、可切换：
- 方案A: 同义词扩展 + 排除词 + 兴趣权重(高/中/低) + AI建议关键词
- 方案B: PsychoProfile自动同步 + "灵光一闪"随机探索
- 方案C: 多维度评分(相关性/新颖度/多样性/质量) + 动态阈值
- 方案D: 混合渐进，默认 = "推荐"组合

配置驱动: Data/interest_engine.json
向后兼容: 旧的 Data/interests.json 自动迁移
"""
import json
import os
import random
from datetime import datetime
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple, Set
from colorama import Fore, Style

# ── 默认配置 ──
DEFAULT_ENGINE_CONFIG = {
    "version": "2.0",
    "interests": [],            # [{keyword, weight, synonyms, auto_suggested}]
    "negative_keywords": [],    # 排除关键词
    "synonym_map": {},          # {keyword: [syn1, syn2, ...]}
    "settings": {
        "proxy_mode": "smart",       # "simple" | "smart" | "ai_only" | "watch_all"
        "serendipity_rate": 0.1,     # 10% 随机探索
        "auto_sync_psycho": True,    # 从PsychoProfile自动同步
        "use_synonyms": True,        # 启用同义词扩展
        "ai_suggest": True,          # AI定期建议关键词
        "ai_suggest_interval": 20,   # 每看20个视频后AI建议一次
        "scoring": {
            "enabled": True,
            "weights": {"relevance": 0.40, "novelty": 0.20, "diversity": 0.15, "quality": 0.25},
            "dynamic_threshold": True,
            "threshold_base": 6.0,
            "threshold_min": 4.5,
            "threshold_max": 7.5,
        }
    },
    "history_tags": [],         # 已看标签 (新颖度追踪)
    "videos_watched_count": 0,  # 已看视频总数 (触发AI建议)
    "updated_at": ""
}

# ── 简单同义词库（离线可用，零成本）──
DEFAULT_SYNONYM_MAP = {
    "ai": ["人工智能", "AI", "大模型", "LLM", "GPT", "深度学习", "机器学习", "神经网络", "AIGC"],
    "python": ["py", "python编程", "python教程", "pandas", "numpy"],
    "科技": ["技术", "黑科技", "前沿科技", "科技前沿", "数码"],
    "编程": ["代码", "开发", "程序员", "软件开发", "coding"],
    "游戏": ["gaming", "手游", "端游", "主机游戏", "电竞"],
    "历史": ["历史故事", "古代", "朝代", "历史人物"],
    "经济": ["财经", "金融", "投资", "商业", "理财"],
    "音乐": ["歌曲", "乐器", "音乐制作", "编曲", "作曲"],
    "电影": ["影视", "电影解说", "影评", "导演"],
    "动漫": ["二次元", "动画", "番剧", "ACG", "漫画"],
    "数学": ["数学题", "算术", "几何", "代数"],
    "物理": ["物理知识", "力学", "量子", "相对论"],
    "生物": ["生命科学", "基因", "进化", "生态"],
    "哲学": ["思想", "哲学史", "哲学家"],
    "心理学": ["心理", "认知", "行为科学", "脑科学"],
    "设计": ["UI", "UX", "平面设计", "工业设计", "交互设计"],
    "创业": ["startup", "商业模式", "融资", "企业管理"],
    "英语": ["英文", "english", "英语学习", "英语口语"],
    "摄影": ["拍照", "摄像", "相机", "构图", "后期"],
    "美食": ["烹饪", "做饭", "料理", "探店", "饮食"],
    "旅游": ["旅行", "景点", "户外", "探险", "自驾"],
    "健康": ["养生", "健身", "运动", "医疗", "营养"],
    "汽车": ["车辆", "新能源车", "自动驾驶", "评测"],
    "法律": ["法规", "律师", "司法", "民法典"],
    "教育": ["教学", "学习", "培训", "考试"],
    "社会学": ["社会现象", "人口", "城市化", "阶层"],
    "网络安全": ["黑客", "漏洞", "病毒", "安全攻防", "加密"],
}

# ── 相关性模糊映射（"python"也匹配"Django"）──
FUZZY_RELATED = {
    "python": ["django", "flask", "fastapi", "tornado", "jupyter", "anaconda", "pip", "pypi"],
    "ai": ["chatgpt", "claude", "copilot", "stable diffusion", "midjourney", "transformer", "attention"],
    "前端": ["react", "vue", "angular", "html", "css", "javascript", "typescript", "nodejs"],
    "后端": ["api", "rest", "graphql", "微服务", "docker", "kubernetes"],
    "数据库": ["mysql", "postgresql", "mongodb", "redis", "sql"],
}

ENGINE_CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "Data", "interest_engine.json"
)

# ── 日志辅助 ──
def _elog(msg: str, tag: str = "ENGINE"):
    """引擎日志"""
    from colorama import Fore, Style
    color_map = {"OK": Fore.GREEN, "INFO": Fore.CYAN, "WARN": Fore.YELLOW, "ERR": Fore.RED}
    c = color_map.get(tag, Fore.CYAN)
    print(f"{c}[{tag}]{Style.RESET_ALL} {msg}")


@dataclass
class InterestItem:
    """单个兴趣条目"""
    keyword: str
    weight: str = "medium"  # high/medium/low
    synonyms: List[str] = field(default_factory=list)
    auto_suggested: bool = False


@dataclass
class MatchResult:
    """匹配结果"""
    passed: bool
    matched_keywords: List[str] = field(default_factory=list)
    match_reason: str = ""
    scores: Dict[str, float] = field(default_factory=dict)
    total_score: float = 0.0


class InterestEngine:
    """智能兴趣引擎 — 整合方案A/B/C/D全部能力"""

    # ── 初始化 ──
    def __init__(self, config_file: str = None):
        self.config_file = config_file or ENGINE_CONFIG_FILE
        self.config = self._load_or_init()
        self._ensure_dirs()

    def _ensure_dirs(self):
        os.makedirs(os.path.dirname(self.config_file), exist_ok=True)

    def _load_or_init(self) -> dict:
        """加载配置，如不存在则尝试从旧格式迁移"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                # 确保所有字段存在
                return self._merge_defaults(cfg)
            except (json.JSONDecodeError, OSError):
                pass
        # 尝试迁移旧 interests.json
        migrated = self._migrate_from_legacy()
        if migrated:
            return self._merge_defaults(migrated)
        return dict(DEFAULT_ENGINE_CONFIG)  # 全新默认

    def _merge_defaults(self, cfg: dict) -> dict:
        """深度合并默认值，保证新字段存在"""
        import copy
        merged = copy.deepcopy(DEFAULT_ENGINE_CONFIG)
        self._deep_update(merged, cfg)
        return merged

    def _deep_update(self, target: dict, source: dict):
        for k, v in source.items():
            if k in target and isinstance(target[k], dict) and isinstance(v, dict):
                self._deep_update(target[k], v)
            else:
                target[k] = v

    def _migrate_from_legacy(self) -> Optional[dict]:
        """从旧 Data/interests.json 迁移"""
        legacy_path = os.path.join(
            os.path.dirname(self.config_file), "interests.json"
        )
        if not os.path.exists(legacy_path):
            return None
        try:
            with open(legacy_path, 'r', encoding='utf-8') as f:
                old = json.load(f)
            old_interests = old.get("interests", [])
            if not old_interests:
                return None
            new_interests = [
                {"keyword": kw.lower(), "weight": "medium", "synonyms": [], "auto_suggested": False}
                for kw in old_interests if isinstance(kw, str)
            ]
            cfg = dict(DEFAULT_ENGINE_CONFIG)
            cfg["interests"] = new_interests
            cfg["updated_at"] = datetime.now().isoformat()
            self.config = cfg
            self.save()
            _elog(f"已从旧格式迁移 {len(new_interests)} 个兴趣关键词", "OK")
            return cfg
        except Exception:
            return None

    # ── 持久化 ──
    def save(self):
        self.config["updated_at"] = datetime.now().isoformat()
        try:
            tmp = self.config_file + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.config_file)
            return True
        except OSError:
            return False

    # ── 便利属性 ──
    @property
    def settings(self) -> dict:
        return self.config.get("settings", {})

    @property
    def proxy_mode(self) -> str:
        return self.settings.get("proxy_mode", "smart")

    @property
    def interests_list(self) -> List[dict]:
        return self.config.get("interests", [])

    @property
    def negative_keywords(self) -> List[str]:
        return self.config.get("negative_keywords", [])

    @property
    def scoring_enabled(self) -> bool:
        return self.settings.get("scoring", {}).get("enabled", True)

    @property
    def serendipity_rate(self) -> float:
        return self.settings.get("serendipity_rate", 0.1)

    @property
    def history_tags(self) -> List[str]:
        return self.config.get("history_tags", [])

    # ── 获取纯关键词列表（向后兼容）──
    def get_keywords(self) -> List[str]:
        return [item.get("keyword", item) if isinstance(item, dict) else item
                for item in self.interests_list]

    def get_interest_count(self) -> int:
        return len(self.interests_list)

    # ── 兴趣管理 CRUD ──
    def add_interest(self, keyword: str, weight: str = "medium",
                     synonyms: List[str] = None, auto_suggested: bool = False) -> bool:
        keyword = keyword.strip().lower()
        if not keyword:
            return False
        existing = [i.get("keyword", "") for i in self.interests_list if isinstance(i, dict)]
        if keyword in existing:
            return False
        item = {
            "keyword": keyword,
            "weight": weight,
            "synonyms": synonyms or [],
            "auto_suggested": auto_suggested
        }
        self.interests_list.append(item)
        # 自动扩充同义词
        if self.settings.get("use_synonyms", True) and keyword in DEFAULT_SYNONYM_MAP:
            item["synonyms"] = list(set(item.get("synonyms", []) + DEFAULT_SYNONYM_MAP[keyword]))
        self.save()
        return True

    def remove_interest(self, keyword: str) -> bool:
        keyword = keyword.strip().lower()
        for i, item in enumerate(self.interests_list):
            k = item.get("keyword", "") if isinstance(item, dict) else item
            if k == keyword:
                self.interests_list.pop(i)
                self.save()
                return True
        return False

    def update_weight(self, keyword: str, weight: str) -> bool:
        for item in self.interests_list:
            if isinstance(item, dict) and item.get("keyword", "") == keyword:
                item["weight"] = weight
                self.save()
                return True
        return False

    # ── 排除词管理 ──
    def add_negative(self, keyword: str) -> bool:
        kw = keyword.strip().lower()
        if kw and kw not in self.negative_keywords:
            self.negative_keywords.append(kw)
            self.save()
            return True
        return False

    def remove_negative(self, keyword: str) -> bool:
        kw = keyword.strip().lower()
        if kw in self.negative_keywords:
            self.negative_keywords.remove(kw)
            self.save()
            return True
        return False

    # ═══════════════════════════════════════════════════
    #  核心匹配管道
    # ═══════════════════════════════════════════════════

    def _get_search_text(self, title: str = "", tags: str = "", desc: str = "",
                         up_name: str = "", category: str = "") -> str:
        """构建搜索文本，权重：title > tags > desc > up > category"""
        parts = []
        if title: parts.append(title)
        if tags: parts.append(tags)
        if desc: parts.append(desc[:200])
        if up_name: parts.append(up_name)
        if category: parts.append(category)
        return " ".join(parts).lower()

    def _keyword_match(self, search_text: str) -> Tuple[List[str], float]:
        """
        方案A: 增强关键词匹配
        - 同义词扩展 (use_synonyms)
        - 模糊关联 (FUZZY_RELATED)
        - 权重加成 (high=1.5, medium=1.0, low=0.5)
        """
        matched = []
        total_weight = 0.0
        use_syn = self.settings.get("use_synonyms", True)

        for item in self.interests_list:
            if not isinstance(item, dict):
                kw = item
                weight_val = 1.0
                syns = []
            else:
                kw = item.get("keyword", "")
                w = item.get("weight", "medium")
                weight_val = {"high": 1.5, "medium": 1.0, "low": 0.5}.get(w, 1.0)
                syns = item.get("synonyms", [])
                if use_syn:
                    # 补充默认同义词
                    if kw in DEFAULT_SYNONYM_MAP:
                        syns = list(set(syns + DEFAULT_SYNONYM_MAP[kw]))

            if not kw:
                continue

            # 直接匹配
            if kw in search_text:
                matched.append(kw)
                total_weight += weight_val
                continue

            # 同义词匹配
            if use_syn:
                for syn in syns:
                    if syn.lower() in search_text:
                        matched.append(kw)
                        total_weight += weight_val * 0.85  # 同义词略微降权
                        break

            # 模糊关联匹配
            if kw in FUZZY_RELATED:
                for related in FUZZY_RELATED[kw]:
                    if related in search_text:
                        if kw not in matched:
                            matched.append(kw)
                            total_weight += weight_val * 0.7
                        break

        score = min(total_weight / max(len(self.interests_list), 1) * 7.0, 10.0) if matched else 0.0
        return matched, score

    def _negative_check(self, search_text: str) -> Tuple[bool, str]:
        """检查排除词"""
        for nk in self.negative_keywords:
            if nk and nk in search_text:
                return True, f"命中排除词: {nk}"
        return False, ""

    def _novelty_score(self, tags: str = "", category: str = "") -> float:
        """
        方案C: 新颖度评分
        标签/分类在历史中越常见 → 分越低
        """
        if not self.history_tags:
            return 7.0  # 无历史，默认中等新颖
        tags_lower = (tags + " " + category).lower()
        seen_count = sum(1 for ht in self.history_tags if ht.lower() in tags_lower)
        total = max(len(self.history_tags), 1)
        ratio = seen_count / min(total, 50)  # 只看最近50个
        return 10.0 * (1.0 - min(ratio, 1.0))  # 0-10分，越新颖越高

    def _diversity_score(self, recent_topics: List[str] = None) -> float:
        """
        方案C: 多样性评分
        最近看过的主题越少重复 → 分越高
        """
        if not recent_topics or len(recent_topics) < 3:
            return 7.0
        # 简化: 去重比例
        unique_ratio = len(set(recent_topics[-10:])) / max(len(recent_topics[-10:]), 1)
        return unique_ratio * 10.0

    def _multi_dim_score(self, relevance: float, novelty: float,
                         diversity: float, quality: float) -> Tuple[float, Dict[str, float]]:
        """方案C: 多维度加权总分"""
        sc = self.settings.get("scoring", {})
        w = sc.get("weights", {"relevance": 0.4, "novelty": 0.2, "diversity": 0.15, "quality": 0.25})
        total = (
            relevance * w.get("relevance", 0.4) +
            novelty * w.get("novelty", 0.2) +
            diversity * w.get("diversity", 0.15) +
            quality * w.get("quality", 0.25)
        )
        # 动态阈值：精力越低 阈值越高（更挑剔）
        threshold = sc.get("threshold_base", 6.0)
        if sc.get("dynamic_threshold", True):
            import random
            threshold += random.uniform(-0.5, 0.5)
            threshold = max(sc.get("threshold_min", 4.5), min(threshold, sc.get("threshold_max", 7.5)))
        return total, {
            "relevance": relevance, "novelty": novelty,
            "diversity": diversity, "quality": quality,
            "total": total, "threshold": threshold
        }

    def should_serendipity(self) -> bool:
        """方案B: 灵光一闪 — 随机探索非兴趣视频"""
        return random.random() < self.serendipity_rate

    # ═══════════════════════════════════════════════════
    #  主匹配入口
    # ═══════════════════════════════════════════════════

    def match(self, title: str = "", tags: str = "", desc: str = "",
              up_name: str = "", category: str = "",
              vis_desc: str = "", vis_score: float = 0.0,
              quality_ai_score: float = 7.0) -> MatchResult:
        """
        完整的匹配管道，返回 MatchResult
        AI部分需要在外部补充（_brain_interact.py 的 judge_interest_with_ai）
        """

        # 0. 空兴趣 → 全量通过
        if not self.interests_list:
            return MatchResult(
                passed=True, matched_keywords=[],
                match_reason="未设置兴趣，默认通过",
                total_score=7.0
            )

        search_text = self._get_search_text(title, tags, desc, up_name, category)

        # 1. 排除词检查
        is_blocked, block_reason = self._negative_check(search_text)
        if is_blocked:
            return MatchResult(
                passed=False, matched_keywords=[],
                match_reason=block_reason, total_score=0.0
            )

        # 2. 灵光一闪 (watch_all时不触发，因为已经全量)
        mode = self.proxy_mode
        if mode != "watch_all" and self.should_serendipity():
            return MatchResult(
                passed=True, matched_keywords=["灵光一闪"],
                match_reason="🎲 灵光一闪: 随机探索非兴趣内容",
                total_score=8.0
            )

        # 3. 关键词匹配 (方案A)
        kw_matched, kw_score = self._keyword_match(search_text)
        if kw_matched and mode == "simple":
            return MatchResult(
                passed=True, matched_keywords=kw_matched,
                match_reason=f"关键词匹配: {', '.join(kw_matched)}",
                scores={"keyword_score": kw_score},
                total_score=kw_score
            )

        # 4. 多维度评分 (方案C)
        if self.scoring_enabled:
            relevance = kw_score if kw_score > 0 else 3.0
            novelty = self._novelty_score(tags, category)
            diversity = self._diversity_score()
            quality = max(vis_score, quality_ai_score or 5.0)
            total, scores = self._multi_dim_score(relevance, novelty, diversity, quality)

            if mode == "simple":
                passed = kw_matched or total >= scores.get("threshold", 6.0)
                return MatchResult(
                    passed=passed,
                    matched_keywords=kw_matched,
                    match_reason=f"评分: {total:.1f}/10 (阈值{scores['threshold']:.1f})" if not kw_matched else f"关键词匹配: {', '.join(kw_matched)}",
                    scores=scores, total_score=total
                )

            # smart/ai_only: 有高分直接过，否则交给AI
            if total >= scores.get("threshold", 6.0) + 1.0:
                return MatchResult(
                    passed=True, matched_keywords=kw_matched,
                    match_reason=f"高分通过: {total:.1f}/10",
                    scores=scores, total_score=total
                )
            if total < scores.get("threshold", 6.0) - 2.0:
                return MatchResult(
                    passed=False, matched_keywords=[],
                    match_reason=f"低分拦截: {total:.1f}/10",
                    scores=scores, total_score=total
                )

            # 中间地带 → 需要AI判断 (标记 unclear)
            return MatchResult(
                passed=None,  # None = 需要AI进一步判断
                matched_keywords=kw_matched,
                match_reason=f"中间区域({total:.1f}/10)，需AI判断",
                scores=scores, total_score=total
            )

        # 无评分模式: 纯关键词
        if kw_matched:
            return MatchResult(passed=True, matched_keywords=kw_matched,
                              match_reason=f"关键词匹配: {', '.join(kw_matched)}")
        return MatchResult(passed=None, matched_keywords=[],
                          match_reason="无关键词命中，需AI判断")

    # ═══════════════════════════════════════════════════
    #  PsychoProfile 同步 (方案B)
    # ═══════════════════════════════════════════════════

    def sync_from_psycho(self, psycho_profile) -> int:
        """
        从 PsychoProfile 的 L1 表层兴趣同步关键词
        返回新增数量
        """
        if not self.settings.get("auto_sync_psycho", True) or not psycho_profile:
            return 0

        added = 0
        try:
            # L1: 表层兴趣
            l1 = getattr(psycho_profile, 'surface_interests', None)
            if not l1:
                l1 = getattr(psycho_profile, 'L1', None)
            if l1:
                if isinstance(l1, dict):
                    for kw, score_val in l1.items():
                        if score_val > 0.5:
                            weight = "high" if score_val > 0.8 else "medium"
                            if self.add_interest(str(kw), weight=weight, auto_suggested=True):
                                added += 1
                elif isinstance(l1, list):
                    for kw in l1:
                        if self.add_interest(str(kw), auto_suggested=True):
                            added += 1

            # L4: 深层动机 → 权重调整
            l4 = getattr(psycho_profile, 'deep_motivations', None)
            if l4:
                if isinstance(l4, dict):
                    for kw, strength in l4.items():
                        if strength > 0.7:
                            self.update_weight(str(kw), "high")
                        elif strength > 0.4:
                            self.update_weight(str(kw), "medium")

            # L5: 衰退兴趣标记
            l5 = getattr(psycho_profile, 'declining', None)
            if l5:
                if isinstance(l5, list):
                    for kw in l5:
                        self.update_weight(str(kw), "low")

            if added > 0:
                self.save()
                _elog(f"PsychoProfile 同步: 新增 {added} 个兴趣关键词", "OK")
        except Exception as e:
            _elog(f"PsychoProfile 同步失败: {e}", "WARN")

        return added

    # ═══════════════════════════════════════════════════
    #  学习记录 (新颖度追踪)
    # ═══════════════════════════════════════════════════

    def record_watched(self, tags: str = "", category: str = ""):
        """记录已看视频的标签，用于新颖度追踪"""
        new_tags = []
        for t in (tags + "," + category).split(","):
            t = t.strip().lower()
            if t and t not in ("", "none", "无", "-"):
                new_tags.append(t)
        if new_tags:
            self.history_tags.extend(new_tags)
            # 保留最近200个标签
            if len(self.history_tags) > 200:
                self.config["history_tags"] = self.history_tags[-200:]
        self.config["videos_watched_count"] = self.config.get("videos_watched_count", 0) + 1
        self.save()

    # ═══════════════════════════════════════════════════
    #  AI关键词建议触发检查 (方案A)
    # ═══════════════════════════════════════════════════

    def should_suggest_keywords(self) -> bool:
        """是否应该触发AI建议新关键词"""
        if not self.settings.get("ai_suggest", True):
            return False
        interval = self.settings.get("ai_suggest_interval", 20)
        count = self.config.get("videos_watched_count", 0)
        return count > 0 and count % interval == 0

    def generate_suggest_prompt(self, recent_titles: List[str]) -> str:
        """生成AI建议关键词的prompt"""
        existing = ", ".join(self.get_keywords())
        titles_text = "\n".join(f"- {t[:60]}" for t in (recent_titles or [])[:10])
        return f"""基于用户已看的视频，建议3-5个新的兴趣关键词。

当前兴趣: {existing}

最近观看:
{titles_text}

要求:
1. 只建议新的、当前兴趣中没有的关键词
2. 关键词应为简洁的2-4字中文词
3. 只输出JSON: {{"suggestions": ["关键词1", "关键词2", ...]}}"""

    def apply_ai_suggestions(self, suggestions: List[str]):
        """应用AI建议的关键词"""
        added = 0
        for kw in suggestions:
            if self.add_interest(kw, auto_suggested=True):
                added += 1
        if added:
            _elog(f"AI建议: 新增 {added} 个关键词 ({', '.join(suggestions)})", "OK")
        return added

    # ═══════════════════════════════════════════════════
    #  统计与诊断
    # ═══════════════════════════════════════════════════

    def get_stats(self) -> dict:
        """获取引擎统计信息"""
        manual = sum(1 for i in self.interests_list
                     if isinstance(i, dict) and not i.get("auto_suggested", False))
        auto = sum(1 for i in self.interests_list
                   if isinstance(i, dict) and i.get("auto_suggested", False))
        high = sum(1 for i in self.interests_list
                   if isinstance(i, dict) and i.get("weight") == "high")
        medium = sum(1 for i in self.interests_list
                     if isinstance(i, dict) and i.get("weight") == "medium")
        low = sum(1 for i in self.interests_list
                   if isinstance(i, dict) and i.get("weight") == "low")
        return {
            "total": len(self.interests_list),
            "manual": manual, "auto_suggested": auto,
            "high_weight": high, "medium_weight": medium, "low_weight": low,
            "negative_keywords": len(self.negative_keywords),
            "history_tags": len(self.history_tags),
            "videos_watched": self.config.get("videos_watched_count", 0),
            "proxy_mode": self.proxy_mode,
            "scoring_enabled": self.scoring_enabled,
            "serendipity": f"{self.serendipity_rate*100:.0f}%",
            "auto_sync_psycho": self.settings.get("auto_sync_psycho", True),
            "ai_suggest": self.settings.get("ai_suggest", True),
        }

    def display_settings(self):
        """在菜单中显示当前设置"""
        stats = self.get_stats()
        sc = self.settings.get("scoring", {})
        w = sc.get("weights", {})  # 提前定义，f-string中引用
        print(f"""
{Fore.CYAN}╔══════════════════════════════════════════════════════════╗
║              🎯 兴趣偏好设置 (引擎 v2.0)                  ║
╚══════════════════════════════════════════════════════════╝{Style.RESET_ALL}

{Fore.CYAN}【方案A】智能关键词增强:{Style.RESET_ALL}
  • 兴趣总数: {stats['total']} (手动{stats['manual']} | AI建议{stats['auto_suggested']})
  • 权重分布: 高{stats['high_weight']} | 中{stats['medium_weight']} | 低{stats['low_weight']}
  • 排除词: {stats['negative_keywords']} 个
  • 同义词扩展: {Fore.GREEN + '✓' if self.settings.get('use_synonyms') else Fore.YELLOW + '✗'}{Style.RESET_ALL}
  • AI关键词建议: {Fore.GREEN + '✓' if self.settings.get('ai_suggest') else Fore.YELLOW + '✗'}{Style.RESET_ALL}

{Fore.CYAN}【方案B】AI驱动兴趣画像:{Style.RESET_ALL}
  • PsychoProfile同步: {Fore.GREEN + '✓' if self.settings.get('auto_sync_psycho') else Fore.YELLOW + '✗'}{Style.RESET_ALL}
  • 灵光一闪: {stats['serendipity']} (随机探索非兴趣)
  • 历史标签追踪: {stats['history_tags']} 个

{Fore.CYAN}【方案C】智能过滤评分:{Style.RESET_ALL}
  • 多维度评分: {Fore.GREEN + '✓' if stats['scoring_enabled'] else Fore.YELLOW + '✗'}{Style.RESET_ALL}
  • 权重: 相关性{w.get('relevance',0.4):.0%} | 新颖度{w.get('novelty',0.2):.0%} | 多样性{w.get('diversity',0.15):.0%} | 质量{w.get('quality',0.25):.0%}
  • 动态阈值: {Fore.GREEN + '✓' if sc.get('dynamic_threshold') else Fore.YELLOW + '✗'}{Style.RESET_ALL} (基准{sc.get('threshold_base',6.0)})

{Fore.CYAN}【方案D】过滤模式:{Style.RESET_ALL} {Fore.GREEN}{stats['proxy_mode']}{Style.RESET_ALL}
  • simple=纯关键词 | smart=智能混合(推荐) | ai_only=纯AI | watch_all=全看
""")


# ── 全局单例 ──
_engine_instance: Optional[InterestEngine] = None


def get_engine() -> InterestEngine:
    """获取全局引擎单例（延迟初始化）"""
    global _engine_instance
    if _engine_instance is None:
        _engine_instance = InterestEngine()
    return _engine_instance


def reset_engine():
    """重置引擎（配置变更后）"""
    global _engine_instance
    _engine_instance = None
