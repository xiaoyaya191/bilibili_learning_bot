# -*- coding: utf-8 -*-
"""core/contact_filter.py — 统一联系人黑白名单（私信 + 评论共用）。

配置结构（config.json）：
    "contact_filter": {
        "blacklist_uids": ["..."],      # 拉黑：不回复私信/评论，不在联系人列表显示
        "whitelist_enabled": false,      # 白名单模式：开启后仅白名单用户收到私信/评论回复
        "whitelist_uids": ["..."]        # 白名单：白名单模式下允许回复；私信场景仍保留“强制自动回复”语义
    }

兼容旧配置 private_message.blacklist_uids / whitelist_uids（与新分区取并集），
系统默认拉黑哔哩哔哩智能机（可用 private_message.disable_default_blacklist 关闭）。
"""


def _norm_uids(raw):
    """把 list/str 统一成去空白的 uid 字符串列表。"""
    if isinstance(raw, str):
        raw = raw.replace("，", ",").split(",")
    if not isinstance(raw, (list, tuple, set)):
        return []
    out = []
    for x in raw:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    return out


# B站官方机器人：默认拉黑（与旧 private_message 逻辑一致）
DEFAULT_BLACKLIST = {"12076317": "哔哩哔哩智能机"}


def effective_blacklist(cfg):
    """生效黑名单（contact_filter ∪ private_message 旧配置 ∪ 系统默认项）。"""
    if not isinstance(cfg, dict):
        cfg = {}
    cf = cfg.get("contact_filter") if isinstance(cfg.get("contact_filter"), dict) else {}
    pm = cfg.get("private_message") if isinstance(cfg.get("private_message"), dict) else {}
    merged = _norm_uids(cf.get("blacklist_uids")) + _norm_uids(pm.get("blacklist_uids"))
    if not pm.get("disable_default_blacklist", False) and not cf.get("disable_default_blacklist", False):
        for uid in DEFAULT_BLACKLIST:
            if uid not in merged:
                merged.append(uid)
    return set(merged)


def whitelist_mode_on(cfg):
    """白名单模式是否开启：开启后仅白名单用户收到私信/评论回复。"""
    if not isinstance(cfg, dict):
        return False
    cf = cfg.get("contact_filter") if isinstance(cfg.get("contact_filter"), dict) else {}
    return bool(cf.get("whitelist_enabled", False))


def effective_whitelist(cfg):
    """生效白名单（contact_filter ∪ private_message 旧配置）。"""
    if not isinstance(cfg, dict):
        cfg = {}
    cf = cfg.get("contact_filter") if isinstance(cfg.get("contact_filter"), dict) else {}
    pm = cfg.get("private_message") if isinstance(cfg.get("private_message"), dict) else {}
    return set(_norm_uids(cf.get("whitelist_uids")) + _norm_uids(pm.get("whitelist_uids")))


def filter_status(cfg, uid):
    """返回 uid 的过滤状态：'blocked'（黑名单）/ 'not_allowed'（白名单模式未命中）/ 'ok'。"""
    uid = str(uid or "").strip()
    if not uid:
        return "ok"
    if uid in effective_blacklist(cfg):
        return "blocked"
    if whitelist_mode_on(cfg) and uid not in effective_whitelist(cfg):
        return "not_allowed"
    return "ok"
