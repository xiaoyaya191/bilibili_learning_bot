"""
OpenBiliClaw — 夺回推荐权的内容管道 (v4.0 Phase 0)
====================================================
三层管线：召回(5000+) → 排序(200+) → 重排(Top20)

用途：在视频到达AI大脑之前，做三层过滤，把B站几百万视频变成真正值得看的20个。

与三层大脑的对应：
  Layer1 召回  ← ⚡原始层（广度、安全底线）
  Layer2 排序  ← 💗情感层（"这个看起来有意思"）
  Layer3 重排  ← 🧠理性层（"这个应该学"）
"""

from .pipeline import RecommendationPipeline
from .config import BiliClawConfig

__all__ = ["RecommendationPipeline", "BiliClawConfig"]
__version__ = "0.1.0"
