from copy import deepcopy

import pytest

from services.video_watch_queue import DEFAULTS, VideoWatchQueue


@pytest.fixture
def queue_api(tmp_path, monkeypatch):
    import core.config as core_config
    import web_panel
    state = {'watch_queue': dict(DEFAULTS)}
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(web_panel.app, 'testing', True)
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])
    monkeypatch.setattr(core_config, 'load_config', lambda: deepcopy(state))
    monkeypatch.setattr(core_config, 'config', deepcopy(state))
    def save(value):
        state.clear()
        state.update(deepcopy(value))
        return True
    monkeypatch.setattr(core_config, 'save_config', save)
    return web_panel.app.test_client(), VideoWatchQueue(tmp_path / 'video_watch_queue.sqlite3'), state


def test_queue_api_works_without_bilibili_login_and_keeps_platform_route(queue_api):
    client, queue, state = queue_api
    assert client.post('/api/watch-queue', json={'bvid': 'BV1AA00000001'}).get_json()['ok']
    assert client.get('/api/watch-queue').get_json()['items'][0]['bvid'] == 'BV1AA00000001'
    assert client.post('/api/watch-queue', json={'bvid': 'BV1AA00000001'}).status_code == 409
    import web_panel
    rules = [rule.endpoint for rule in web_panel.app.url_map.iter_rules() if rule.rule == '/api/watch-later']
    assert rules == ['api_watch_later']


def test_remove_is_confirmed_and_cannot_remove_watching(queue_api):
    client, queue, state = queue_api
    client.post('/api/watch-queue', json={'bvid': 'BV1AA00000001'})
    assert client.delete('/api/watch-queue', json={'bvid': 'BV1AA00000001'}).status_code == 400
    queue.claim(DEFAULTS)
    assert client.delete('/api/watch-queue', json={'bvid': 'BV1AA00000001', 'confirmed': True}).status_code == 400
    queue.fail('BV1AA00000001', '停止', interrupted=True, preferences=DEFAULTS)
    assert client.delete('/api/watch-queue', json={'bvid': 'BV1AA00000001', 'confirmed': True}).get_json()['ok']
    assert not queue.snapshot()['items']


def test_settings_validate_types_limits_and_persist(queue_api):
    client, queue, state = queue_api
    for invalid in ({'max_selected': 101}, {'sync_platform': 'true'}, {'unsupported': 1}):
        assert client.post('/api/watch-queue/settings', json=invalid).status_code == 400
    result = client.post('/api/watch-queue/settings', json={'max_selected': 30, 'remove_completed': False, 'sync_platform': True})
    assert result.get_json()['ok']
    assert state['watch_queue']['max_selected'] == 30
    assert not state['watch_queue']['remove_completed']
    assert client.get('/api/watch-queue/settings').get_json()['settings']['sync_platform']


def test_history_restore_clear_and_independent_dedup(queue_api):
    client, queue, state = queue_api
    client.post('/api/watch-queue', json={'bvid': 'BV1AA00000001'})
    queue.claim(DEFAULTS)
    queue.finish('BV1AA00000001', 'done', score=9, actions=['点赞'], preferences=DEFAULTS)
    result = client.get('/api/watch-queue').get_json()
    assert result['history'][0]['actions'] == ['点赞']
    assert client.post('/api/watch-queue', json={'bvid': 'BV1AA00000001', 'action': 'restore'}).get_json()['ok']
    assert len(queue.snapshot()['items']) == 1
    assert client.delete('/api/watch-queue/history', json={}).status_code == 400
    assert client.delete('/api/watch-queue/history', json={'confirmed': True}).get_json()['ok']
    assert queue.snapshot()['history_total'] == 0
    assert client.delete('/api/watch-queue/history', json={'confirmed': True, 'reset_seen': True}).get_json()['ok']


def test_invalid_inputs_are_rejected_without_mutating_queue(queue_api):
    client, queue, state = queue_api
    assert client.post('/api/watch-queue', json={'bvid': '../../secret'}).status_code == 400
    assert client.post('/api/watch-queue', json=['invalid']).status_code == 400
    assert client.get('/api/watch-queue?history_page=invalid').status_code == 400
    assert queue.snapshot()['items'] == []


def test_queue_routes_require_real_panel_authentication(tmp_path, monkeypatch):
    import web_panel
    monkeypatch.setattr(web_panel.app, 'testing', False)
    client = web_panel.app.test_client()
    for path in ('/api/watch-queue', '/api/watch-queue/settings'):
        result = client.get(path)
        assert result.status_code == 401
        assert result.get_json()['auth_required']


def test_template_exposes_local_queue_settings_history_and_separate_platform():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] / 'web_panel.html').read_text(encoding='utf-8')
    for marker in ('id="videoQueueList"', 'id="videoQueueHistory"', 'id="videoQueueSettingsFields"', 'video-watch-queue.js', 'B站账号的稍后再看列表（独立同步）'):
        assert marker in source
