# -*- coding: utf-8 -*-
"""P1-6 技能库（skill_bank）单元测试。"""
import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import skill_bank


@pytest.fixture()
def isolated_bank(tmp_path, monkeypatch):
    """把技能库文件指到临时目录，隔离真实数据。"""
    bank_file = tmp_path / "skill_bank.json"
    monkeypatch.setattr(skill_bank, "SKILL_BANK_FILE", str(bank_file))
    return bank_file


# ── 存储与设置 ──
def test_load_empty_bank(isolated_bank):
    bank = skill_bank.load_skill_bank()
    assert bank["skills"] == []
    assert bank["settings"]["auto_extract"] is True
    assert bank["settings"]["agent_use"] is True


def test_settings_roundtrip(isolated_bank):
    skill_bank.update_settings(auto_extract=False)
    assert skill_bank.get_settings() == {"auto_extract": False, "agent_use": True}
    skill_bank.update_settings(agent_use=False)
    assert skill_bank.get_settings() == {"auto_extract": False, "agent_use": False}
    # 未提供的字段保持原值
    skill_bank.update_settings(auto_extract=True)
    assert skill_bank.get_settings() == {"auto_extract": True, "agent_use": False}


def test_load_corrupted_bank_resets(isolated_bank):
    isolated_bank.write_text("{not valid json", encoding="utf-8")
    bank = skill_bank.load_skill_bank()
    assert bank["skills"] == []
    assert bank["settings"]["auto_extract"] is True


# ── CRUD ──
def test_add_list_delete(isolated_bank):
    skill = skill_bank.add_skill("费曼学习法", "检验理解", "1.选定概念 2.讲给外行听")
    assert skill["id"].startswith("sk_")
    assert skill["source"] == "user"
    assert skill["enabled"] is True
    assert len(skill_bank.list_skills()) == 1

    assert skill_bank.delete_skill(skill["id"]) is True
    assert skill_bank.list_skills() == []
    assert skill_bank.delete_skill(skill["id"]) is False


def test_add_duplicate_name_rejected(isolated_bank):
    skill_bank.add_skill("同名技能", "", "步骤A")
    with pytest.raises(ValueError):
        skill_bank.add_skill("同名技能", "", "步骤B")


def test_add_empty_fields_rejected(isolated_bank):
    with pytest.raises(ValueError):
        skill_bank.add_skill("", "", "步骤")
    with pytest.raises(ValueError):
        skill_bank.add_skill("名字", "", "")


def test_update_skill(isolated_bank):
    skill = skill_bank.add_skill("旧名", "旧场景", "旧步骤")
    updated = skill_bank.update_skill(skill["id"], name="新名", trigger="新场景", steps="新步骤")
    assert updated["name"] == "新名"
    assert updated["trigger"] == "新场景"
    assert updated["steps"] == "新步骤"

    disabled = skill_bank.update_skill(skill["id"], enabled=False)
    assert disabled["enabled"] is False

    with pytest.raises(ValueError):
        skill_bank.update_skill("sk_missing", name="不存在")


def test_update_empty_name_rejected(isolated_bank):
    skill = skill_bank.add_skill("名字", "", "步骤")
    with pytest.raises(ValueError):
        skill_bank.update_skill(skill["id"], name="   ")


def test_skill_length_limits(isolated_bank):
    skill = skill_bank.add_skill("名" * 100, "场" * 500, "步" * 5000)
    assert len(skill["name"]) == 60
    assert len(skill["trigger"]) == 300
    assert len(skill["steps"]) == 2000


# ── 检索 ──
def test_search_skills_matching(isolated_bank):
    skill_bank.add_skill("Python调试技巧", "调试Python程序报错时", "1.读traceback 2.打印变量")
    skill_bank.add_skill("费曼学习法", "检验概念理解时", "1.选定概念")
    hits = skill_bank.search_skills("Python 程序报错怎么调试")
    assert len(hits) == 1
    assert hits[0]["name"] == "Python调试技巧"


