"""
services/favorability.py — 好感度系统：为每个 B 站用户维护一份全局好感度档案。

- Data/favorability.json  每个用户的好感度档案 {"users": {uid: {...}}}
- config.json favorability 节控制行为：
    enabled      总开关（默认 False：实验功能，可能不稳定）
    auto_adjust  开启后互动事件自动加分/扣分
    daily_cap    单用户单日自动加分上限（防刷）
    weights      各事件分值：reply/like/coin/favorite/dm/follow/risk
    history_limit 每个用户保留的变动记录条数

等级（0-100，默认 50）：
    0-19  戒备    20-39 陌生    40-59 点头之交
    60-79 熟人    80-94 朋友    95-100 挚友

时间统一使用 datetime.now().isoformat(timespec="seconds")。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from core.user_data import DATA_DIR
from utils.storage import JsonStore

DATA_FILE = DATA_DIR / "favorability.json"
_store = JsonStore(DATA_FILE)
_LOCK = threading.RLock()

# 事件 → 默认分值（负数表示扣分）
DEFAULT_WEIGHTS: dict[str, int] = {
    "reply": 2,      # 成功回复评论
    "like": 1,       # 点赞评论/视频
    "coin": 3,       # 投币支持
    "favorite": 2,   # 收藏视频
    "dm": 1,         # 私信互动
    "follow": 5,     # 关注UP主（机器人主动关注优质UP）
    "risk": -5,      # 互动里出现风险词/风控
}

DEFAULT_SETTINGS: dict[str, Any] = {
    "enabled": False,        # 默认关闭（实验功能）
    "auto_adjust": True,     # 开启后互动自动加减分
    "daily_cap": 10,         # 单用户单日自动加分上限
    "weights": dict(DEFAULT_WEIGHTS),
    "history_limit": 30,     # 每用户保留变动记录条数
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _load() -> dict:
    data = _store.read({})
    return data if isinstance(data, dict) else {}


def _save(data: dict) -> None:
    _store.write(data if isinstance(data, dict) else {})


def _get_settings() -> dict:
    """读取 config.json 的 favorability 节（带默认值兜底）。"""
    try:
        from core.config import load_config
        cfg = load_config().get("favorability") or {}
    except Exception:
        cfg = {}
    if not isinstance(cfg, dict):
        cfg = {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in cfg.items() if k in DEFAULT_SETTINGS})
    weights = dict(DEFAULT_WEIGHTS)
    stored_weights = cfg.get("weights")
    if isinstance(stored_weights, dict):
        for key in DEFAULT_WEIGHTS:
            if key in stored_weights:
                try:
                    weights[key] = int(stored_weights[key])
                except (TypeError, ValueError):
                    pass
    settings["weights"] = weights
    try:
        settings["daily_cap"] = max(0, int(settings["daily_cap"]))
    except (TypeError, ValueError):
        settings["daily_cap"] = DEFAULT_SETTINGS["daily_cap"]
    try:
        settings["history_limit"] = max(5, min(200, int(settings["history_limit"])))
    except (TypeError, ValueError):
        settings["history_limit"] = DEFAULT_SETTINGS["history_limit"]
    return settings


def save_settings(patch: dict) -> dict:
    """把 patch 合并进 config.json 的 favorability 节并返回新设置。"""
    from core.config import load_config, save_config
    cfg = load_config()
    fav = cfg.get("favorability")
    if not isinstance(fav, dict):
        fav = dict(DEFAULT_SETTINGS)
    if "enabled" in patch:
        fav["enabled"] = bool(patch["enabled"])
    if "auto_adjust" in patch:
        fav["auto_adjust"] = bool(patch["auto_adjust"])
    if "daily_cap" in patch:
        try:
            fav["daily_cap"] = max(0, int(patch["daily_cap"]))
        except (TypeError, ValueError):
            pass
    if "history_limit" in patch:
        try:
            fav["history_limit"] = max(5, min(200, int(patch["history_limit"])))
        except (TypeError, ValueError):
            pass
    if isinstance(patch.get("weights"), dict):
        weights = dict(DEFAULT_WEIGHTS)
        for key in DEFAULT_WEIGHTS:
            if key in patch["weights"]:
                try:
                    weights[key] = int(patch["weights"][key])
                except (TypeError, ValueError):
                    pass
        fav["weights"] = weights
    cfg["favorability"] = fav
    save_config(cfg)
    return _get_settings()


def is_enabled() -> bool:
    return bool(_get_settings().get("enabled"))


LEVELS = [
    (0, "戒备", "danger"),
    (20, "陌生", "muted"),
    (40, "点头之交", "info"),
    (60, "熟人", "info"),
    (80, "朋友", "ok"),
    (95, "挚友", "ok"),
]


def level_of(score: int) -> tuple:
    """返回 (等级名, 颜色档 danger/muted/info/ok)。"""
    score = max(0, min(100, int(score)))
    name, color = "戒备", "danger"
    for threshold, lvl, clr in LEVELS:
        if score >= threshold:
            name, color = lvl, clr
    return name, color


def _apply_change(uid: str, name: str, delta: int, reason: str, auto: bool):
    """内部：对用户应用一次分值变动，返回更新后的档案；uid 无效返回 None。"""
    uid = str(uid or "").strip()
    if not uid or uid.lower() in ("unknown", "none", "-"):
        return None
    data = _load()
    users = data.setdefault("users", {})
    profile = users.get(uid)
    if not isinstance(profile, dict):
        profile = {
            "name": name or uid,
            "score": 50,
            "created_at": _now_iso(),
            "history": [],
            "daily": {},
        }
    # 单日自动加分上限（手动调整与扣分不受限）
    if auto and delta > 0:
        daily = profile.setdefault("daily", {})
        day = _today()
        spent = int(daily.get(day) or 0)
        cap = _get_settings()["daily_cap"]
        if spent >= cap:
            return None
        delta = min(delta, cap - spent)
        daily[day] = spent + delta
        # 只保留最近 3 天，防文件膨胀
        for old_day in list(daily.keys()):
            if old_day < day:
                if len(daily) > 3:
                    daily.pop(old_day)
    try:
        old_score = int(profile.get("score", 50))
    except (TypeError, ValueError):
        old_score = 50
    new_score = max(0, min(100, old_score + int(delta)))
    profile["name"] = name or profile.get("name") or uid
    profile["score"] = new_score
    profile["updated_at"] = _now_iso()
    history = profile.setdefault("history", [])
    history.append({"time": _now_iso(), "delta": new_score - old_score,
                    "reason": str(reason or "")[:120], "auto": auto})
    limit = _get_settings()["history_limit"]
    profile["history"] = history[-limit:]
    users[uid] = profile
    _save(data)
    return profile


def record_event(uid: str, name: str, event: str, note: str = ""):
    """互动事件入口：功能关闭或 auto_adjust 关闭时静默跳过。"""
    settings = _get_settings()
    if not settings["enabled"] or not settings["auto_adjust"]:
        return None
    if event not in DEFAULT_WEIGHTS:
        return None
    delta = int(settings["weights"].get(event, 0))
    if delta == 0:
        return None
    reason = note or {
        "reply": "回复评论", "like": "点赞", "coin": "投币",
        "favorite": "收藏", "dm": "私信互动", "follow": "关注UP主", "risk": "风险互动",
    }.get(event, event)
    with _LOCK:
        return _apply_change(uid, name, delta, reason, auto=True)


def adjust(uid: str, name: str, delta: int, note: str = ""):
    """手动调整（不受日上限限制）。"""
    try:
        delta = int(delta)
    except (TypeError, ValueError):
        return None
    if delta == 0:
        return None
    with _LOCK:
        return _apply_change(uid, name, delta, note or "手动调整", auto=False)


def set_score(uid: str, name: str, score: int):
    """直接设置分数。"""
    try:
        score = max(0, min(100, int(score)))
    except (TypeError, ValueError):
        return None
    with _LOCK:
        data = _load()
        users = data.setdefault("users", {})
        profile = users.get(uid)
        if not isinstance(profile, dict):
            profile = {"name": name or uid, "score": 50,
                       "created_at": _now_iso(), "history": []}
        try:
            old = int(profile.get("score", 50))
        except (TypeError, ValueError):
            old = 50
        profile["score"] = score
        profile["name"] = name or profile.get("name") or uid
        profile["updated_at"] = _now_iso()
        history = profile.setdefault("history", [])
        history.append({"time": _now_iso(), "delta": score - old, "reason": "手动设置", "auto": False})
        profile["history"] = history[-_get_settings()["history_limit"]:]
        users[uid] = profile
        _save(data)
        return profile


def remove_user(uid: str) -> bool:
    with _LOCK:
        data = _load()
        users = data.setdefault("users", {})
        if str(uid) in users:
            users.pop(str(uid))
            _save(data)
            return True
        return False


def reset_all() -> int:
    """清空所有用户档案，返回清掉的数量。"""
    with _LOCK:
        data = _load()
        count = len(data.get("users") or {})
        _save({"users": {}})
        return count


def _public_profile(uid: str, profile: dict) -> dict:
    try:
        score = int(profile.get("score", 50))
    except (TypeError, ValueError):
        score = 50
    score = max(0, min(100, score))
    level, color = level_of(score)
    history = [h for h in (profile.get("history") or []) if isinstance(h, dict)]
    return {
        "uid": str(uid),
        "name": str(profile.get("name") or uid),
        "score": score,
        "level": level,
        "level_color": color,
        "created_at": profile.get("created_at", ""),
        "updated_at": profile.get("updated_at", ""),
        "history": history[-15:],
        "history_count": len(history),
    }


def list_users(query: str = "") -> list:
    """按名字/UID 模糊筛选，按好感度降序。"""
    data = _load()
    users = data.get("users") or {}
    q = str(query or "").strip().lower()
    items = []
    for uid, profile in users.items():
        if not isinstance(profile, dict):
            continue
        if q and q not in str(profile.get("name") or "").lower() and q not in str(uid).lower():
            continue
        items.append(_public_profile(uid, profile))
    items.sort(key=lambda x: (-x["score"], x.get("updated_at", "")))
    return items


def overview() -> dict:
    """统计概览。"""
    items = list_users()
    scores = [u["score"] for u in items]
    return {
        "total": len(items),
        "average": round(sum(scores) / len(scores), 1) if scores else 0,
        "best_friends": sum(1 for s in scores if s >= 95),
        "friends": sum(1 for s in scores if 80 <= s < 95),
        "wary": sum(1 for s in scores if s < 20),
    }


def get_payload(query: str = "") -> dict:
    """面板 GET /api/favorability 的统一返回体。"""
    settings = _get_settings()
    return {
        "ok": True,
        "settings": settings,
        "users": list_users(query),
        "overview": overview(),
    }
