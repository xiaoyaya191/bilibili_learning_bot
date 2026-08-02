import os
import sys
import importlib
from pathlib import Path

import core.config as core_config
import core.user_data as user_data


def test_private_data_uses_user_storage():
    assert Path(core_config.CONFIG_FILE) == user_data.DATA_DIR / "config.json"
    assert Path(core_config.COOKIE_FILE) == user_data.DATA_DIR / "bilibili_cookies.json"
    assert user_data.DATA_DIR.parent == user_data.USER_DATA_DIR


def test_project_owned_defaults_stay_in_project():
    assert user_data.KNOWLEDGE_BASE_DIR == user_data.PROJECT_DIR / "KnowledgeBase"
    assert user_data.HTML_EXPORTS_DIR == user_data.PROJECT_DIR / "html_exports"
    assert user_data.MINDMAPS_DIR == user_data.PROJECT_DIR / "MindMaps"
    assert user_data.WORD_DIR == user_data.PROJECT_DIR / "Word"


def test_frozen_release_keeps_generated_artifacts_in_user_data(monkeypatch, tmp_path):
    monkeypatch.setenv("BILI_USER_DATA_DIR", str(tmp_path / "BiliLearn"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "app-resources"), raising=False)
    frozen_data = importlib.reload(user_data)
    try:
        assert frozen_data.KNOWLEDGE_BASE_DIR == frozen_data.USER_DATA_DIR / "KnowledgeBase"
        assert frozen_data.HTML_EXPORTS_DIR == frozen_data.USER_DATA_DIR / "html_exports"
        assert frozen_data.MINDMAPS_DIR == frozen_data.USER_DATA_DIR / "MindMaps"
        assert frozen_data.WORD_DIR == frozen_data.USER_DATA_DIR / "Word"
    finally:
        monkeypatch.delenv("BILI_USER_DATA_DIR", raising=False)
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.delattr(sys, "_MEIPASS", raising=False)
        importlib.reload(user_data)


def test_explicit_user_data_dir_does_not_import_host_legacy_profile(monkeypatch, tmp_path):
    isolated = tmp_path / "isolated"
    host_home = tmp_path / "host-home"
    legacy_config = host_home / "BiliLearn" / "Data" / "config.json"
    legacy_config.parent.mkdir(parents=True)
    legacy_config.write_text('{"api": {"unified_api_key": "host-secret"}}', encoding="utf-8")

    monkeypatch.setenv("BILI_USER_DATA_DIR", str(isolated))
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: host_home))
    isolated_data = importlib.reload(user_data)
    try:
        assert not (isolated_data.DATA_DIR / "config.json").exists()
    finally:
        monkeypatch.delenv("BILI_USER_DATA_DIR", raising=False)
        importlib.reload(user_data)


def test_frozen_asr_model_default_uses_writable_user_data(monkeypatch, tmp_path):
    import xingye_bot.asr_engine as asr_engine

    monkeypatch.setenv("BILI_USER_DATA_DIR", str(tmp_path / "BiliLearn"))
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    frozen_data = importlib.reload(user_data)
    try:
        assert asr_engine.ASREngine({})._get_model_dir() == str(
            frozen_data.USER_DATA_DIR / "models" / "asr"
        )
    finally:
        monkeypatch.delenv("BILI_USER_DATA_DIR", raising=False)
        monkeypatch.delattr(sys, "frozen", raising=False)
        importlib.reload(user_data)


def test_relative_custom_knowledge_path_is_project_relative():
    path = core_config.resolve_knowledge_base_dir({"knowledge": {"base_dir": "research-notes"}})
    assert Path(path) == Path(core_config.BASE_DIR) / "research-notes"


def test_absolute_custom_knowledge_path_is_preserved(tmp_path):
    configured = str(tmp_path / "custom-kb")
    path = core_config.resolve_knowledge_base_dir({"knowledge_base_dir": configured})
    assert os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(configured))


def test_private_feature_state_shares_data_directory():
    from persona.psycho import DATA_DIR as psycho_data_dir
    from services.interest_engine import ENGINE_CONFIG_FILE

    assert Path(psycho_data_dir) == user_data.DATA_DIR
    assert Path(ENGINE_CONFIG_FILE) == user_data.DATA_DIR / "interest_engine.json"
