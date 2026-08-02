"""ob_bridge/audit.py — OB 效能审计 & 质量跟踪

跟踪 OB 推荐的转化率、来源分布、平均质量等指标。
定期产出审计报告，供 brain 自我进化时参考。
"""

import time
from datetime import datetime
from collections import defaultdict
from typing import Optional


class OBAuditor:
    """OB 推荐效能审计器

    使用方式：
        auditor = OBAuditor()
        auditor.record("recommend", source="ob", bvid="BVxxx", title="...")
        # ... 决策完成 ...
        auditor.record("decision", source="ob", bvid="BVxxx", score=8.5, learned=True)

        report = auditor.summary()
    """

    def __init__(self):
        self.created_at = datetime.now()
        self._events = []           # 原始事件
        self._by_source = defaultdict(lambda: {          # 按来源统计
            "total": 0, "watched": 0, "learned": 0,
            "skipped": 0, "scores": [], "avg_score": 0.0,
            "conversion_rate": 0.0, "learn_rate": 0.0,
            "topics": defaultdict(int),
        })
        # 时间窗口统计
        self._hourly = defaultdict(lambda: defaultdict(int))  # hour → source → count
        self._last_report_at = time.time()
        self._report_interval = 3600  # 默认每小时输出报告

    # ── 事件记录 ──

    def record(self, event_type: str, source: str = "native", **kwargs):
        """记录一条审计事件

        event_type: "recommend" | "decision"
        source:     "ob" | "native" | "revisit" | "browse_up" | "psycho_recommend"
        """
        event = {
            "type": event_type,
            "source": source,
            "time": time.time(),
            **kwargs,
        }
        self._events.append(event)
        self._events = self._events[-500:]  # 保留最近 500 条

        # 实时更新按来源统计
        src = self._by_source[source]
        src["total"] = src.get("total", 0) + 1

        hour_key = datetime.now().strftime("%Y-%m-%d %H")
        self._hourly[hour_key][source] += 1

    def record_decision(self, source: str, bvid: str, title: str,
                        score: float, learned: bool, topic: str = "",
                        skip_reason: str = ""):
        """记录决策结果"""
        src = self._by_source[source]
        src["watched"] = src.get("watched", 0) + 1

        if learned:
            src["learned"] = src.get("learned", 0) + 1
        if skip_reason:
            src["skipped"] = src.get("skipped", 0) + 1

        src["scores"] = (src.get("scores", []) + [score])[-100:]  # 保留最近 100 个分数
        src["avg_score"] = round(sum(src["scores"]) / max(len(src["scores"]), 1), 2)

        if topic:
            src["topics"][topic] += 1

    # ── 报告生成 ──

    def summary(self) -> dict:
        """生成摘要报告"""
        results = {
            "sources": {},
            "total": {
                "recommended": 0,
                "watched": 0,
                "learned": 0,
            },
            "comparison": {},
            "generated_at": datetime.now().isoformat(),
            "uptime_hours": round((time.time() - self.created_at.timestamp()) / 3600, 1),
        }

        for source, stats in self._by_source.items():
            total = stats.get("total", 0)
            watched = stats.get("watched", 0)
            learned = stats.get("learned", 0)
            skipped = stats.get("skipped", 0)
            avg_score = stats.get("avg_score", 0.0)

            # 转化率 = watched / recommended
            conv = round(watched / max(total, 1) * 100, 1)
            # 学习率 = learned / watched
            learn_rate = round(learned / max(watched, 1) * 100, 1)
            # 跳过率 = skipped / watched
            skip_rate = round(skipped / max(watched, 1) * 100, 1)

            results["sources"][source] = {
                "recommended": total,
                "watched": watched,
                "learned": learned,
                "skipped": skipped,
                "avg_score": avg_score,
                "conversion_rate_pct": conv,
                "learn_rate_pct": learn_rate,
                "skip_rate_pct": skip_rate,
                "top_topics": dict(
                    sorted(stats.get("topics", {}).items(),
                           key=lambda x: x[1], reverse=True)[:5]
                ),
            }

            results["total"]["recommended"] += total
            results["total"]["watched"] += watched
            results["total"]["learned"] += learned

        # 对比：OB vs native
        ob_stats = results["sources"].get("ob", {})
        native_stats = results["sources"].get("native", {})
        if ob_stats and native_stats:
            ob_conv = ob_stats.get("conversion_rate_pct", 0)
            na_conv = native_stats.get("conversion_rate_pct", 0)
            ob_score = ob_stats.get("avg_score", 0)
            na_score = native_stats.get("avg_score", 0)

            results["comparison"] = {
                "conversion_delta": round(ob_conv - na_conv, 1),
                "score_delta": round(ob_score - na_score, 1),
                "winner": "ob" if ob_conv >= na_conv and ob_score >= na_score else
                         "native" if na_conv > ob_conv and na_score > ob_score else "mixed",
                "verdict": "",
            }
            delta_conv = ob_conv - na_conv
            delta_score = ob_score - na_score
            if delta_conv > 5 and delta_score > 0.5:
                results["comparison"]["verdict"] = "OB 显著优于原生推荐"
            elif delta_conv < -5 and delta_score < -0.5:
                results["comparison"]["verdict"] = "原生推荐显著优于 OB"
            else:
                results["comparison"]["verdict"] = "OB 与原生推荐旗鼓相当"

        return results

    def format_report(self) -> str:
        """生成可读的文本报告"""
        s = self.summary()
        lines = []
        lines.append(f"📊 OB效能审计报告 (运行 {s['uptime_hours']}h)")

        for src, stats in s["sources"].items():
            emoji = {"ob": "🤖", "native": "📡", "revisit": "📖",
                     "browse_up": "👤", "psycho_recommend": "🧠"}.get(src, "📌")
            lines.append(
                f"  {emoji} {src}: 推荐{stats['recommended']}→观看{stats['watched']}"
                f"→学习{stats['learned']} | 转化{stats['conversion_rate_pct']}%"
                f"| 均分{stats['avg_score']} | 学习率{stats['learn_rate_pct']}%"
            )

        comp = s.get("comparison", {})
        if comp.get("verdict"):
            lines.append(f"  ⚖️ OB vs 原生: {comp['verdict']} "
                        f"(转化差{comp.get('conversion_delta',0):+.1f}% "
                        f"均分差{comp.get('score_delta',0):+.2f})")

        return "\n".join(lines)

    def should_report(self) -> bool:
        """是否该输出报告了"""
        return time.time() - self._last_report_at >= self._report_interval

    def mark_reported(self):
        """标记报告已输出"""
        self._last_report_at = time.time()

    def get_evolution_context(self) -> str:
        """生成供进化系统使用的上下文文本"""
        s = self.summary()
        parts = []

        for src, stats in s["sources"].items():
            if src not in ("ob", "native"):
                continue
            parts.append(
                f"[{src}]推荐{stats['recommended']}视频→观看{stats['watched']}"
                f"→学习{stats['learned']} | 均分{stats['avg_score']} "
                f"| 学习率{stats['learn_rate_pct']}%"
            )

        comp = s.get("comparison", {})
        if comp.get("verdict"):
            parts.append(f"OB对比原生: {comp['verdict']}")

        return " | ".join(parts) if parts else ""

    def reset(self):
        """重置统计数据"""
        self._by_source.clear()
        self._events.clear()
        self._hourly.clear()
        self.created_at = datetime.now()
        self._last_report_at = time.time()
