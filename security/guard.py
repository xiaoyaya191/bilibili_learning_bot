"""security/guard.py — 回复内容安全审查（隐私/安全模块）"""
import re
from core.config import config as _global_config


class ReplySafetyGuard:
    """评论/私信回复审查：命中敏感词就跳过，不发送。

    与原版 start_cli.py 的 ReplySafetyGuard 完全兼容，
    通过 __init__(config) 接收配置，或省略使用 core.config 的全局配置。
    """

    def __init__(self, config: dict = None):
        cfg = config or _global_config
        safety_cfg = cfg.get("reply_safety", {})
        self.enabled = safety_cfg.get("enabled", True)
        self.block_on_incoming = safety_cfg.get("block_on_incoming", True)
        self.block_on_outgoing = safety_cfg.get("block_on_outgoing", True)
        self.block_political_video_comments = safety_cfg.get("block_political_video_comments", True)
        self.blocked_keywords: list = safety_cfg.get("blocked_keywords", [])
        self.blocked_regex = self._build_regex()

    def _build_regex(self) -> re.Pattern:
        if not self.blocked_keywords:
            return re.compile(r'(?!x)x')  # never match
        pattern = '|'.join(re.escape(kw) for kw in self.blocked_keywords)
        return re.compile(pattern, re.IGNORECASE)

    def recheck(self):
        """热重载配置（原 start_cli.py 中支持）"""
        # 保持在 start_cli.py 中重载，此处仅占位
        pass

    def should_block(self, text: str) -> bool:
        if not self.enabled or not text:
            return False
        return bool(self.blocked_regex.search(text))

    def filter_replies(self, replies: list) -> list:
        if not self.enabled:
            return replies
        safe = [r for r in replies if not self.should_block(r.get("text", ""))]
        return safe

    def is_video_comment_safe(self, video_title: str, video_desc: str) -> bool:
        if not self.block_political_video_comments:
            return True
        combined = f"{video_title} {video_desc}".lower()
        political = {"政治", "政府", "台湾", "香港", "新疆", "西藏", "抗议", "游行",
                     "民主", "选举", "宪法", "习近平", "中共", "共产党"}
        for kw in political:
            if kw in combined:
                return False
        return True

    # ── v2.0.3 补全：与原 start_cli.py 内联版兼容的方法 ──

    def find_hits(self, text: str) -> list:
        """扫描文本，返回命中敏感词的列表。"""
        if not self.enabled or not text:
            return []
        return [kw for kw in self.blocked_keywords if kw in text]

    def review(self, incoming: str, outgoing: str):
        """审查对话：检查来信和回信是否命中敏感词。
        返回 (ok: bool, reason: str, hits: list)
        """
        incoming_hits = []
        outgoing_hits = []

        if self.block_on_incoming and incoming:
            incoming_hits = self.find_hits(incoming)
        if self.block_on_outgoing and outgoing:
            outgoing_hits = self.find_hits(outgoing)

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
        """审查视频内容是否适合评论（防涉政）。
        返回 (allowed: bool, reason: str, hits: list)
        """
        if not self.block_political_video_comments:
            return True, '', []

        combined = f"{title} {up} {subtitle} {comments}"
        hits = self.find_hits(combined)
        if hits:
            return False, f"视频内容命中敏感词: {', '.join(hits)}", hits
        return True, '', []
