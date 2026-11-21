"""系统设置 → 数据目录：接口行为与路径安全检查。"""
import json
from pathlib import Path

import pytest

import web_panel
from core import storage_location


@pytest.fixture
def env(tmp_path, monkeypatch):
    """隔离默认根与当前数据目录，绝不动真实 LOCALAPPDATA。"""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.delenv("BILI_USER_DATA_DIR", raising=False)
    current = tmp_path / "current"
    (current / "Data").mkdir(parents=True)
    (current / "Data" / "config.json").write_text('{"api":{"unified_api_key":"secret"}}', encoding="utf-8")
    (current / "KnowledgeBase").mkdir(parents=True)
    (current / "KnowledgeBase" / "note.md").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(web_panel, "USER_DATA_DIR", current)
    monkeypatch.setattr(web_panel.app, "testing", True)
    return web_panel.app.test_client(), tmp_path, current


def _pointer(tmp_path: Path) -> Path:
    return tmp_path / "localappdata" / "BiliLearn" / "Data" / storage_location.POINTER_NAME


def test_get_reports_current_default_and_groups(env):
    client, tmp_path, current = env
    payload = client.get("/api/storage").get_json()
    assert payload["ok"]
    assert Path(payload["current_path"]) == current
    assert Path(payload["configured_path"]) == current
    assert not payload["restart_required"] and not payload["env_override"]
    assert Path(payload["default_path"]) == tmp_path / "localappdata" / "BiliLearn"
    assert {"data", "knowledge", "mindmaps"} <= set(payload["groups"])


def test_post_saves_pointer_and_marks_restart_required(env):
    client, tmp_path, current = env
    target = tmp_path / "portable" / "BiliLearnData"
    result = client.post("/api/storage", json={"path": str(target)}).get_json()
    assert result["ok"], result
    assert result["restart_required"] is True
    assert Path(result["configured_path"]) == target.resolve()
    assert Path(result["current_path"]) == current

    saved = json.loads(_pointer(tmp_path).read_text(encoding="utf-8"))
    assert Path(saved["path"]) == target.resolve()

    after = client.get("/api/storage").get_json()
    assert Path(after["configured_path"]) == target.resolve()
    assert after["restart_required"] is True


@pytest.mark.parametrize(
    "candidate, expected",
    [
        ("C:\\", "磁盘根目录"),
        ("relative-folder", "绝对路径"),
        (".", "绝对路径"),
    ],
)
def test_rejects_unsafe_paths(env, candidate, expected):
    client, tmp_path, _ = env
    response = client.post("/api/storage", json={"path": candidate})
    assert response.status_code == 400
    body = response.get_json()
    assert not body["ok"] and expected in body["message"]
    assert not _pointer(tmp_path).exists()


def test_rejects_program_directory(env):
    client, tmp_path, _ = env
    response = client.post("/api/storage", json={"path": str(Path(web_panel.BASE_DIR) / "user-data")})
    assert response.status_code == 400
    assert "程序所在目录" in response.get_json()["message"]


def test_rejects_target_inside_current_root(env):
    client, tmp_path, current = env
    response = client.post("/api/storage", json={"path": str(current / "inner")})
    assert response.status_code == 400
    assert "不能位于当前数据目录内部" in response.get_json()["message"]


def test_rejects_non_dict_body_and_fills_pointer_only_after_validation(env):
    client, tmp_path, _ = env
    assert client.post("/api/storage", json=["nope"]).status_code == 400
    assert not _pointer(tmp_path).exists()


def test_migrate_copies_missing_files_without_overwriting(env):
    client, tmp_path, current = env
    target = tmp_path / "newdata"
    target.mkdir()
    (target / "Data").mkdir()
    (target / "Data" / "config.json").write_text('{"keep":"me"}', encoding="utf-8")

    result = client.post("/api/storage", json={"path": str(target), "migrate": True}).get_json()
    assert result["ok"], result
    assert result["migrated"]["copied_files"] == 1  # 只有 KnowledgeBase/note.md
    assert result["migrated"]["skipped_files"] >= 1  # config.json 已存在，跳过
    assert (target / "KnowledgeBase" / "note.md").read_text(encoding="utf-8") == "hello"
    assert json.loads((target / "Data" / "config.json").read_text(encoding="utf-8")) == {"keep": "me"}
    # 迁移是复制，源目录保持不变
    assert (current / "KnowledgeBase" / "note.md").exists()


