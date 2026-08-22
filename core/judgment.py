# -*- coding: utf-8 -*-
"""core/judgment.py — AI 判定/计分规则统一配置（判定提示词分区后端）。

config.json 的 "judgment" 节：
    "video_decision": {
        "objective_scoring_criteria": "…",   # 客观评分标准（怎么算分）
        "extra_requirements": ""              # 追加到评分提示词末尾的额外要求
    }
    "fallback": {                             # AI 不可用时的本地兜底评分参数
        "base_score": 4.7, "score_min": 3.0, "score_max": 7.5,
        "subtitle_tiers": [[150, 0.9], [500, 0.5], [1200, 0.4]],
        "comment_tiers": [[150, 0.2], [500, 0.2]],
        "danmaku_min_chars": 80, "danmaku_bonus": 0.1, "visual_weight": 0.15,
        "knowledge_terms": [...], "knowledge_bonus": 0.6,
        "entertainment_terms": [...], "entertainment_penalty": 0.6,
        "learnable_min_subtitle": 150, "learnable_min_score": 6.0
    }
    "interest_filter": {                      # 候选视频 AI 兴趣兜底判定
        "system_prompt": "…",
        "user_prompt_template": "…（占位符 {interests} {title} {up} {vis_desc} {vis_score} {engine_score} {engine_reason}）"
    }

默认值 = 原硬编码行为；未配置的键自动回落默认。
mtime 热更新：面板保存 config.json 后，运行中的机器人无需重启即可生效。
"""
import json
import os
import threading

try:
    from core.config import CONFIG_FILE
except ImportError:  # 独立测试环境
    CONFIG_FILE = os.path.join("config.json")

DEFAULTS = {
    "video_decision": {
        # brain/video_analysis.py 客观模式评分标准（默认与内置一致）
        "objective_scoring_criteria": (
            "评分标准：\n"
            "1. 标题与内容匹配度（是否标题党）\n"
            "2. 信息价值——深度分析类看观点深度，新闻汇总类看信息广度/信息量，技术教程类看实用性/可操作性\n"
            "3. 制作质量\n"
            "注意：不同类型的视频有不同的价值维度。'信息差/新闻汇总'类视频的价值在于快速覆盖多个热点话题"
            "提供的信息广度，不要统一用深度分析的标准去评判。只要有真实信息量的新闻汇总就应当认可。"
        ),
        "extra_requirements": "",
    },
    "fallback": {
        # brain/decision.py local_fallback_decision 的计分参数（默认与内置一致）
        "base_score": 4.7,
        "score_min": 3.0,
        "score_max": 7.5,
        "subtitle_tiers": [[150, 0.9], [500, 0.5], [1200, 0.4]],
        "comment_tiers": [[150, 0.2], [500, 0.2]],
        "danmaku_min_chars": 80,
        "danmaku_bonus": 0.1,
        "visual_weight": 0.15,
        "knowledge_terms": [
            "教程", "原理", "分析", "研究", "科普", "技术", "代码", "编程", "维修",
            "实验", "方法", "指南", "经验", "评测", "简历", "医学", "历史", "经济",
        ],
        "knowledge_bonus": 0.6,
        "entertainment_terms": ["搞笑", "整活", "鬼畜", "高光", "集锦", "对局", "抽卡", "reaction"],
        "entertainment_penalty": 0.6,
        "learnable_min_subtitle": 150,
        "learnable_min_score": 6.0,
    },
    "interest_filter": {
        # brain/_brain_interact.py judge_interest_with_ai 的提示词（默认与内置一致）
        "system_prompt": "你是B站视频兴趣筛选器，只输出合法JSON。",
        "user_prompt_template": (
            "\n请判断这个B站视频是否符合用户兴趣。\n\n"
            "用户兴趣: {interests}\n"
            "视频标题: {title}\n"
            "UP主: {up}\n"
            "封面印象: {vis_desc}\n"
            "封面印象分: {vis_score}\n"
            "引擎预评分: {engine_score}/10 ({engine_reason})\n\n"
            "要求:\n"
            "1. 综合标题、UP主、封面印象判断，不要只做关键词匹配。\n"
            "2. 只输出JSON，格式为:\n"
            '{"interested": true, "matched": ["兴趣1"], "reason": "一句话理由"}\n'
            "3. 如果明显不相关，interested=false，matched=[]。\n"
        ),
    },
}

