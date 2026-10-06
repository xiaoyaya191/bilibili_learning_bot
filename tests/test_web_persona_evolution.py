import json
import pytest
import web_panel
from services import persona_evolution_routes as routes
from services.persona_evolution import PersonaEvolution


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(web_panel, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(web_panel.app, 'testing', True)
    clock = [1000.0]
    store = PersonaEvolution(tmp_path, clock=lambda: clock[0])
    monkeypatch.setattr(routes, 'store', lambda: store)
    items = {'原始': {'name': '原始', 'system_prompt': '  原始\n ', 'owner_prompt': '主人', 'rules': ['不编造'], 'style': '自然'}}
    web_panel.write_json(tmp_path / 'web_personas.json', {'active': '原始', 'items': items})
    web_panel._sync_runtime_personas({'active': '原始', 'items': items})
    client = web_panel.app.test_client()
    return client, store, clock, items


def enable(client, clock):
    token = client.post('/api/persona-evolution/challenge').get_json()['token']
    clock[0] += 10
    assert client.post('/api/persona-evolution/confirm', json={'token': token}).get_json()['ok']
    return token


def test_api_default_countdown_confirm_and_cancel(api):
    client, store, clock, items = api
    assert client.get('/api/persona-evolution').get_json()['enabled'] is False
    token = client.post('/api/persona-evolution/challenge').get_json()['token']
    assert client.post('/api/persona-evolution/confirm', json={'token': token}).status_code == 400
    client.post('/api/persona-evolution/cancel', json={'token': token})
    clock[0] += 10
    assert client.post('/api/persona-evolution/confirm', json={'token': token}).status_code == 400
    enable(client, clock)
    status = client.get('/api/persona-evolution').get_json()
    backup = client.get('/api/persona-evolution/backups/' + str(status['backups'][0]['id'])).get_json()['backup']
    assert backup['original'] == items['原始']
    assert client.post('/api/persona-evolution/disable').get_json()['ok']
    assert not client.get('/api/persona-evolution').get_json()['enabled']


def test_token_bound_to_session(api):
    client, store, clock, items = api
    token = client.post('/api/persona-evolution/challenge').get_json()['token']
    clock[0] += 10
    other = web_panel.app.test_client()
    assert other.post('/api/persona-evolution/confirm', json={'token': token}).status_code == 400
    assert client.post('/api/persona-evolution/confirm', json={'token': token}).get_json()['ok']


def test_full_manual_flow_does_not_write_personas(api, tmp_path, monkeypatch):
    client, store, clock, items = api
    from services import _services_ai
    async def fake_ai(messages, **kwargs):
        return json.dumps({'styles': {'tone': 'warm', 'detail': 'brief', 'structure': 'organized'}, 'rationale': '更清晰'})
    monkeypatch.setattr(_services_ai, 'call_ai', fake_ai)
    originals = [(path, path.read_bytes()) for path in (tmp_path / 'personas.json', tmp_path / 'web_personas.json')]
    enable(client, clock)
    assert client.post('/api/persona-evolution/generate', json={'key': '原始', 'goal': '简洁'}).status_code == 400
    result = client.post('/api/persona-evolution/generate', json={'key': '原始', 'goal': '简洁', 'confirmed': True}).get_json()
    assert result['ok']
    assert client.post('/api/persona-evolution/apply', json={'id': result['id']}).status_code == 400
    assert client.post('/api/persona-evolution/apply', json={'id': result['id'], 'confirmed': True}).get_json()['ok']
    assert store.prompt_block('原始', items['原始'])
    assert client.post('/api/persona-evolution/restore', json={'key': '原始', 'confirmed': True}).get_json()['ok']
    assert not store.prompt_block('原始', items['原始'])
    for path, contents in originals:
        assert path.read_bytes() == contents


@pytest.mark.parametrize('endpoint', ['confirm', 'cancel', 'generate', 'apply', 'restore'])
def test_invalid_json(api, endpoint):
    client, store, clock, items = api
    assert client.post('/api/persona-evolution/' + endpoint, json=[]).status_code == 400


@pytest.mark.parametrize('endpoint', ['', '/backups/1', '/challenge', '/confirm', '/disable', '/generate', '/apply', '/restore', '/cancel'])
def test_auth_required(api, monkeypatch, endpoint):
    client, store, clock, items = api
    monkeypatch.setattr(web_panel.app, 'testing', False)
    response = client.get('/api/persona-evolution' + endpoint) if endpoint in ('', '/backups/1') else client.post('/api/persona-evolution' + endpoint, json={})
    assert response.status_code == 401
    assert response.get_json()['auth_required']


def test_api_backup_failure_does_not_enable(api, monkeypatch):
    client, store, clock, items = api
    token = client.post('/api/persona-evolution/challenge').get_json()['token']
    clock[0] += 10
    def fail(*args):
        raise OSError('disk full')
    monkeypatch.setattr(store, '_backup', fail)
    assert client.post('/api/persona-evolution/confirm', json={'token': token}).status_code == 500
    assert not store.status(items)['enabled']
