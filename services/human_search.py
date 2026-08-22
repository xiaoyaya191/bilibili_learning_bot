# -*- coding: utf-8 -*-
"""
拟人随机搜索（human search）
让机器人像真人一样"手痒"去搜点东西：综合记忆、私信、评论、观看历史、知识库，
生成一条真人会搜的搜索词。三种模式：
  human  可控拟人（默认，体验最好）：综合上下文+时段习惯，正经中带点随性
  chaos  随机放飞：从数据源随机抽碎片强拼，越出人意料越好（支持随机种子）
  off    关闭
支持自定义提示词（{context} {time_hint} {quirk} 占位符）。
"""
from __future__ import annotations

import json
import random
from datetime import datetime
from pathlib import Path
from typing import Any

from core.user_data import DATA_DIR, KNOWLEDGE_BASE_DIR, USER_DATA_DIR

# ── 默认设置（config.json 的 human_search 节缺失时使用） ──
DEFAULTS: dict[str, Any] = {
    "enabled": False,
    "mode": "human",                # human | chaos | off
    "interval_min_minutes": 20,     # 触发间隔下限
    "interval_max_minutes": 120,    # 触发间隔上限（每次在区间内随机取）
    "daily_max": 15,                # 每日触发上限
    "sources": {                    # 数据源开关
        "memory": True,             # 机器人记忆（known_ups/第一印象）
        "dm": True,                 # 私信记录
        "comments": True,           # 评论（发过的+回复过的）
        "watch_history": True,      # 刷过的视频
        "knowledge": True,          # 学过的知识（知识库分类/笔记标题）
    },
    "custom_prompt": "",            # 非空则整体替换默认提示词
    "random_seed": "",              # 空=真随机；数字=固定种子（chaos 可复现）
    "quirkiness": 0.5,              # 0-1 怪异度
}

DEFAULT_HUMAN_PROMPT = (
    "你正在扮演一个真实的 B 站重度用户，现在突然想搜点什么。不是任务，就是手痒。\n"
    "下面是你的真实数字生活碎片（记忆/私信/评论/看过的视频/学过的知识）的综合采样：\n"
    "{context}\n"
    "当前时段倾向：{time_hint}\n"
    "怪异度参数：{quirk}/1.0（越高越容易搜些奇怪但真实人类会搜的东西）\n"
    "要求：\n"
    "1. 结合上面的碎片，生成 1 条你在那一刻真的会输入进搜索框的内容；\n"
    "2. 像真人：有时正经查资料，有时纯粹好奇，有时无聊乱搜，偶尔口语化、带错别字也行；\n"
    "3. 只输出这一条搜索词本身，不要引号、不要解释、不要多余文字。"
)

DEFAULT_CHAOS_PROMPT = (
    "你是一个不可预测的真实人类，脑子里刚蹦出一个奇怪念头就要去搜索。\n"
    "以下是从你的数字生活里随机抽出的不相关碎片（强行拼在一起）：\n"
    "{context}\n"
    "当前时段：{time_hint}\n"
    "怪异度：{quirk}/1.0（放飞模式，越高越离谱，但仍必须是真人会搜的东西）\n"
    "要求：\n"
    "1. 把这些碎片脑补成一条搜索词，越出人意料越好，可以离谱但要像真人搜的；\n"
    "2. 只输出这一条搜索词，不要任何解释。"
)

_SOURCE_LABELS = {
    "memory": "记忆",
    "dm": "私信",
    "comments": "评论",
    "watch_history": "看过的视频",
    "knowledge": "学过的知识",
}


