"""ob_bridge/ab_test.py — OB vs 原生推荐 AB 对比框架

跟踪两个推荐源的质量指标，输出对比报告供进化系统决策。
"""

import time
from collections import defaultdict
from datetime import datetime


class ABComparisonTracker:
    """AB对比跟踪器

    在每个视频决策完成后，记录来源和质量数据。
    定期生成对比报告。

    Attributes:
        A = OB 推荐
        B = 原生 B站 推荐
    """

    def __init__(self, window_size: int = 200):
        self.window_size = window_size  # 滑动窗口大小
        self._started_at = time.time()

        # 两组数据
        self._group_a = self._new_group()  # OB
        self._group_b = self._new_group()  # Native

        # 分时趋势
        self._hourly_trend = []  # [(hour_label, a_stats, b_stats), ...]

    @staticmethod
    def _new_group() -> dict:
        return {
            "recommended": 0,
            "watched": 0,
            "learned": 0,
            "scores": [],       # 最近 N 个分数
            "durations": [],    # 视频时长
            "topics": defaultdict(int),
            "up_names": set(),
        }

    # ── 记录 ──

    def record_recommend(self, group: str, count: int = 1):
        """记录推荐数量"""
        g = self._group_a if group == "ob" else self._group_b
        g["recommended"] += count

    def record_decision(self, group: str, bvid: str, title: str,
                        score: float, learned: bool, up_name: str = "",
                        duration: int = 0, topic: str = ""):
        """记录决策结果"""
        g = self._group_a if group == "ob" else self._group_b
        g["watched"] += 1
        if learned:
            g["learned"] += 1
        g["scores"].append(score)
        if len(g["scores"]) > self.window_size:
            g["scores"] = g["scores"][-self.window_size:]
        if duration > 0:
            g["durations"].append(duration)
            if len(g["durations"]) > self.window_size:
                g["durations"] = g["durations"][-self.window_size:]
        if up_name:
            g["up_names"].add(up_name)
        if topic:
            g["topics"][topic] += 1

    # ── 统计 ──

    def _compute_group_stats(self, g: dict) -> dict:
        """计算单组统计数据"""
        watched = max(g["watched"], 1)
        recommended = max(g["recommended"], 1)
        scores = g["scores"]
        durations = g["durations"]

        return {
            "recommended": g["recommended"],
            "watched": g["watched"],
            "learned": g["learned"],
            "conversion_rate": round(g["watched"] / recommended * 100, 1),
            "learn_rate": round(g["learned"] / watched * 100, 1),
            "avg_score": round(sum(scores) / max(len(scores), 1), 2),
            "avg_duration": round(sum(durations) / max(len(durations), 1), 0),
            "unique_ups": len(g["up_names"]),
            "top_topics": dict(
                sorted(g["topics"].items(), key=lambda x: x[1], reverse=True)[:5]
            ),
        }

    def compare(self) -> dict:
        """生成对比报告"""
        a_stats = self._compute_group_stats(self._group_a)
        b_stats = self._compute_group_stats(self._group_b)

        # 差异计算
        def delta(a_val, b_val) -> float:
            return round(a_val - b_val, 2)

        return {
            "ob": a_stats,
            "native": b_stats,
            "deltas": {
                "conversion_rate": delta(
                    a_stats["conversion_rate"], b_stats["conversion_rate"]),
                "avg_score": delta(
                    a_stats["avg_score"], b_stats["avg_score"]),
                "learn_rate": delta(
                    a_stats["learn_rate"], b_stats["learn_rate"]),
                "unique_ups": delta(
                    a_stats["unique_ups"], b_stats["unique_ups"]),
            },
            "winner": self._determine_winner(a_stats, b_stats),
            "uptime_hours": round(
                (time.time() - self._started_at) / 3600, 1),
            "sample_size": {
                "ob": a_stats["watched"],
                "native": b_stats["watched"],
            },
        }

    def _determine_winner(self, a: dict, b: dict) -> str:
        """判断哪个来源更好"""
        a_score = (
            a["conversion_rate"] * 0.3 +
            a["avg_score"] * 10 * 0.3 +
            a["learn_rate"] * 0.2 +
            a["unique_ups"] * 0.2
        )
        b_score = (
            b["conversion_rate"] * 0.3 +
            b["avg_score"] * 10 * 0.3 +
            b["learn_rate"] * 0.2 +
            b["unique_ups"] * 0.2
        )

        diff = a_score - b_score
        if diff > 10:
            return "ob_better"
        elif diff < -10:
            return "native_better"
        else:
            return "comparable"

    def evolution_context(self) -> str:
        """生成供进化系统使用的上下文"""
        c = self.compare()
        d = c["deltas"]

        verdict = {
            "ob_better": "OB推荐质量显著优于B站原生",
            "native_better": "B站原生推荐质量显著优于OB",
            "comparable": "OB与B站原生推荐质量接近",
        }.get(c["winner"], "")

        parts = [
            f"[AB对比] {verdict}",
            f"OB均分{c['ob']['avg_score']} vs 原生{c['native']['avg_score']}"
            f"(Δ{d['avg_score']:+.2f})",
            f"OB转化率{c['ob']['conversion_rate']}% vs 原生{c['native']['conversion_rate']}%"
            f"(Δ{d['conversion_rate']:+.1f}%)",
            f"OB学习率{c['ob']['learn_rate']}% vs 原生{c['native']['learn_rate']}%"
            f"(Δ{d['learn_rate']:+.1f}%)",
        ]

        # 如果 OB 更差，给出建议
        if c["winner"] == "native_better":
            parts.append(
                "[建议] 降低OB推荐优先级，增加OB探索模式比例，"
                "或调整OB兴趣画像权重")
        elif c["winner"] == "ob_better":
            parts.append(
                "[建议] OB推荐效果好，可加大OB配额，减少原生首页刷取")

        return "\n".join(parts)

    def reset(self):
        """重置统计"""
        self._group_a = self._new_group()
        self._group_b = self._new_group()
        self._hourly_trend.clear()
        self._started_at = time.time()
