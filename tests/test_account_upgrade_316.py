"""Regression coverage for username-only upgrades; never touch real accounts."""
import copy
import pytest


@pytest.mark.parametrize("web", [{}, {"username": "old-user"}, {"username": "old-user", "password": "existing-hash"}])
def test_startup_never_seeds_or_overwrites_account(monkeypatch, web):
    import web_panel
    config = {"web": copy.deepcopy(web)}
    monkeypatch.setattr(web_panel, "read_json", lambda *args: config)
    monkeypatch.setattr(web_panel, "write_json", lambda *args: pytest.fail("startup must not write credentials"))
    assert web_panel._ensure_default_panel_account() is False
    assert config == {"web": web}


@pytest.mark.parametrize("username", ["legacy-user", "x", '<old&user>'])
def test_legacy_setup_preserves_identity_and_sets_password(monkeypatch, username):
    import web_panel
    config = {"web": {"username": username}, "ai_permissions": {"enabled": False}}
    monkeypatch.setattr(web_panel, "read_json", lambda *args: copy.deepcopy(config))
    def save(path, value):
        config.clear()
        config.update(copy.deepcopy(value))
        return True
    monkeypatch.setattr(web_panel, "write_json", save)
    monkeypatch.setattr(web_panel, "_write_recovery_file", lambda user, code: user == username)
    monkeypatch.setattr(web_panel, "log_line", lambda *args: None)
    from html import escape
    assert 'readonly value="' + escape(username, quote=True) + '"' in web_panel._setup_html()
    with web_panel.app.test_request_context('/api/auth/setup', method='POST', json={"username": "replacement", "password": "new-secret"}):
        assert web_panel.api_auth_setup()[1] == 400
    assert config['web'] == {"username": username}
    with web_panel.app.test_request_context('/api/auth/setup', method='POST', json={"username": username, "password": "new-secret"}):
        assert web_panel.api_auth_setup().json['ok']
    assert config['web']['username'] == username
    assert web_panel._verify_password('new-secret', config['web']['password'])
    assert not web_panel._verify_password('yaya', config['web']['password'])
    assert config['ai_permissions'] == {"enabled": False}


def test_permission_save_survives_collection_save_and_reload(tmp_path, monkeypatch):
    import web_panel
    import core.config as core_config
    from utils.storage import JsonStore
    from services.permission_routes import collection_settings
    from services.action_permissions import allowed
    path = tmp_path / "config.json"
    monkeypatch.setattr(core_config, "CONFIG_FILE", str(path))
    monkeypatch.setattr(web_panel, "CONFIG_FILE", path)
    monkeypatch.setitem(web_panel.app.config, 'LEARNING_READ_CONFIG', lambda: JsonStore(path).read({}))
    monkeypatch.setitem(web_panel.app.config, 'LEARNING_WRITE_CONFIG', lambda value: JsonStore(path).write(value))
    assert JsonStore(path).write({"web": {"username": "legacy-user"}})
    with web_panel.app.test_request_context('/api/ai-permissions', method='POST', json={"enabled": True, "actions": {"follow_up": True}}):
        assert web_panel.api_ai_permissions().json['ok']
    with web_panel.app.test_request_context('/api/collection-settings', method='POST', json={"destination": "local", "folder_name": "test"}):
        assert collection_settings().json['ok']
    with web_panel.app.test_request_context('/api/ai-permissions'):
        saved = web_panel.api_ai_permissions().json
        assert saved['enabled'] is True
        assert saved['actions']['follow_up'] is True
    assert allowed('follow_up') is True
    assert allowed('unfollow_user') is False
    assert core_config.load_config()['web']['username'] == 'legacy-user'


def test_explicit_credentials_change_refreshes_recovery_identity(monkeypatch):
    import web_panel
    import core.config as core_config
    config = {"web": {"username": "yaya", "password": web_panel._hash_password('yaya'), "default_credentials": True}}
    monkeypatch.setattr(core_config, 'load_config', lambda: copy.deepcopy(config))
    monkeypatch.setattr(core_config, 'config', {})
    def save(value):
        config.clear()
        config.update(copy.deepcopy(value))
        return True
    monkeypatch.setattr(core_config, 'save_config', save)
    refreshed = []
    monkeypatch.setattr(web_panel, '_rotate_recovery_code', lambda cfg, username: refreshed.append(username) or True)
    with web_panel.app.test_request_context('/api/account/update-credentials', method='POST', json={"old_password": "yaya", "new_username": "restored-user", "new_password": "private-new-password"}):
        assert web_panel.api_account_update_credentials().json['ok']
    assert refreshed == ['restored-user']
    assert config['web']['username'] == 'restored-user'
    assert 'default_credentials' not in config['web']
