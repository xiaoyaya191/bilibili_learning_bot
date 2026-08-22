# -*- coding: utf-8 -*-
"""core/variety.py — "节目效果"随机模式（实验性，默认关闭）。

开启后机器人会随机出现一些"不按剧本走"的想法：
- 兴趣判定随机翻转（小概率放过不相关视频 / 错杀相关视频，理由千奇百怪）
- 本地兜底评分加随机抖动
- 兴趣判定提示词注入一句"今日风向"

配置（config.json）：
    "variety": {"enabled": false, "intensity": 0.5}

intensity ∈ [0.1, 1.0]，越大越疯。判定提示词分区提供开关，运行中热更新。
"""
from __future__ import annotations

import os
import random
import threading

try:
    from core.config import CONFIG_FILE
except ImportError:  # 独立测试环境
    CONFIG_FILE = os.path.join("config.json")

_lock = threading.Lock()
_cache = {"mtime": None, "cfg": None}

_FLIP_REASON_PASS = (
    "节目效果：突然就想看看这个",
    "节目效果：直觉说这个有意思",
    "节目效果：今天心情好，放行",
    "节目效果：标题太怪了，忍不住",
    "节目效果：缘分到了",
)
_FLIP_REASON_BLOCK = (
    "节目效果：今天看这个不来电",
    "节目效果：莫名其妙就是不想看",
    "节目效果：直觉说跳过",
    "节目效果：这个UP主今天气场不合",
)
_FLAVORS = (
    "今日节目效果开启：你的判断允许带一点随性和怪念头，但保持JSON格式不变。",
    "今日节目效果开启：像半夜刷视频的真实人类一样凭直觉判断，格式仍需严格。",
    "今日节目效果开启：可以偶发地表达突发奇想，输出格式必须合法。",
)


def _load() -> dict:
    with _lock:
        mtime = None
        try:
            mtime = os.stat(CONFIG_FILE).st_mtime
        except OSError:
            pass
        if _cache["cfg"] is not None and mtime == _cache["mtime"]:
            return _cache["cfg"]
        cfg = {}
        try:
            import json
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                raw = json.load(f)
            v = raw.get("variety") if isinstance(raw, dict) else None
            if isinstance(v, dict):
                cfg = v
        except (OSError, ValueError):
            cfg = {}
        _cache["mtime"] = mtime
        _cache["cfg"] = cfg
        return cfg


def reset_cache() -> None:
    with _lock:
        _cache["mtime"] = None
        _cache["cfg"] = None


def enabled() -> bool:
    return bool(_load().get("enabled", False))


def intensity() -> float:
    try:
        return max(0.1, min(1.0, float(_load().get("intensity", 0.5))))
    except (TypeError, ValueError):
        return 0.5


def interest_flip(title: str = ""):
    """节目效果：小概率翻转兴趣判定结果。

    返回 None 表示不干预；返回 (passed: bool, reason: str) 表示强制翻转。
    """
    if not enabled():
        return None
    chance = 0.08 * intensity()
    if random.random() >= chance:
        return None
    if random.random() < 0.6:
        return True, random.choice(_FLIP_REASON_PASS)
    return False, random.choice(_FLIP_REASON_BLOCK)


def score_jitter(score: float) -> float:
    """节目效果：本地兜底评分加随机抖动（±0.9 * intensity）。"""
    if not enabled():
        return score
    try:
        base = float(score)
    except (TypeError, ValueError):
        return score
    return round(base + random.uniform(-0.9, 0.9) * intensity(), 1)


def prompt_flavor() -> str:
    """节目效果：注入到兴趣判定 system 提示词的一句"今日风向"。"""
    if not enabled():
        return ""
    return random.choice(_FLAVORS)