_lock = threading.Lock()
_cache = {"mtime": None, "judgment": None}


def _deep_merge(base, override):
    """递归合并：override 覆盖 base，未给的键保留 base 默认。"""
    if not isinstance(override, dict):
        return base
    out = dict(base)
    for k, v in override.items():
        if k in out and isinstance(out[k], dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def reset_cache():
    """面板写入 config 后清缓存，使下一次读取立即生效。"""
    with _lock:
        _cache["mtime"] = None
        _cache["judgment"] = None


def get_judgment():
    """读取生效的判定配置（config.judgment 深合并默认值；mtime 变化时自动重读）。"""
    with _lock:
        mtime = None
        try:
            mtime = os.stat(CONFIG_FILE).st_mtime
        except OSError:
            pass
        if _cache["judgment"] is not None and mtime == _cache["mtime"]:
            return _cache["judgment"]
        user_cfg = {}
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                raw = json.load(f)
            j = raw.get("judgment") if isinstance(raw, dict) else None
            if isinstance(j, dict):
                user_cfg = j
        except (OSError, ValueError):
            user_cfg = {}
        merged = _deep_merge(DEFAULTS, user_cfg)
        _cache["mtime"] = mtime
        _cache["judgment"] = merged
        return merged


def _num(value, default):
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _terms(value, default):
    if isinstance(value, str):
        value = value.replace("，", ",").split(",")
    if not isinstance(value, (list, tuple)):
        return list(default)
    return [str(x).strip() for x in value if str(x).strip()] or list(default)


def fallback_params(judgment=None):
    """兜底评分参数（数值/词表容错归一，供 brain/decision.py 使用）。"""
    fb = (judgment or get_judgment()).get("fallback", DEFAULTS["fallback"])
    tiers = fb.get("subtitle_tiers") or DEFAULTS["fallback"]["subtitle_tiers"]
    ctiers = fb.get("comment_tiers") or DEFAULTS["fallback"]["comment_tiers"]

    def _norm_tiers(raw, default):
        out = []
        for pair in raw if isinstance(raw, list) else []:
            if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                out.append([_num(pair[0], 10**9), _num(pair[1], 0.0)])
        return out or default

    return {
        "base_score": _num(fb.get("base_score"), 4.7),
        "score_min": _num(fb.get("score_min"), 3.0),
        "score_max": _num(fb.get("score_max"), 7.5),
        "subtitle_tiers": _norm_tiers(tiers, DEFAULTS["fallback"]["subtitle_tiers"]),
        "comment_tiers": _norm_tiers(ctiers, DEFAULTS["fallback"]["comment_tiers"]),
        "danmaku_min_chars": _num(fb.get("danmaku_min_chars"), 80),
        "danmaku_bonus": _num(fb.get("danmaku_bonus"), 0.1),
        "visual_weight": _num(fb.get("visual_weight"), 0.15),
        "knowledge_terms": _terms(fb.get("knowledge_terms"), DEFAULTS["fallback"]["knowledge_terms"]),
        "knowledge_bonus": _num(fb.get("knowledge_bonus"), 0.6),
        "entertainment_terms": _terms(fb.get("entertainment_terms"), DEFAULTS["fallback"]["entertainment_terms"]),
        "entertainment_penalty": _num(fb.get("entertainment_penalty"), 0.6),
        "learnable_min_subtitle": _num(fb.get("learnable_min_subtitle"), 150),
        "learnable_min_score": _num(fb.get("learnable_min_score"), 6.0),
    }
