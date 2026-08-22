"""ob_bridge/config_bridge.py — 策略说明书 → OpenBiliClaw 配置翻译器

负责翻译 brain 的策略说明书（自然语言）到 OB API 调用。
不直接修改 OB 的 config.toml，而是通过 API 动态调整参数。
"""

import re
from typing import Optional

from ob_bridge.client import OBClient
from utils.display import log


# ── 策略模式匹配规则 ──

STRATEGY_PATTERNS = [
    # (正则, 提取函数, profile_edit操作)
    (r"盲区.*[加权重|加权|增强].*(\d+)", "knowledge_gap_weight"),
    (r"长视频.*[不降权|不惩罚|不加惩罚]", "long_video_no_penalty"),
    (r"实战.*权重.*(\d+\.?\d*)", "practical_weight"),
    (r"泛娱乐.*权重.*(\d+\.?\d*)", "entertainment_weight"),
    (r"Top\d+.*至少.*(\d+)%.*非舒适区", "diversity_quota"),
    (r"某?UP主.*([\w\u4e00-\u9fff]+).*低.*[准确率|质量].*降权", "up_downgrade"),
    (r"探索.*比例.*(\d+)", "explore_ratio"),
    (r"新增兴趣.*?[：:]\s*(.+)", "new_interest"),
    (r"不再关注.*?[：:]\s*(.+)", "remove_interest"),
]


async def parse_and_apply_strategy(strategy_text: str, ob_client: OBClient) -> dict:
    """解析策略说明书并应用到 OB

    Args:
        strategy_text: 策略说明书文本（自然语言）
        ob_client: OB HTTP 客户端

    Returns:
        dict: {"applied": [...], "skipped": [...]}
    """
    if not ob_client:
        return {"applied": [], "skipped": [], "error": "OB 客户端未初始化"}

    results = {"applied": [], "skipped": []}

    for line in strategy_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue

        for pattern, action, _ in STRATEGY_PATTERNS:
            match = re.search(pattern, line, re.IGNORECASE)
            if not match:
                continue

            try:
                if action == "knowledge_gap_weight":
                    pct = int(match.group(1))
                    log(f"[OB Bridge] 策略识别：盲区加权 {pct}%", "CONFIG")
                    results["applied"].append({"action": action, "line": line, "params": {"pct": pct}})

                elif action == "long_video_no_penalty":
                    log("[OB Bridge] 策略识别：长视频不降权", "CONFIG")
                    results["applied"].append({"action": action, "line": line})

                elif action == "practical_weight":
                    w = float(match.group(1))
                    log(f"[OB Bridge] 策略识别：实战权重 {w}", "CONFIG")
                    results["applied"].append({"action": action, "line": line, "params": {"weight": w}})

                elif action == "entertainment_weight":
                    w = float(match.group(1))
                    log(f"[OB Bridge] 策略识别：泛娱乐权重 {w}", "CONFIG")
                    results["applied"].append({"action": action, "line": line, "params": {"weight": w}})

                elif action == "diversity_quota":
                    pct = int(match.group(1))
                    log(f"[OB Bridge] 策略识别：多样性配额 {pct}%", "CONFIG")
                    results["applied"].append({"action": action, "line": line, "params": {"pct": pct}})

                elif action == "up_downgrade":
                    up_name = match.group(1)
                    ok = await ob_client.add_dislike_up(up_name, "审计发现内容低准确率")
                    if ok:
                        log(f"[OB Bridge] UP主降权已应用: {up_name}", "CONFIG")
                    results["applied"].append({"action": action, "line": line, "up": up_name, "ok": ok})

                elif action == "explore_ratio":
                    pct = int(match.group(1))
                    log(f"[OB Bridge] 策略识别：探索比例 {pct}%", "CONFIG")
                    results["applied"].append({"action": action, "line": line, "params": {"pct": pct}})

                elif action == "new_interest":
                    topic = match.group(1).strip()
                    ok = await ob_client.adjust_interest_weight(topic, 1.0)
                    if ok:
                        log(f"[OB Bridge] 新增兴趣已同步OB: {topic}", "CONFIG")
                    results["applied"].append({"action": action, "line": line, "topic": topic, "ok": ok})

                elif action == "remove_interest":
                    topic = match.group(1).strip()
                    ok = await ob_client.adjust_interest_weight(topic, 0.0)
                    if ok:
                        log(f"[OB Bridge] 移除兴趣已同步OB: {topic}", "CONFIG")
                    results["applied"].append({"action": action, "line": line, "topic": topic, "ok": ok})

                break  # 一条策略只匹配第一个规则

            except Exception as e:
                log(f"[OB Bridge] 策略应用失败 ({action}): {e}", "WARN")
                results["skipped"].append({"action": action, "line": line, "error": str(e)})

    return results