def get_settings() -> dict[str, Any]:
    """读取 config['human_search']（带默认值兜底）。"""
    cfg: dict[str, Any] = {}
    try:
        from core.config import load_config
        raw = load_config().get("human_search")
        if isinstance(raw, dict):
            cfg = raw
    except Exception:
        cfg = {}
    merged = json.loads(json.dumps(DEFAULTS))  # deep copy
    _deep_merge(merged, cfg)
    # 钳制
    try:
        merged["mode"] = str(merged.get("mode") or "human").lower()
        if merged["mode"] not in ("human", "chaos", "off"):
            merged["mode"] = "human"
    except Exception:
        merged["mode"] = "human"
    try:
        lo = max(3, int(merged.get("interval_min_minutes", 20)))
        hi = max(lo, int(merged.get("interval_max_minutes", 120)))
        merged["interval_min_minutes"], merged["interval_max_minutes"] = lo, hi
    except (TypeError, ValueError):
        merged["interval_min_minutes"], merged["interval_max_minutes"] = 20, 120
    try:
        merged["daily_max"] = max(1, min(200, int(merged.get("daily_max", 15))))
    except (TypeError, ValueError):
        merged["daily_max"] = 15
    try:
        merged["quirkiness"] = max(0.0, min(1.0, float(merged.get("quirkiness", 0.5))))
    except (TypeError, ValueError):
        merged["quirkiness"] = 0.5
    return merged


def _deep_merge(target: dict, patch: dict) -> dict:
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def _load_json(path: Path, default: Any = None) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    return default


# ── 数据源采样 ──
def _sample_memory(rng: random.Random) -> list[str]:
    data = _load_json(USER_DATA_DIR / "bot_memory.json", {}) or {}
    out: list[str] = []
    ups = data.get("known_ups") or {}
    if isinstance(ups, dict):
        for name, info in list(ups.items())[:200]:
            if not isinstance(info, dict):
                continue
            imp = str(info.get("first_impression") or "").strip()
            note = str(info.get("note") or "").strip()
            out.append(f"认识的UP「{name}」" + (f"，印象：{imp[:40]}" if imp else "") + (f"，备注：{note[:40]}" if note else ""))
    hist = data.get("history") or []
    if isinstance(hist, list):
        for item in hist[-80:]:
            if isinstance(item, dict):
                t = str(item.get("title") or "").strip()
                if t:
                    out.append(f"看过「{t[:50]}」")
    return out


def _sample_dm(rng: random.Random) -> list[str]:
    data = _load_json(DATA_DIR / "private_message_log.json", {}) or {}
    out: list[str] = []
    hist = data.get("history") or []
    if isinstance(hist, list):
        for item in hist[-60:]:
            if not isinstance(item, dict):
                continue
            incoming = str(item.get("incoming") or "").strip()
            reply = str(item.get("reply") or "").strip()
            if incoming:
                out.append(f"收到私信：「{incoming[:60]}」")
            elif reply:
                out.append(f"回复私信：「{reply[:60]}」")
    return out


def _sample_comments(rng: random.Random) -> list[str]:
    data = _load_json(DATA_DIR / "comment_log.json", {}) or {}
    out: list[str] = []
    hist = data.get("history") or []
    if isinstance(hist, list):
        for item in hist[-60:]:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content") or item.get("reply") or item.get("comment") or "").strip()
            title = str(item.get("title") or "").strip()
            if content:
                out.append(f"在「{title[:30] if title else '某视频'}」下评论过：「{content[:60]}」")
    convs = data.get("conversations") or {}
    if isinstance(convs, dict):
        for turns in list(convs.values())[:20]:
            if isinstance(turns, dict):
                turns = turns.get("turns") or []
            if isinstance(turns, list):
                for turn in turns[-4:]:
                    if isinstance(turn, dict) and turn.get("role") == "user":
                        c = str(turn.get("content") or "").strip()
                        if c:
                            out.append(f"别人回复你：「{c[:60]}」")
    return out


def _sample_watch(rng: random.Random) -> list[str]:
    data = _load_json(DATA_DIR / "watch_history_metadata.json", {}) or {}
    out: list[str] = []
    if isinstance(data, dict):
        for bvid, meta in list(data.items())[:200]:
            if not isinstance(meta, dict):
                continue
            title = str(meta.get("title") or "").strip()
            up = str(meta.get("up") or "").strip()
            cat = str(meta.get("category") or "").strip()
            if title:
                out.append(f"刷过「{title[:50]}」" + (f"（{up}的{cat}视频）" if up or cat else ""))
    return out


def _sample_knowledge(rng: random.Random) -> list[str]:
    out: list[str] = []
    try:
        kb = Path(KNOWLEDGE_BASE_DIR)
        if kb.exists():
            for d in kb.iterdir():
                if d.is_dir():
                    out.append(f"学过分类「{d.name}」")
                    mds = [m.stem for m in d.glob("*.md")]
                    for stem in rng.sample(mds, min(3, len(mds))) if mds else []:
                        out.append(f"做过笔记「{stem[:40]}」")
    except Exception:
        pass
    return out


