import builtins
import json
from pathlib import Path



def _allow_web_request(monkeypatch, web_panel):
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])


def test_web_factory_reset_expires_confirmation_token(monkeypatch):
    import web_panel

    _allow_web_request(monkeypatch, web_panel)
    client = web_panel.app.test_client()
    token = client.post("/api/factory-reset/request").get_json()["token"]
    created_at = web_panel._factory_reset_pending_token["created_at"]
    monkeypatch.setattr(web_panel.time, "time", lambda: created_at + web_panel._FACTORY_RESET_TOKEN_TTL_SECONDS + 1)

    response = client.post("/api/factory-reset", json={"confirm_token": token})

    assert response.status_code == 403
    assert response.get_json()["ok"] is False


def test_web_factory_reset_removes_web_credentials(monkeypatch, tmp_path):
    import web_panel

    _allow_web_request(monkeypatch, web_panel)
    data_dir = tmp_path / "Data"
    user_dir = tmp_path / "user"
    config_file = data_dir / "config.json"
    data_dir.mkdir(parents=True)
    user_dir.mkdir()
    config_file.write_text(json.dumps({"web": {"username": "user", "password": "hash"}}), encoding="utf-8")
    (data_dir / ".web_secret_key").write_text("secret", encoding="utf-8")

    import core.config as core_config
    import core.user_data as user_data

    monkeypatch.setattr(web_panel, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_panel, "CONFIG_FILE", config_file)
    monkeypatch.setattr(web_panel, "USER_DATA_DIR", user_dir)
    monkeypatch.setattr(web_panel, "BASE_DIR", tmp_path / "project")
    monkeypatch.setattr(web_panel, "get_backup_dir", lambda: tmp_path / "backups")
    monkeypatch.setattr(core_config, "CIPHER_KEY_FILE", str(user_dir / ".cipher_key"))
    monkeypatch.setattr(user_data, "HIGHLIGHTS_DIR", user_dir / "highlights")
    monkeypatch.setattr(user_data, "HTML_EXPORTS_DIR", user_dir / "html_exports")
    monkeypatch.setattr(user_data, "MINDMAPS_DIR", user_dir / "MindMaps")
    monkeypatch.setattr(user_data, "WORD_DIR", user_dir / "Word")
    monkeypatch.setattr(user_data, "QR_CODES_DIR", user_dir / "qr_codes")
    client = web_panel.app.test_client()
    token = client.post("/api/factory-reset/request").get_json()["token"]

    response = client.post("/api/factory-reset", json={"confirm_token": token})

    assert response.get_json()["ok"] is True
    assert not config_file.exists()
    assert not (data_dir / ".web_secret_key").exists()


def test_cli_quick_factory_reset_uses_one_confirmation(monkeypatch, tmp_path):
    import cli.app as app
    import core.config as core_config
    import core.user_data as user_data

    data_dir = tmp_path / "Data"
    data_dir.mkdir()
    config_file = data_dir / "config.json"
    config_file.write_text(json.dumps({"web": {"username": "user", "password": "hash"}}), encoding="utf-8")
    user_root = tmp_path / "user"
    user_root.mkdir()
    project_root = tmp_path / "project"
    project_root.mkdir()
    monkeypatch.setattr(app, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(app, "BASE_DIR", str(project_root))
    monkeypatch.setattr(core_config, "DATA_DIR", str(data_dir))
    monkeypatch.setattr(app, "CONFIG_FILE", str(config_file))
    monkeypatch.setattr(app, "BACKUP_DIR", str(tmp_path / "backups"))
    monkeypatch.setattr(core_config, "CIPHER_KEY_FILE", str(user_root / ".cipher_key"))
    monkeypatch.setattr(user_data, "USER_DATA_DIR", user_root)
    monkeypatch.setattr(user_data, "KNOWLEDGE_BASE_DIR", user_root / "KnowledgeBase")
    monkeypatch.setattr(user_data, "HIGHLIGHTS_DIR", user_root / "highlights")
    monkeypatch.setattr(user_data, "HTML_EXPORTS_DIR", user_root / "html_exports")
    monkeypatch.setattr(user_data, "MINDMAPS_DIR", user_root / "MindMaps")
    monkeypatch.setattr(user_data, "WORD_DIR", user_root / "Word")
    knowledge_base_dir = user_root / "KnowledgeBase"
    word_dir = user_root / "Word"
    mindmaps_dir = user_root / "MindMaps"
    knowledge_base_dir.mkdir()
    word_dir.mkdir()
    mindmaps_dir.mkdir()
    (knowledge_base_dir / "notes.md").write_text("private knowledge", encoding="utf-8")
    (word_dir / "report.docx").write_text("private document", encoding="utf-8")
    (mindmaps_dir / "topic.html").write_text("private mind map", encoding="utf-8")
    monkeypatch.setattr(user_data, "QR_CODES_DIR", user_root / "qr_codes")
    monkeypatch.setattr(builtins, "input", lambda _prompt: "RESET")

    app.quick_factory_reset_all()

    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert config["web"]["username"] == ""
    assert config["web"]["password"] == ""
    assert not knowledge_base_dir.exists()
    assert not word_dir.exists()
    assert not mindmaps_dir.exists()
    # Regression: the CLI has two historical reset definitions. The active one
    # must never retain the repository's real BASE_DIR during this test.
    assert str(project_root) != str(Path(__file__).resolve().parents[1])


def test_default_reset_preserves_backups_but_explicit_backup_group_removes_them(tmp_path):
    from core.factory_reset import erase_all_user_data

    project = tmp_path / "project"
    user = tmp_path / "BiliLearn"
    data = user / "Data"
    backup = tmp_path / "backup"
    external_kb = tmp_path / "external-kb"
    external_docs = tmp_path / "external-docs"
    recovery = user / "账号恢复" / "网页端账号恢复.txt"
    for file_path in (
        data / "bilibili_cookies.json",
        project / "MindMaps" / "private.html",
        user / "KnowledgeBase" / "legacy.md",
        recovery,
        external_kb / "note.md",
        external_docs / "report.docx",
        backup / "config.json",
    ):
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text("private", encoding="utf-8")

    result = erase_all_user_data(
        data_dir=data,
        user_data_dir=user,
        project_dir=project,
        backup_dir=backup,
        cipher_key_file=user / ".cipher_key",
        config={
            "knowledge_base_dir": str(external_kb),
            "document_export": {"output_dir": str(external_docs)},
        },
    )

    assert not result["failures"]
    assert data.exists() and not any(data.iterdir())
    assert not recovery.exists()
    assert not (project / "MindMaps").exists()
    assert not (user / "KnowledgeBase").exists()
    assert not external_kb.exists()
    assert not external_docs.exists()
    assert backup.exists()

    result = erase_all_user_data(
        data_dir=data,
        user_data_dir=user,
        project_dir=project,
        backup_dir=backup,
        cipher_key_file=user / ".cipher_key",
        config={},
        selected_groups=["backup_files"],
    )

    assert not result["failures"]
    assert not backup.exists()


def test_reset_preview_keeps_backup_unselected_by_default(tmp_path):
    from core.factory_reset import preview_reset_targets

    preview = preview_reset_targets(
        data_dir=tmp_path / "Data",
        user_data_dir=tmp_path / "user",
        project_dir=tmp_path / "project",
        backup_dir=tmp_path / "backups",
        cipher_key_file=tmp_path / "user" / ".cipher_key",
        config={},
    )

    backup = next(group for group in preview["groups"] if group["id"] == "backup_files")
    assert backup["selected"] is False
