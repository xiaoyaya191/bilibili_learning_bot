"""ob_bridge/client.py — OpenBiliClaw HTTP 客户端

所有超时 ≤10s，失败静默返回 None/False，永不抛异常给调用方。
"""

import asyncio
from typing import Optional

import httpx

from ob_bridge.types import OBMode, OBStatus, RecommendationItem
from utils.display import log


class OBClient:
    """OpenBiliClaw REST API 客户端"""

    def __init__(self, base_url: str = "http://127.0.0.1:8420", timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._mode: OBMode = OBMode.EXPLORE
        self._client: Optional[httpx.AsyncClient] = None

    # ── 模式管理 ──

    @property
    def mode(self) -> OBMode:
        return self._mode

    def set_mode(self, mode: OBMode):
        """切换推荐模式（精准/探索）"""
        old = self._mode
        self._mode = mode
        if old != mode:
            log(f"[OB] 模式切换: {old.value} → {mode.value}", "CONFIG")

    # ── 核心接口 ──

    async def health_check(self) -> bool:
        """检测 OB 是否在线"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/api/health")
                return resp.status_code == 200
        except Exception:
            return False

    async def get_recommendations(self, limit: int = 20) -> Optional[list[RecommendationItem]]:
        """拉取推荐列表

        Args:
            limit: 拉取数量（默认20）

        Returns:
            list[RecommendationItem] 成功时，None 失败/OB离线时
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                # 探索模式下传 mode=explore 参数
                params = {}
                if self._mode == OBMode.EXPLORE:
                    params["mode"] = "explore"

                resp = await client.get(
                    f"{self.base_url}/api/recommendations",
                    params=params,
                )
                if resp.status_code != 200:
                    return None

                data = resp.json()
                items_raw = data.get("items", [])
                if not items_raw:
                    return None

                items = []
                for raw in items_raw[:limit]:
                    item = RecommendationItem(
                        bvid=raw.get("bvid", ""),
                        title=raw.get("title", ""),
                        up_name=raw.get("up_name", ""),
                        cover_url=raw.get("cover_url", ""),
                        expression=raw.get("expression", ""),
                        topic_label=raw.get("topic_label", ""),
                        duration=raw.get("duration", 0),
                        content_id=raw.get("content_id", ""),
                        source_platform=raw.get("source_platform", "bilibili"),
                        content_url=raw.get("content_url", ""),
                        recommendation_id=raw.get("id", 0),
                    )
                    items.append(item)
                return items if items else None
        except Exception:
            return None

    async def report_event(self, bvid: str, event_type: str, metadata: dict = None) -> bool:
        """回传行为事件

        Args:
            bvid: 视频 BV 号
            event_type: watch / skip
            metadata: 额外元数据（score, mode, topic 等）
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                payload = {
                    "events": [{
                        "type": event_type,
                        "url": f"https://www.bilibili.com/video/{bvid}",
                        "source_platform": "bilibili",
                        "metadata": metadata or {},
                    }]
                }
                resp = await client.post(
                    f"{self.base_url}/api/events",
                    json=payload,
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def report_feedback(self, recommendation_id: int, feedback_type: str, note: str = "") -> bool:
        """回传推荐反馈

        Args:
            recommendation_id: OB 推荐 ID
            feedback_type: like / dislike / dismiss
            note: 备注说明
        """
        if not recommendation_id:
            return False
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                payload = {
                    "recommendation_id": recommendation_id,
                    "feedback_type": feedback_type,
                    "note": note,
                }
                resp = await client.post(
                    f"{self.base_url}/api/recommendations/click",
                    json=payload,
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def get_profile_summary(self) -> Optional[dict]:
        """读取 OB 用户画像摘要

        Returns:
            dict 含 profile 和 summary 字段，None 失败时
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.get(f"{self.base_url}/api/profile-summary")
                if resp.status_code == 200:
                    return resp.json()
        except Exception:
            pass
        return None

    async def has_interests(self) -> bool:
        """检查 OB 画像中是否有用户自定义的兴趣"""
        profile = await self.get_profile_summary()
        if not profile:
            return False
        interests = (
            profile.get("profile", {})
            .get("surface", {})
            .get("primary_interests", [])
        )
        return bool(interests and len(interests) > 0)

    async def refresh_recommendations(self) -> bool:
        """触发 OB 后台补货"""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.base_url}/api/recommendations/refresh")
                return resp.status_code == 200
        except Exception:
            return False

    # ── 画像编辑接口 ──

    async def edit_profile(self, layer: str, operation: str, topic: str,
                           weight: float = 1.0, ttl_hours: int = 0,
                           source: str = "learning_bot") -> bool:
        """编辑 OB 用户画像

        Args:
            layer: 画像层级 (surface / interest / role / values / core)
            operation: 操作类型 (add_like / add_dislike / set_weight / remove / add_curiosity_keyword)
            topic: 主题/关键词
            weight: 权重 (0.0~2.0)
            ttl_hours: 生存小时 (0=永久，>0 表示临时注入)
            source: 来源标记 (learning_bot / learning_bot_knowledge_gap / learning_bot_diary)

        Returns:
            True 成功，False 失败
        """
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                payload = {
                    "layer": layer,
                    "operation": operation,
                    "topic": topic,
                    "weight": weight,
                    "source": source,
                }
                if ttl_hours > 0:
                    payload["ttl_hours"] = ttl_hours

                resp = await client.post(
                    f"{self.base_url}/api/profile/edit",
                    json=payload,
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def add_curiosity_keyword(self, keyword: str, weight: float = 1.5,
                                    ttl_hours: int = 24, source: str = "learning_bot_diary") -> bool:
        """注入好奇心关键词到 OB 规划器

        这是 edit_profile 的快捷方法，专用于日记"知识生长点"注入。
        关键词会在 OB 的 UnifiedKeywordPlanner 中临时加权搜索。

        Args:
            keyword: 搜索关键词
            weight: 临时权重（默认 1.5，高于普通兴趣）
            ttl_hours: 过期时间（默认 24h）
            source: 来源标记
        """
        return await self.edit_profile(
            layer="surface",
            operation="add_curiosity_keyword",
            topic=keyword,
            weight=weight,
            ttl_hours=ttl_hours,
            source=source,
        )

    async def adjust_interest_weight(self, topic: str, weight: float,
                                     source: str = "learning_bot_knowledge_gap") -> bool:
        """调整兴趣权重（知识盲区→加权，学够了→降权）"""
        op = "set_weight"
        if weight <= 0:
            op = "remove"
        return await self.edit_profile(
            layer="surface",
            operation=op,
            topic=topic,
            weight=max(0.0, min(2.0, weight)),
            source=source,
        )

    async def add_dislike_up(self, up_name: str, reason: str = "") -> bool:
        """将某 UP 主加入 OB 的 dislike 列表（审计发现低质量内容时）"""
        return await self.edit_profile(
            layer="surface",
            operation="add_dislike",
            topic=f"UP:{up_name}",
            weight=0.0,
            source="learning_bot_audit",
        )