async def sync_knowledge_gaps_to_ob(
    gaps: list[dict],
    ob_client: OBClient,
    auto_weight_threshold: float = 0.3,
) -> int:
    """将知识库盲区同步到 OB 画像

    Args:
        gaps: 知识盲区列表 [{"topic": "xxx", "coverage": 0.15}, ...]
        ob_client: OB 客户端
        auto_weight_threshold: 覆盖率低于此值自动加权

    Returns:
        int: 成功同步的盲区数
    """
    if not ob_client or not gaps:
        return 0

    count = 0
    for gap in gaps:
        topic = gap.get("topic", "")
        coverage = gap.get("coverage", 1.0)

        if not topic:
            continue

        # 覆盖率低 → 加权召回
        if coverage < auto_weight_threshold:
            weight = 1.0 + (auto_weight_threshold - coverage) * 2  # 最少 1.0，最多约 1.6
            ok = await ob_client.adjust_interest_weight(
                topic=topic,
                weight=round(weight, 2),
                source="learning_bot_knowledge_gap",
            )
            if ok:
                count += 1
                log(f"[OB Bridge] 知识盲区加权: {topic} (覆盖率 {coverage:.0%} → 权重 {weight:.2f})", "CONFIG")

        # 覆盖率极高 → 降权（减少重复推送）
        elif coverage > 0.85:
            ok = await ob_client.adjust_interest_weight(
                topic=topic,
                weight=0.5,
                source="learning_bot_saturated",
            )
            if ok:
                log(f"[OB Bridge] 知识饱和降权: {topic} (覆盖率 {coverage:.0%} → 权重 0.5)", "CONFIG")

    return count


async def inject_curiosity_from_diary(
    diary_entry: dict,
    ob_client: OBClient,
    ttl_hours: int = 24,
) -> list[str]:
    """从日记中提取「知识生长点」并注入 OB 好奇心关键词

    Args:
        diary_entry: 日记条目字典 (含 title, growth_points, curiosity 等字段)
        ob_client: OB 客户端
        ttl_hours: 关键词存活时间

    Returns:
        list[str]: 成功注入的关键词列表
    """
    if not ob_client or not diary_entry:
        return []

    keywords = set()

    # 1. 提取 growth_points 字段
    growth = diary_entry.get("growth_points", "")
    if growth:
        # 简单按逗号/分号/顿号/换行分割，取前5个
        parts = re.split(r"[，,；;、\n]", str(growth))
        for p in parts[:5]:
            kw = p.strip()
            if len(kw) >= 2 and len(kw) <= 30:
                keywords.add(kw)

    # 2. 提取 curiosity 字段
    curiosity = diary_entry.get("curiosity", "")
    if curiosity:
        parts = re.split(r"[，,；;、\n]", str(curiosity))
        for p in parts[:3]:
            kw = p.strip()
            if 2 <= len(kw) <= 30:
                keywords.add(kw)

    # 3. 标题中的关键词
    title = diary_entry.get("title", "")
    if title and len(title) <= 20:
        keywords.add(title)

    # 逐一注入
    injected = []
    for kw in keywords:
        ok = await ob_client.add_curiosity_keyword(
            keyword=kw,
            weight=1.5,
            ttl_hours=ttl_hours,
            source="learning_bot_diary",
        )
        if ok:
            injected.append(kw)

    if injected:
        log(f"[OB Bridge] 好奇心注入 {len(injected)} 个关键词: {', '.join(injected[:5])}", "CONFIG")

    return injected