def test_reset_restores_default(env):
    client, tmp_path, _ = env
    client.post("/api/storage", json={"path": str(tmp_path / "portable")})
    assert _pointer(tmp_path).exists()

    result = client.post("/api/storage/reset", json={}).get_json()
    assert result["ok"]
    assert Path(result["configured_path"]) == tmp_path / "localappdata" / "BiliLearn"
    assert not _pointer(tmp_path).exists()


def test_env_override_blocks_changes(env, monkeypatch):
    client, tmp_path, _ = env
    monkeypatch.setenv("BILI_USER_DATA_DIR", str(tmp_path / "portable"))
    body = client.post("/api/storage", json={"path": str(tmp_path / "other")}).get_json()
    assert body["ok"] is False and "BILI_USER_DATA_DIR" in body["message"]
    assert not _pointer(tmp_path).exists()
    assert client.get("/api/storage").get_json()["env_override"] is True
    assert client.post("/api/storage/reset", json={}).get_json()["ok"] is False


def test_authentication_required(env, monkeypatch):
    client, tmp_path, _ = env
    monkeypatch.setattr(web_panel.app, "testing", False)
    assert client.get("/api/storage").status_code == 401
    assert client.post("/api/storage", json={"path": str(tmp_path / "x")}).status_code == 401
    assert client.post("/api/storage/reset", json={}).status_code == 401


def test_migrate_skips_runtime_files_and_is_idempotent(tmp_path):
    source = tmp_path / "old"
    target = tmp_path / "new"
    (source / "Data").mkdir(parents=True)
    (source / "Data" / "bot.lock").write_text("lock", encoding="utf-8")
    (source / "Data" / storage_location.POINTER_NAME).write_text("{}", encoding="utf-8")
    (source / "Data" / "config.json").write_text("{}", encoding="utf-8")

    first = storage_location.migrate_contents(source, target)
    assert first["copied_files"] == 1
    assert not (target / "Data" / "bot.lock").exists()
    assert not (target / "Data" / storage_location.POINTER_NAME).exists()
    second = storage_location.migrate_contents(source, target)
    assert second["copied_files"] == 0 and second["skipped_files"] == 1


def test_validate_target_rejects_file_and_accepts_directory(tmp_path):
    file_path = tmp_path / "not-a-dir.txt"
    file_path.write_text("x", encoding="utf-8")
    with pytest.raises(storage_location.StoragePathError):
        storage_location.validate_target(str(file_path))
    created = storage_location.validate_target(str(tmp_path / "deep" / "nested"))
    assert created.is_dir()


def test_account_mode_switches_accounts_root_instead_of_blocking(env, monkeypatch):
    """面板启动后总是带 BILI_ACCOUNT_ID；此时应能迁移整个账号根，而不是 400。"""
    client, tmp_path, current = env
    accounts_root = tmp_path / "root"
    workspace = accounts_root / "accounts" / "account-001"
    (workspace / "Data").mkdir(parents=True)
    (workspace / "Data" / "config.json").write_text("{}", encoding="utf-8")
    (accounts_root / "accounts.json").write_text('{"accounts":[]}', encoding="utf-8")
    monkeypatch.setenv("BILI_ACCOUNT_ID", "account-001")
    monkeypatch.setenv("BILI_ACCOUNTS_ROOT", str(accounts_root))
    monkeypatch.setenv("BILI_USER_DATA_DIR", str(workspace))
    monkeypatch.setattr(web_panel, "USER_DATA_DIR", workspace)

    payload = client.get("/api/storage").get_json()
    assert payload["account_mode"] is True
    assert Path(payload["current_path"]) == accounts_root
    assert Path(payload["workspace_path"]) == workspace
    assert payload["env_override"] is False  # 程序自己写入的 BILI_USER_DATA_DIR 不算用户覆盖

    target = tmp_path / "moved-root"
    result = client.post("/api/storage", json={"path": str(target), "migrate": True}).get_json()
    assert result["ok"], result
    assert result["account_mode"] is True
    assert (target / "accounts.json").exists()
    assert (target / "accounts" / "account-001" / "Data" / "config.json").exists()
    assert Path(json.loads(_pointer(tmp_path).read_text(encoding="utf-8"))["path"]) == target.resolve()


def test_panel_html_exposes_data_directory_card():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")
    for marker in (
        'id="sysStorageBox"',
        'id="sysStoragePath"',
        'id="sysStorageMigrate"',
        "function loadSysStorage",
        "function saveSysStorage",
        "function resetSysStorage",
        "/api/storage/reset",
        "function rf_sys(){loadSysStorage()}",
    ):
        assert marker in template
