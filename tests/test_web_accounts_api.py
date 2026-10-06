import pytest

from core.account_web import account_web
from core.account_workspaces import AccountWorkspaces
from core.account_processes import AccountProcesses


@pytest.fixture
def panel(tmp_path, monkeypatch):
    import web_panel
    monkeypatch.setattr('core.account_workspaces.port_available', lambda port: True)
    monkeypatch.setattr('core.account_processes.port_available', lambda port: True)
    registry = AccountWorkspaces(tmp_path)
    registry.create('主账号')
    manager = AccountProcesses(registry)
    monkeypatch.setattr(account_web, 'manager', manager)
    monkeypatch.setenv('BILI_ACCOUNT_ID', 'account-001')
    monkeypatch.setitem(web_panel.app.config, 'TESTING', True)
    yield web_panel.app.test_client(), registry, manager
    manager.processes.clear()


def test_create_list_delete_and_secret_free_response(panel):
    client, registry, manager = panel
    result = client.post('/api/accounts', json={'name': '学习账号'}).get_json()
    assert result['ok']
    assert result['account']['port'] == 18084
    listed = client.get('/api/accounts').get_json()
    assert listed['max_accounts'] == 10
    assert len(listed['accounts']) == 2
    assert 'SESSDATA' not in str(listed)
    assert client.delete('/api/accounts/account-002', json={}).status_code == 400
    deleted = client.delete('/api/accounts/account-002', json={'confirmation': 'account-002'}).get_json()
    assert deleted['ok'] and deleted['backup'].endswith('.zip')


def test_subaccount_cannot_manage_other_accounts(panel, monkeypatch):
    client, _, _ = panel
    monkeypatch.setenv('BILI_ACCOUNT_ID', 'account-002')
    assert client.get('/api/accounts').status_code == 403
    assert client.post('/api/accounts', json={'name': '拒绝'}).status_code == 403


def test_api_requires_panel_auth(panel, monkeypatch):
    import web_panel
    client, _, _ = panel
    monkeypatch.setitem(web_panel.app.config, 'TESTING', False)
    response = client.get('/api/accounts')
    assert response.status_code == 401
    assert response.get_json()['auth_required']


def test_limit_and_duplicate_port(panel):
    client, _, _ = panel
    assert client.post('/api/accounts', json={'name': '冲突', 'port': 18083}).status_code == 400
    for number in range(9):
        assert client.post('/api/accounts', json={'name': str(number)}).get_json()['ok']
    assert client.post('/api/accounts', json={'name': '第11个'}).status_code == 400


def test_running_account_cannot_delete_or_change_port(panel, monkeypatch):
    client, registry, manager = panel
    registry.create('副账号')
    monkeypatch.setattr(manager, 'status', lambda account_id: {'running': True, 'status': 'running'})
    assert client.delete('/api/accounts/account-002', json={'confirmation': 'account-002'}).status_code == 400
    assert client.patch('/api/accounts/account-002', json={'port': 19001}).status_code == 400


def test_open_returns_correct_account_port(panel, monkeypatch):
    client, registry, manager = panel
    account = registry.create('副账号', 20000)
    monkeypatch.setattr(manager, 'start', lambda account_id: dict(account, running=True))
    assert client.post('/api/accounts/account-002/open', json={}).get_json()['port'] == 20000


def test_panel_management_page_and_storage_guards(panel):
    client, _, _ = panel
    assert '最多 10 个'.encode() in client.get('/accounts').data
    assert client.post('/api/storage', json={'path': 'elsewhere'}).status_code == 400
    assert client.post('/api/kb/path', json={'path': 'elsewhere'}).status_code == 400


def test_primary_context_and_embedded_management_page(panel):
    client, registry, _ = panel
    context = client.get('/api/accounts/context').get_json()
    assert context == {'ok': True, 'current_account_id': 'account-001', 'is_primary': True,
                       'primary_port': registry.get('account-001')['port']}
    embedded = client.get('/accounts?embedded=1').get_data(as_text=True)
    assert 'class="embedded"' in embedded
    assert '← 返回当前面板' not in embedded
    assert 'id="create"' in embedded


def test_subaccount_context_only_exposes_primary_port(panel, monkeypatch):
    client, _, _ = panel
    monkeypatch.setenv('BILI_ACCOUNT_ID', 'account-002')
    context = client.get('/api/accounts/context').get_json()
    assert context['ok'] and context['is_primary'] is False
    assert context['primary_port'] == 18083
    assert 'workspace' not in context
    assert client.get('/api/accounts').status_code == 403


def test_context_requires_auth(panel, monkeypatch):
    import web_panel
    client, _, _ = panel
    monkeypatch.setitem(web_panel.app.config, 'TESTING', False)
    response = client.get('/api/accounts/context')
    assert response.status_code == 401
    assert response.get_json()['auth_required']


def test_account_section_entry_in_both_panel_templates():
    import web_panel
    from pathlib import Path
    template = (Path(__file__).resolve().parents[1] / 'web_panel.html').read_text(encoding='utf-8')
    for html in (template, web_panel._DEFAULT_HTML):
        assert 'data-pg="accounts"' in html
        assert 'id="pg-accounts"' in html
        assert 'id="accountsFrame"' in html
        assert '/api/accounts/context' in html
        assert "async function rf_accounts(){" in html
        assert '多账号工作空间</h2>' not in html
        assert "function nav(p,el){\nasync function rf_accounts" not in html
    assert 'delete hidden.accounts' in template
    assert "nav(location.hash==='#accounts'?'accounts':'dash')" in template