_SAMPLERS = {
    "memory": _sample_memory,
    "dm": _sample_dm,
    "comments": _sample_comments,
    "watch_history": _sample_watch,
    "knowledge": _sample_knowledge,
}


def build_context(cfg: dict[str, Any] | None = None, rng: random.Random | None = None) -> list[str]:
    """从启用的数据源采样，返回碎片文本列表（每条一行）。"""
    cfg = cfg or get_settings()
    rng = rng or random.Random()
    sources = cfg.get("sources") or {}
    frags: list[str] = []
    for key, sampler in _SAMPLERS.items():
        if not sources.get(key, True):
            continue
        try:
            items = sampler(rng)
        except Exception:
            items = []
        rng.shuffle(items)
        frags.extend(items[:6])  # 每源最多 6 条
    rng.shuffle(frags)
    return frags[:18]  # 总量控制在 18 条内


def _time_hint() -> str:
    h = datetime.now().hour
    if 0 <= h < 6:
        return "深夜/凌晨，人容易猎奇、搜些白天不会搜的东西，也容易困但刷个不停"
    if 6 <= h < 9:
        return "早晨，正经查资料、规划学习的意愿高"
    if 9 <= h < 12:
        return "上午，专注学习时段，偏正经搜索"
    if 12 <= h < 14:
        return "午休，边吃边刷，轻松好奇向"
    if 14 <= h < 18:
        return "下午，学习+摸鱼混合"
    if 18 <= h < 22:
        return "晚间黄金档，兴趣最活跃，什么都想搜"
    return "夜里，放松+轻度好奇"


async def gen_query(cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """生成一条拟人搜索词。返回 {ok, query, mode, seed_used, frags}。"""
    cfg = cfg or get_settings()
    mode = str(cfg.get("mode") or "human").lower()
    if mode not in ("human", "chaos"):
        mode = "human"

    # 随机种子（chaos 支持固定种子复现；空=真随机）
    seed_str = str(cfg.get("random_seed") or "").strip()
    seed_used = None
    if mode == "chaos" and seed_str:
        try:
            seed_used = int(seed_str)
        except ValueError:
            try:
                seed_used = int(seed_str.encode("utf-8").hex()[:8], 16)
            except Exception:
                seed_used = None
    rng = random.Random(seed_used if seed_used is not None else None)

    frags = build_context(cfg, rng)
    if not frags:
        # 数据源全空时给一组通用碎片，避免提示词空上下文
        frags = ["刚注册B站没多久", "首页推荐什么都刷", "收藏夹吃灰中"]

    if mode == "chaos":
        rng.shuffle(frags)
        frags = frags[: max(3, int(len(frags) * 0.6))]  # 随机丢一部分，更不可控
    context = "\n".join(f"- {f}" for f in frags)
    quirk = float(cfg.get("quirkiness", 0.5))
    hint = _time_hint()

    custom = str(cfg.get("custom_prompt") or "").strip()
    if custom:
        prompt = (custom.replace("{context}", context)
                        .replace("{time_hint}", hint)
                        .replace("{quirk}", f"{quirk:.2f}"))
    elif mode == "chaos":
        prompt = DEFAULT_CHAOS_PROMPT.format(context=context, time_hint=hint, quirk=f"{quirk:.2f}")
    else:
        prompt = DEFAULT_HUMAN_PROMPT.format(context=context, time_hint=hint, quirk=f"{quirk:.2f}")

    from services._services_ai import call_ai
    answer = await call_ai(
        [{"role": "user", "content": prompt}],
        temperature=min(1.5, 0.7 + quirk * 0.6),  # 怪异度抬升随机性
        max_tokens=120,
        timeout=45,
        verbose=False,
    )
    query = str(answer or "").strip().strip('"').strip("'").strip()
    # 取第一行、限长
    query = query.splitlines()[0].strip() if query else ""
    query = query[:80]
    return {
        "ok": bool(query),
        "query": query,
        "mode": mode,
        "seed_used": seed_used,
        "frags": frags[:6],
        "time_hint": hint,
    }
