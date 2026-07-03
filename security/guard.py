"""security/guard.py — 回复内容安全审查（隐私/安全模块）

分级拦截策略：
- Tier 1 高风险词（HIGH_RISK_KEYWORDS）：明确政治指向的组合词，单次命中即拦截
  例："六四"、"台独"、"辱华"、"靖国神社"等
- Tier 2 通用高频词：日常话语中的常见词，需 2+ 个同时命中才拦截
  例："国家"、"政府"、"民主"、"战争"等
"""
import re
from core.config import config as _global_config


class ReplySafetyGuard:
    """评论/私信回复审查：分级命中敏感词就跳过，不发送。

    与原版 start_cli.py 的 ReplySafetyGuard 完全兼容，
    通过 __init__(config) 接收配置，或省略使用 core.config 的全局配置。
    """

    # 高风险关键词：明确政治指向，单次命中即拦截
    HIGH_RISK_KEYWORDS = {
        "六四", "法轮", "辱华", "台独", "港独", "藏独", "疆独",
        "靖国神社", "武统", "一国两制", "独裁", "民族主义",
    }

    def __init__(self, config: dict = None):
        cfg = config or _global_config
        safety_cfg = cfg.get("reply_safety", {})
        self.enabled = safety_cfg.get("enabled", True)
        self.block_on_incoming = safety_cfg.get("block_on_incoming", True)
        self.block_on_outgoing = safety_cfg.get("block_on_outgoing", True)
        self.block_political_video_comments = safety_cfg.get("block_political_video_comments", True)
        self.blocked_keywords: list = safety_cfg.get("blocked_keywords", [])
        # 按风险等级拆分
        self._high_risk_words = [kw for kw in self.blocked_keywords if kw in self.HIGH_RISK_KEYWORDS]
        self._common_words = [kw for kw in self.blocked_keywords if kw not in self.HIGH_RISK_KEYWORDS]

    def recheck(self):
        """热重载配置（原 start_cli.py 中支持）"""
        pass

    def should_block(self, text: str) -> bool:
        """分级拦截：
        - 命中任意高风险词 → 立即拦截
        - 命中 2+ 通用词 → 拦截（单通用词不拦，避免误杀）
        """
        if not self.enabled or not text:
            return False
        # Tier 1: 高风险词 → 即时拦截
        for kw in self._high_risk_words:
            if kw in text:
                return True
        # Tier 2: 通用词 → 需 2+ 命中
        common_hits = [kw for kw in self._common_words if kw in text]
        return len(common_hits) >= 2

    def filter_replies(self, replies: list) -> list:
        if not self.enabled:
            return replies
        return [r for r in replies if not self.should_block(r.get("text", ""))]

    def is_video_comment_safe(self, video_title: str, video_desc: str) -> bool:
        """视频内容涉政检查（分级策略）"""
        if not self.block_political_video_comments:
            return True
        combined = f"{video_title} {video_desc}".lower()
        # 高风险词：单次即拦
        for kw in self.HIGH_RISK_KEYWORDS:
            if kw in combined:
                return False
        # 通用词：需 2+
        common = {"政治", "政府", "台湾", "香港", "新疆", "西藏", "抗议", "游行",
                  "民主", "选举", "宪法", "习近平", "中共", "共产党"}
        hits = [kw for kw in common if kw in combined]
        return len(hits) < 2

    # ── v2.0.3 补全：与原 start_cli.py 内联版兼容的方法 ──

    def find_hits(self, text: str) -> list:
        """返回所有已注册关键词的命中（全部层级，供日志/调试用）。
        注意：命中列表 ≠ 拦截判定，实际拦截需通过 _find_blocking_hits()。
        """
        if not self.enabled or not text:
            return []
        return [kw for kw in self.blocked_keywords if kw in text]

    def _find_blocking_hits(self, text: str) -> list:
        """返回实际触发拦截的命中词（按分级规则）。
        - 高风险词：全计入
        - 通用词：仅当 2+ 命中时全计入；单个通用词不拦截，不返回
        """
        if not self.enabled or not text:
            return []
        hits = [kw for kw in self._high_risk_words if kw in text]
        common_hits = [kw for kw in self._common_words if kw in text]
        if len(common_hits) >= 2:
            hits.extend(common_hits)
        return hits

    def review(self, incoming: str, outgoing: str):
        """审查对话：分级检查来信和回信。
        返回 (ok: bool, reason: str, hits: list)
        """
        incoming_hits = []
        outgoing_hits = []

        if self.block_on_incoming and incoming:
            incoming_hits = self._find_blocking_hits(incoming)
        if self.block_on_outgoing and outgoing:
            outgoing_hits = self._find_blocking_hits(outgoing)

        all_hits = list(set(incoming_hits + outgoing_hits))
        if all_hits:
            parts = []
            if incoming_hits:
                parts.append(f"来信命中: {', '.join(incoming_hits)}")
            if outgoing_hits:
                parts.append(f"回信命中: {', '.join(outgoing_hits)}")
            return False, '; '.join(parts), all_hits
        return True, '', []

    def review_video_for_comment(self, title: str = '', up: str = '',
                                  subtitle: str = '', comments: str = ''):
        """审查视频内容是否适合评论（防涉政，分级策略）。
        返回 (allowed: bool, reason: str, hits: list)
        """
        if not self.block_political_video_comments:
            return True, '', []

        combined = f"{title} {up} {subtitle} {comments}"
        hits = self._find_blocking_hits(combined)
        if hits:
            return False, f"视频内容命中敏感词: {', '.join(hits)}", hits
        return True, '', []
