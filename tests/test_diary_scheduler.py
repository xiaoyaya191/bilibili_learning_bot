import asyncio
import json
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor

import pytest
from services.diary_scheduler import DiaryScheduler, settings, validate_settings, in_schedule
from services import diary_store


def test_defaults_and_validation():
    value = settings({})
    assert value['enabled'] and value['auto_enabled']
    assert value['auto_interval_minutes'] == 1440
    assert len(value['sources']) == 5
    for invalid in ({'sources': []}, {'unknown': True}, {'temperature': float('nan')}, {'auto_interval_minutes': 1}, {'enabled': 'yes'}, {'time_windows': ['24:00-25:00']}):
        with pytest.raises(ValueError):
            validate_settings(invalid)


def test_schedule_and_persistence(tmp_path):
    scheduler = DiaryScheduler(tmp_path)
    preferences = settings({})
    started = datetime.fromisoformat(scheduler.state()['started'])
    assert not scheduler.due(preferences, started + timedelta(hours=23))
    assert DiaryScheduler(tmp_path).due(preferences, started + timedelta(hours=25))
    preferences.update(weekdays=[0], time_windows=['22:00-02:00'])
    assert in_schedule(preferences, datetime(2026, 10, 5, 23))
    assert not in_schedule(preferences, datetime(2026, 10, 6, 23))
    assert not in_schedule(preferences, datetime(2026, 10, 5, 15))


def test_single_running_job_and_expired_recovery(tmp_path):
    scheduler = DiaryScheduler(tmp_path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(lambda unused: scheduler.begin(), range(4)))
    assert sum(value is not None for value in ids) == 1
    with scheduler.connection() as database:
        database.execute("UPDATE jobs SET deadline='2000-01-01T00:00:00'")
    assert scheduler.begin() is not None


def test_sources_limits_and_redaction(tmp_path):
    now = datetime.now()
    (tmp_path / 'history_videos.json').write_text(json.dumps({'videos': [
        {'action': 'view', 'title': 'Python知识', 'time': now.isoformat(), 'result': '已学习'},
        {'action': 'view', 'title': '跳过片', 'time': now.isoformat(), 'result': '跳过'},
        {'action': 'view', 'title': '旧视频', 'time': (now-timedelta(days=3)).isoformat(), 'result': '已学习'}]}), encoding='utf8')
    (tmp_path / 'private_message_log.json').write_text(json.dumps({'history': [
        {'timestamp': now.isoformat(), 'incoming': '邮箱 test@example.com 电话13812345678 api_key=secret', 'reply': '回复', 'sent': True},
        {'timestamp': now.isoformat(), 'incoming': '拦截内容', 'blocked': True}]}), encoding='utf8')
    preferences = settings({'diary': {'sources': ['videos', 'private_messages']}})
    collected = DiaryScheduler(tmp_path).collect(preferences, now)
    assert collected['counts'] == {'videos': 1, 'private_messages': 1}
    text = str(collected['events'])
    assert 'test@example.com' not in text and '13812345678' not in text and 'secret' not in text
    assert '拦截内容' not in text and '旧视频' not in text
    assert '已发送私信' in text


def test_ai_success_and_restart_interval(tmp_path, monkeypatch):
    import services._services_ai as ai
    calls = []
    async def fake(messages, **kwargs):
        calls.append(messages)
        return '我今天学到了Python。'
    monkeypatch.setattr(ai, 'call_ai', fake)
    scheduler = DiaryScheduler(tmp_path)
    preferences = settings({'diary': {'empty_behavior': 'write'}})
    result = asyncio.run(scheduler.generate(preferences, manual=True))
    assert result['ok'] and result['entry']['source'] == 'ai'
    assert len(diary_store.read(scheduler.diary_path)['entries']) == 1
    assert not DiaryScheduler(tmp_path).due(preferences)
    assert scheduler.snapshot(preferences)['jobs'][0]['status'] == 'success'
    assert len(calls) == 1


def test_empty_failure_retry_and_opt_in_fallback(tmp_path, monkeypatch):
    import services._services_ai as ai
    async def fake(*args, **kwargs):
        return ''
    monkeypatch.setattr(ai, 'call_ai', fake)
    scheduler = DiaryScheduler(tmp_path)
    preferences = settings({})
    assert asyncio.run(scheduler.generate(preferences, manual=True))['status'] == 'skipped'
    preferences['empty_behavior'] = 'write'
    assert asyncio.run(scheduler.generate(preferences, manual=True))['status'] == 'failed'
    assert scheduler.state()['retry_at']
    assert not diary_store.read(scheduler.diary_path)['entries']
    preferences['fallback_to_local'] = True
    assert asyncio.run(scheduler.generate(preferences, manual=True))['entry']['source'] == 'local'