def extract_strategy_lines(evolution_result: dict) -> Optional[str]:
    """从进化结果中提取策略相关文本行"""
    parsed = evolution_result.get("parsed", {})
    lines = []

    new_rule = parsed.get("new_rule", "")
    if new_rule:
        lines.append(new_rule)

    style_delta = parsed.get("style_delta", "")
    if style_delta:
        lines.append(style_delta)

    reflection = parsed.get("reflection", "")
    if reflection:
        # 只取反射中的策略相关行
        for line in reflection.split("\n"):
            if any(kw in line for kw in ["权重", "降权", "比例", "盲区", "探索", "不再", "新增"]):
                lines.append(line)

    # ── Phase 4: 双份策略说明书提取 ──
    ob_strategy = parsed.get("ob_strategy", "")
    if ob_strategy:
        for line in ob_strategy.split("\n"):
            if any(kw in line for kw in ["权重", "降权", "比例", "盲区", "探索", "不再", "新增", "召回", "多样", "epsilon", "ε"]):
                lines.append(line)

    return "\n".join(lines) if lines else None


# ── Phase 4: 进化参数 → OB 调参 ──

EVOLUTION_TO_OB_MAPPINGS = {
    # evolution_key → (OB layer, operation, transformer)
    "epsilon_increase": ("surface", "add_curiosity_keyword", lambda val: ("广域探索", 2.0)),
    "epsilon_decrease": ("surface", "set_weight", lambda val: ("兴趣精化", 1.2)),
    "diversity_boost": ("values", "set_weight", lambda val: ("内容多样性", val)),
    "depth_focus": ("values", "set_weight", lambda val: ("深度优先", val)),
    "interest_shift": ("surface", "add_like", lambda val: (val, 1.5)),
    "interest_fade": ("surface", "remove", lambda val: (val, 0.0)),
    "up_downgrade": ("surface", "add_dislike", lambda val: (f"UP:{val}", 0.0)),
    "up_upgrade": ("surface", "add_like", lambda val: (f"UP:{val}", 1.5)),
}


