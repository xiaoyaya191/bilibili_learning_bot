import json
import sqlite3
import pytest
import web_panel
from services.direct_video import DEFAULTS
from utils.database import DocumentDatabase


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(web_panel, 'CONFIG_FILE', tmp_path / 'config.json')
    monkeypatch.setattr(web_panel.app, 'testing', True)
    (tmp_path / 'config.json').write_text('{"api":{"unified_api_key":"secret"}}', encoding='utf-8')
    return web_panel.app.test_client(), tmp_path


def test_default_off_settings_validation_confirmation_and_preserved_config(api):
    client, path = api
    assert not client.get('/api/direct-video/settings').get_json()['settings']['enabled']
    selected = {**DEFAULTS, 'enabled': True, 'capability_confirmed': True, 'model': 'video-model'}
    assert client.post('/api/direct-video/settings', json={'settings': selected}).status_code == 400
    response = client.post('/api/direct-video/settings', json={'settings': selected, 'confirmed': True})
    assert response.get_json()['ok']
    assert DocumentDatabase(path).read('config.json')['api']['unified_api_key'] == 'secret'
    assert client.get('/api/direct-video/settings').get_json()['settings']['enabled']


@pytest.mark.parametrize('body', [[], {}, {'settings': None}, {'settings': {'enabled': True}}, {'settings': {'model': 1}}])
def test_invalid_settings_body(api, body):
    client, path = api
    assert client.post('/api/direct-video/settings', json=body).status_code == 400


def test_migration_confirmation_health_and_snapshot(api, tmp_path):
    client, directory = api
    (directory / 'personas.json').write_text('{"prompt":"original"}', encoding='utf-8')
    assert client.post('/api/storage/database/migrate', json={}).status_code == 400
    response = client.post('/api/storage/database/migrate', json={'confirmed': True})
    result = response.get_json()
    assert result['ok'] and result['healthy'] and len(result['records']) == 2
    assert 'secret' not in json.dumps(client.get('/api/storage/database').get_json())
    assert client.post('/api/storage/database/download', json={}).status_code == 400
    backup = client.post('/api/storage/database/download', json={'confirmed': True})
    assert backup.status_code == 200 and backup.data.startswith(b'SQLite format 3')
    snapshot = tmp_path / 'backup.sqlite3'
    snapshot.write_bytes(backup.data)
    with sqlite3.connect(snapshot) as connection:
        assert connection.execute('PRAGMA quick_check').fetchone()[0] == 'ok'


def test_corrupt_migration_is_atomic(api):
    client, path = api
    (path / 'z.json').write_bytes(b'broken')
    response = client.post('/api/storage/database/migrate', json={'confirmed': True})
    assert response.status_code == 400, response.get_json()
    assert not client.get('/api/storage/database').get_json()['records']
    assert (path / 'z.json').read_bytes() == b'broken'


@pytest.mark.parametrize('route,method', [('/api/direct-video/settings', 'get'), ('/api/direct-video/settings', 'post'),
                                          ('/api/storage/database', 'get'), ('/api/storage/database/migrate', 'post'),
                                          ('/api/storage/database/download', 'post')])
def test_authentication_required(api, monkeypatch, route, method):
    client, path = api
    monkeypatch.setattr(web_panel.app, 'testing', False)
    response = getattr(client, method)(route)
    assert response.status_code == 401 and response.get_json()['auth_required']