def test_atomic_store_legacy_and_corruption(tmp_path):
    path = tmp_path / 'bot_diary.json'
    path.write_text('{"diaries":[{"content":"旧内容"}]}', encoding='utf8')
    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda number: diary_store.add(path, str(number), '记录'), range(20)))
    assert len(diary_store.read(path)['entries']) == 21
    diary_store.update(path, 'legacy-0-', '旧标题', '修订')
    assert diary_store.read(path)['entries'][0]['content'] == '修订'
    path.write_text('invalid', encoding='utf8')
    with pytest.raises(ValueError):
        diary_store.add(path, '不可覆盖', '内容')
    assert path.read_text(encoding='utf8') == 'invalid'


def test_settings_web_api_and_confirmation(tmp_path, monkeypatch):
    import web_panel
    import core.config as config
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(config, 'CIPHER_KEY_FILE', str(tmp_path / '.cipher_key'))
    monkeypatch.setattr(web_panel.app, 'testing', True)
    with web_panel.app.test_client() as client:
        shown = client.get('/api/diary/settings').get_json()
        assert shown['settings']['auto_interval_minutes'] == 1440
        preferences = shown['settings']
        preferences['sources'] = ['videos']
        preferences['auto_enabled'] = False
        assert client.post('/api/diary/settings', json=preferences).get_json()['ok']
        assert client.get('/api/diary/settings').get_json()['settings']['auto_enabled'] is False
        assert client.post('/api/diary/settings', json={'unexpected': True}).status_code == 400
        assert client.post('/api/diary/generate', json={}).status_code == 400


def test_diary_settings_require_auth(tmp_path, monkeypatch):
    import web_panel
    monkeypatch.setattr(web_panel.app, 'testing', False)
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    with web_panel.app.test_client() as client:
        assert client.get('/api/diary/settings').status_code in (401, 403)
        assert client.post('/api/diary/generate', json={'confirmed': True}).status_code in (401, 403)


def test_daily_events_switches_and_empty_threshold(tmp_path):
    scheduler = DiaryScheduler(tmp_path)
    preferences = settings({'diary': {'trigger_mode': 'daily', 'daily_time': '22:00'}})
    assert not scheduler.due(preferences, datetime(2026, 10, 6, 21))
    assert scheduler.due(preferences, datetime(2026, 10, 6, 23))
    preferences['enabled'] = False
    assert not scheduler.due(preferences, datetime(2026, 10, 6, 23))
    preferences.update(enabled=True, trigger_mode='events', empty_behavior='write')
    assert asyncio.run(scheduler.generate(preferences))['status'] == 'skipped'


def test_chat_knowledge_comments_and_budgets(tmp_path):
    now = datetime.now().isoformat()
    (tmp_path / 'HomeChat').mkdir()
    (tmp_path / 'HomeChat' / 'session.json').write_text(json.dumps({'messages': [{'role': 'user', 'content': '如何使用async？', 'ts': now}, {'role': 'assistant', 'content': '可以使用await。', 'ts': now}]}), encoding='utf8')
    (tmp_path / 'comment_log.json').write_text(json.dumps({'history': [{'timestamp': now, 'action': 'reply', 'incoming': '评论原文', 'content': '真实回复'}, {'timestamp': now, 'action': 'reply_draft', 'content': '未发送草稿'}]}), encoding='utf8')
    knowledge = tmp_path / 'kb'
    knowledge.mkdir()
    (knowledge / 'new.md').write_text('学习到的知识' * 500, encoding='utf8')
    preferences = settings({'diary': {'sources': ['learning', 'web_chat', 'comments'], 'max_chars_per_source': 200, 'max_total_chars': 1000}})
    result = DiaryScheduler(tmp_path, knowledge).collect(preferences)
    assert set(result['counts']) == {'learning', 'web_chat', 'comments'}
    assert all(result['counts'][source] > 0 for source in result['counts'])
    assert result['chars'] <= 1000
    assert sum(len(event['text']) for event in result['events'] if event['source'] == 'learning') <= 200
    assert '未发送草稿' not in str(result['events'])
    preferences['include_blocked'] = True
    result = DiaryScheduler(tmp_path, knowledge).collect(preferences)
    assert '未发送草稿' in str(result['events'])


