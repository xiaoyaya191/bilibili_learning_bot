"""ob_bridge/types.py — 数据模型，与 OpenBiliClaw API 对齐"""

from enum import Enum
from dataclasses import dataclass, field
from typing import Optional


class OBMode(str, Enum):
    """推荐模式"""
    PRECISION = "precision"   # 精准模式：画像有内容，完整三层管线个性化推荐
    EXPLORE = "explore"       # 探索模式：画像为空，轻量管线广撒网


@dataclass
class OBStatus:
    """OB 运行时状态"""
    online: bool = False
    url: str = ""
    error: str = ""


@dataclass
class RecommendationItem:
    """从 OB 拉取的推荐视频条目（映射到 B站格式兼容字段）"""
    bvid: str = ""
    title: str = ""
    up_name: str = ""
    cover_url: str = ""
    expression: str = ""        # AI 生成的推荐理由
    topic_label: str = ""       # 主题标签
    duration: int = 0
    content_id: str = ""
    source_platform: str = "bilibili"
    content_url: str = ""       # 完整视频URL，如 https://www.bilibili.com/video/BVxxx
    recommendation_id: int = 0  # OB 内部推荐ID，用于反馈
    
    # 兼容 B站原始推荐流字段（owner dict 等）
    # 这些由 to_bili_format() 生成
    def to_bili_format(self) -> dict:
        """转换为 brain 期望的 B站推荐流格式"""
        return {
            "bvid": self.bvid,
            "title": self.title,
            "pic": self.cover_url,
            "owner": {
                "name": self.up_name,
                "mid": 0,
            },
            "id": 0,
            "aid": 0,
            "duration": self.duration,
            "_ob_id": self.recommendation_id,
            "_ob_reason": self.expression,
            "_ob_topic": self.topic_label,
            "_source": "openbiliclaw",
        }