async def apply_evolution_to_ob(
    evolution_result: dict,
    ob_client: OBClient,
    ab_context: str = "",
) -> dict:
    """将进化结果翻译成 OB 参数调整

    支持的变化类型：
    - epsilon/好奇心强度变化 → OB探索比例
    - 兴趣偏移 → OB召回权重调整
    - UP主评估变化 → OB UP权重
    - 多样性需求 → OB多样性配额
    - AB对比建议 → OB策略切换

    Args:
        evolution_result: 进化结果 dict (含 parsed)
        ob_client: OB 客户端
        ab_context: AB对比上下文（可选）

    Returns:
        dict: {"applied": [...], "skipped": [...]}
    """
    if not ob_client:
        return {"applied": [], "skipped": [], "error": "OB 客户端未初始化"}

    parsed = evolution_result.get("parsed", {})
    results = {"applied": [], "skipped": []}

    # 1. ε 变化 → 探索比例
    epsilon_delta = parsed.get("epsilon_delta") or parsed.get("curiosity_delta")
    if epsilon_delta is not None:
        try:
            eps = float(epsilon_delta)
            if abs(eps) > 0.1:
                direction = "↑" if eps > 0 else "↓"
                log(f"[OB Bridge] ε 变化: {direction}{abs(eps):.2f} → 调整OB探索策略", "CONFIG")
                if eps > 0:
                    # 好奇心增强 → 增加探索
                    await ob_client.edit_profile("surface", "add_curiosity_keyword",
                                                  "广域探索", weight=1.5 + min(eps, 0.5),
                                                  ttl_hours=48)
                    results["applied"].append({"action": "epsilon_increase", "delta": eps})
                else:
                    # 好奇心减弱 → 降回精准
                    await ob_client.edit_profile("surface", "set_weight",
                                                  "兴趣精化", weight=1.2)
                    results["applied"].append({"action": "epsilon_decrease", "delta": eps})
        except (ValueError, TypeError):
            pass

    # 2. 兴趣偏移 → OB权重
    new_interests = parsed.get("new_interests", "")
    if new_interests:
        for topic in str(new_interests).split(","):
            topic = topic.strip()
            if topic and len(topic) >= 2:
                ok = await ob_client.adjust_interest_weight(topic, 1.5,
                    source="learning_bot_evolution_interest_shift")
                results["applied"].append({"action": "interest_shift", "topic": topic, "ok": ok})
                if ok:
                    log(f"[OB Bridge] 兴趣偏移 → OB加权: {topic}", "CONFIG")

    fade_interests = parsed.get("fade_interests", "")
    if fade_interests:
        for topic in str(fade_interests).split(","):
            topic = topic.strip()
            if topic and len(topic) >= 2:
                ok = await ob_client.adjust_interest_weight(topic, 0.2,
                    source="learning_bot_evolution_interest_fade")
                results["applied"].append({"action": "interest_fade", "topic": topic, "ok": ok})
                if ok:
                    log(f"[OB Bridge] 兴趣消退 → OB降权: {topic}", "CONFIG")

    # 3. 多样性需求
    diversity_need = parsed.get("diversity_need") or parsed.get("cocoon_alert")
    if diversity_need:
        try:
            div_val = float(diversity_need)
            if div_val > 0.5:
                is_cocoon = str(diversity_need).lower() in ("true", "yes", "1") or div_val >= 1.0
                if is_cocoon:
                    # 茧房告警 → 大幅提升多样性
                    await ob_client.edit_profile("values", "set_weight",
                                                  "内容多样性", weight=2.0)
                    log("[OB Bridge] 茧房告警 → OB多样性配额拉满", "CONFIG")
                    results["applied"].append({"action": "diversity_boost", "weight": 2.0})
                else:
                    weight = 1.0 + div_val
                    await ob_client.edit_profile("values", "set_weight",
                                                  "内容多样性", weight=weight)
                    log(f"[OB Bridge] 多样性需求 → OB权重 {weight:.2f}", "CONFIG")
                    results["applied"].append({"action": "diversity_boost", "weight": weight})
        except (ValueError, TypeError):
            pass

    # 4. AB对比自动策略
    if ab_context:
        if "OB推荐效果显著优于原生" in ab_context:
            await ob_client.edit_profile("surface", "set_weight",
                                         "ob_prefer", weight=1.5)
            log("[OB Bridge] AB建议：加大OB配额（OB质量更优）", "CONFIG")
            results["applied"].append({"action": "ab_boost_ob", "reason": "AB_winner_ob"})
        elif "原生推荐质量显著优于OB" in ab_context:
            log("[OB Bridge] AB建议：降低OB配额，增加探索混合模式", "CONFIG")
            # 不降权OB，但标记
            results["applied"].append({"action": "ab_reduce_ob", "reason": "AB_winner_native"})

    # 5. 策略文本解析（保留原有逻辑）
    strategy_text = extract_strategy_lines(evolution_result)
    if strategy_text:
        parse_results = await parse_and_apply_strategy(strategy_text, ob_client)
        results["applied"].extend(parse_results.get("applied", []))
        results["skipped"].extend(parse_results.get("skipped", []))

    return results