def test_event_mode_only_new_sources_and_id_survives_reset(tmp_path, monkeypatch):
    import services._services_ai as ai
    async def fake(*args, **kwargs):
        return '本次学习记录'
    monkeypatch.setattr(ai, 'call_ai', fake)
    scheduler = DiaryScheduler(tmp_path)
    preferences = settings({'diary': {'trigger_mode': 'events', 'event_threshold': 1}})
    (tmp_path / 'history_videos.json').write_text(json.dumps({'videos': [{'action': 'view', 'time': datetime.now().isoformat(), 'title': '首次事件'}]}), encoding='utf8')
    first = asyncio.run(scheduler.generate(preferences))
    assert first['ok']
    assert not scheduler.collect(preferences)['events']
    assert asyncio.run(scheduler.generate(preferences))['status'] == 'skipped'
    scheduler.path.unlink()
    scheduler = DiaryScheduler(tmp_path)
    second = asyncio.run(scheduler.generate(preferences, manual=True))
    assert second['ok']
    assert first['entry']['id'] != second['entry']['id']
    assert len(diary_store.read(scheduler.diary_path)['entries']) == 2


def test_failed_source_does_not_write_empty_diary(tmp_path, monkeypatch):
    scheduler = DiaryScheduler(tmp_path)
    (tmp_path / 'history_videos.json').write_text('broken', encoding='utf8')
    preferences = settings({'diary': {'sources': ['videos'], 'empty_behavior': 'write'}})
    result = asyncio.run(scheduler.generate(preferences, manual=True))
    assert result['status'] == 'skipped'
    assert not diary_store.read(scheduler.diary_path)['entries']


def test_cancelled_job_is_not_success(tmp_path, monkeypatch):
    import services._services_ai as ai
    async def fake(*args, **kwargs):
        raise asyncio.CancelledError()
    monkeypatch.setattr(ai, 'call_ai', fake)
    scheduler = DiaryScheduler(tmp_path)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(scheduler.generate(settings({'diary': {'empty_behavior': 'write'}}), manual=True))
    assert scheduler.snapshot(settings({}))['jobs'][0]['status'] == 'failed'
    assert not scheduler.state()['last_success']


def test_web_generate_atomic_reservation_and_disabled_manual(tmp_path, monkeypatch):
    import web_panel
    import core.config as config
    import services._services_ai as ai
    import threading
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(config, 'CIPHER_KEY_FILE', str(tmp_path / '.cipher_key'))
    monkeypatch.setattr(web_panel.app, 'testing', True)
    finished = threading.Event()
    started = threading.Event()
    async def fake(*args, **kwargs):
        started.set()
        await asyncio.to_thread(finished.wait, 5)
        return '手动生成的记录'
    monkeypatch.setattr(ai, 'call_ai', fake)
    config.save_config({'diary': {'enabled': False, 'auto_enabled': False, 'empty_behavior': 'write'}})
    try:
        with web_panel.app.test_client() as client:
            response = client.post('/api/diary/generate', json={'confirmed': True})
            assert response.status_code == 202
            assert response.get_json()['job_id']
            assert started.wait(3)
            assert client.post('/api/diary/generate', json={'confirmed': True}).status_code == 409
            assert client.get('/api/diary/settings').get_json()['settings']['auto_enabled'] is False
    finally:
        finished.set()
    import time
    deadline = time.monotonic() + 5
    scheduler = DiaryScheduler(tmp_path)
    while scheduler.snapshot(settings({}))['jobs'][0]['status'] == 'running' and time.monotonic() < deadline:
        time.sleep(.02)
    assert scheduler.snapshot(settings({}))['jobs'][0]['status'] == 'success'


def test_config_defaults_match_scheduler_and_ui_is_visible():
    from core.config import DEFAULT_CONFIG, normalize_config
    from services.diary_scheduler import DEFAULTS
    from pathlib import Path
    assert DEFAULT_CONFIG['diary'] == DEFAULTS
    assert normalize_config({'diary': {'enabled': True, 'auto_enabled': True}})['diary']['enabled']
    template = (Path(__file__).resolve().parents[1] / 'web_panel.html').read_text(encoding='utf8')
    assert 'id="pg-diary" hidden' not in template
    assert 'data-pg="diary"' in template
    assert '/assets/js/diary.js' in template


def test_diary_css_asset_and_existing_memory_api(tmp_path, monkeypatch):
    import web_panel
    monkeypatch.setattr(web_panel.app, 'testing', True)
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    with web_panel.app.test_client() as client:
        asset = client.get('/assets/css/diary.css')
        assert asset.status_code == 200
        assert asset.mimetype == 'text/css'
        assert b'#pg-diary' in asset.data
        assert client.get('/assets/css/missing.css').status_code == 404
        assert client.get('/api/memory').status_code == 200