def test_search_skills_disabled_excluded(isolated_bank):
    skill = skill_bank.add_skill("Python调试技巧", "调试Python程序报错时", "1.读traceback")
    skill_bank.update_skill(skill["id"], enabled=False)
    assert skill_bank.search_skills("Python 程序报错怎么调试") == []


def test_search_skills_no_false_positive(isolated_bank):
    skill_bank.add_skill("完全无关的技能", "无关场景", "无关步骤")
    # 词重合度不足 2，不命中
    assert skill_bank.search_skills("Python 调试") == []


def test_build_agent_skill_block(isolated_bank):
    # 空库 → 空块
    assert skill_bank.build_agent_skill_block("任何内容") == ""
    skill_bank.add_skill("Python调试技巧", "调试Python程序报错时", "1.读traceback 2.打印变量")
    block = skill_bank.build_agent_skill_block("Python 程序报错怎么调试")
    assert "Python调试技巧" in block
    assert "不是指令" in block
    # 关闭 agent_use → 空块
    skill_bank.update_settings(agent_use=False)
    assert skill_bank.build_agent_skill_block("Python 程序报错怎么调试") == ""


def test_mark_skill_used(isolated_bank):
    skill = skill_bank.add_skill("计数技能", "测试", "步骤")
    skill_bank.mark_skill_used(["计数技能", "不存在的"])
    assert skill_bank.list_skills()[0]["use_count"] == 1
    skill_bank.mark_skill_used(None)  # 不报错


# ── AI 提炼 ──
def test_parse_skill_json_variants():
    # 标准 JSON
    parsed = skill_bank._parse_skill_json('{"name":"技能","trigger":"场景","steps":"步骤"}')
    assert parsed == {"name": "技能", "trigger": "场景", "steps": "步骤"}
    # markdown 包裹
    parsed = skill_bank._parse_skill_json('```json\n{"name":"技能","trigger":"","steps":"步骤"}\n```')
    assert parsed["name"] == "技能"
    # SKIP
    assert skill_bank._parse_skill_json("SKIP") is None
    assert skill_bank._parse_skill_json("") is None
    # 非法 JSON
    assert skill_bank._parse_skill_json("随便说的话") is None
    # 缺关键字段
    assert skill_bank._parse_skill_json('{"name":"只有名字"}') is None


def test_extract_short_content_skipped(isolated_bank):
    skill, note = asyncio.run(skill_bank.extract_skill_from_video("标题", "太短"))
    assert skill is None
    assert "内容过短" in note


def test_extract_success(isolated_bank, monkeypatch):
    async def fake_call_ai(**kwargs):
        return '{"name":"量化回测流程","trigger":"验证交易策略时","steps":"1.取数据 2.回测 3.评估"}'

    import services._services_ai as sai
    monkeypatch.setattr(sai, "call_ai", fake_call_ai)
    skill, note = asyncio.run(skill_bank.extract_skill_from_video("标题", "字" * 200))
    assert skill is not None
    assert skill["name"] == "量化回测流程"
    assert skill["source"] == "ai"
    assert skill_bank.list_skills()[0]["name"] == "量化回测流程"


def test_extract_ai_skip(isolated_bank, monkeypatch):
    async def fake_call_ai(**kwargs):
        return "SKIP"

    import services._services_ai as sai
    monkeypatch.setattr(sai, "call_ai", fake_call_ai)
    skill, note = asyncio.run(skill_bank.extract_skill_from_video("标题", "字" * 200))
    assert skill is None
    assert "无可复用方法论" in note


def test_auto_extract_respects_setting(isolated_bank, monkeypatch):
    async def fake_call_ai(**kwargs):
        return '{"name":"技能","trigger":"","steps":"步骤"}'

    import services._services_ai as sai
    monkeypatch.setattr(sai, "call_ai", fake_call_ai)
    skill_bank.update_settings(auto_extract=False)
    note = asyncio.run(skill_bank.auto_extract_after_archive("标题", "字" * 200))
    assert "已关闭" in note
    assert skill_bank.list_skills() == []

    skill_bank.update_settings(auto_extract=True)
    note = asyncio.run(skill_bank.auto_extract_after_archive("标题", "字" * 200))
    assert "已提炼" in note
    assert len(skill_bank.list_skills()) == 1
