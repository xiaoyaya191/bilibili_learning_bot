"""services/reply_safety.py — 评论/私信回复内容安全审查"""
import re
from core.config import config as _global_config


class ReplySafetyGuard:
    """评论/私信回复审查：命中敏感词就跳过，不发送。

    与原版 new_agent.py 的 ReplySafetyGuard 完全兼容，
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
        """热重载配置（原 new_agent.py 中支持）"""
        # 保持在 new_agent.py 中重载，此处仅占位
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
