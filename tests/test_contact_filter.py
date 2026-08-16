# -*- coding: utf-8 -*-
"""联系人黑白名单（core/contact_filter）统一过滤测试。"""
from pathlib import Path

from core.contact_filter import (
    DEFAULT_BLACKLIST,
    effective_blacklist,
    effective_whitelist,
    filter_status,
    whitelist_mode_on,
)


def _cfg(**cf):
    return {"contact_filter": cf}


def test_default_blacklist_blocks_official_bot():
    cfg = _cfg(blacklist_uids=[])
    assert "12076317" in effective_blacklist(cfg)
    assert filter_status(cfg, "12076317") == "blocked"
    # 可显式关闭系统默认拉黑
    cfg2 = _cfg(blacklist_uids=[], disable_default_blacklist=True)
    assert "12076317" not in effective_blacklist(cfg2)
    assert filter_status(cfg2, "12076317") == "ok"


def test_blacklist_blocks_dm_and_comment_path():
    cfg = _cfg(blacklist_uids=["10086"])
    assert filter_status(cfg, "10086") == "blocked"
    assert filter_status(cfg, "10000") == "ok"


def test_whitelist_mode_only_allows_whitelisted():
    cfg = _cfg(whitelist_enabled=True, whitelist_uids=["42"])
    assert whitelist_mode_on(cfg) is True
    assert filter_status(cfg, "42") == "ok"
    assert filter_status(cfg, "43") == "not_allowed"
    # 模式关闭时不再限制
    cfg_off = _cfg(whitelist_enabled=False, whitelist_uids=["42"])
    assert whitelist_mode_on(cfg_off) is False
    assert filter_status(cfg_off, "43") == "ok"


def test_blacklist_wins_over_whitelist():
    cfg = _cfg(blacklist_uids=["7"], whitelist_enabled=True, whitelist_uids=["7"])
    assert filter_status(cfg, "7") == "blocked"


def test_legacy_private_message_lists_are_merged():
    cfg = {
        "contact_filter": {"blacklist_uids": ["1"], "whitelist_uids": ["2"]},
        "private_message": {"blacklist_uids": ["9"], "whitelist_uids": ["8"]},
    }
    assert effective_blacklist(cfg) >= {"1", "9"}
    assert effective_whitelist(cfg) >= {"2", "8"}
    # 旧配置单独存在时也生效
    legacy = {"private_message": {"blacklist_uids": ["9"], "whitelist_uids": ["8"]}}
    assert "9" in effective_blacklist(legacy)
    assert "8" in effective_whitelist(legacy)


def test_uid_normalization_accepts_string_and_list():
    cfg = _cfg(blacklist_uids="100，200, 300")
    assert effective_blacklist(cfg) >= {"100", "200", "300"}
    assert filter_status({}, "") == "ok"


def test_panel_template_exposes_whitelist_management_ui():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")
    for marker in (
        "dmRenderFilterPanel",
        "/api/dm/system/whitelist/mode",
        "白名单模式",
        "黑名单与白名单",
    ):
        assert marker in template


def test_web_panel_registers_whitelist_routes():
    import web_panel

    rules = {r.rule for r in web_panel.app.url_map.iter_rules()}
    assert "/api/dm/system/whitelist" in rules
    assert "/api/dm/system/whitelist/mode" in rules
    assert DEFAULT_BLACKLIST  # 系统默认黑名单非空
