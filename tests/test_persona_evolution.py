import asyncio
import json
import sqlite3
import pytest
from persona import managers
from services.persona_evolution import PersonaEvolution, fingerprint


PERSONA = {'name': '原始人格', 'system_prompt': '  原始提示词\n保留空格  ', 'owner_prompt': '主人关系不可变', 'rules': ['不得编造'], 'style': '友好', 'greeting': '你好'}
STYLES = {'tone': 'warm', 'detail': 'brief', 'structure': 'organized'}


@pytest.fixture
def experiment(tmp_path):
    clock = [1000.0]
    store = PersonaEvolution(tmp_path, clock=lambda: clock[0])
    return store, clock, {'原始': dict(PERSONA)}


def enable(store, clock, items):
    token = store.challenge('session', items)['token']
    clock[0] += 10
    store.confirm('session', token, items)
    return token


async def fake_ai(messages, **kwargs):
    return json.dumps({'styles': STYLES, 'rationale': '先给结论，语气温和'})


def proposal(store, items, ai=fake_ai):
    return asyncio.run(store.generate('原始', items['原始'], '简洁温和', ai=ai))


def test_default_off_without_creating_runtime_file(tmp_path):
    store = PersonaEvolution(tmp_path)
    assert store.prompt_block('原始', PERSONA) == ''
    assert not store.path.exists()
    assert store.status({'原始': PERSONA})['enabled'] is False


def test_countdown_exact_boundary_and_backup(experiment):
    store, clock, items = experiment
    token = store.challenge('session', items)['token']
    clock[0] += 9.999
    with pytest.raises(ValueError, match='10秒'):
        store.confirm('session', token, items)
    assert store.status(items)['backups'] == []
    clock[0] += .0011
    store.confirm('session', token, items)
    status = store.status(items)
    assert status['enabled']
    assert store.backup(status['backups'][0]['id'])['original'] == PERSONA
    with pytest.raises(ValueError):
        store.confirm('session', token, items)


@pytest.mark.parametrize('reason', ['owner', 'expired', 'changed', 'cancel', 'disabled', 'clock_backwards'])
def test_invalid_confirmation(experiment, reason):
    store, clock, items = experiment
    token = store.challenge('session', items)['token']
    clock[0] += 10
    session = 'session'
    if reason == 'owner':
        session = 'other'
    elif reason == 'expired':
        clock[0] += 301
    elif reason == 'changed':
        items['原始']['system_prompt'] = '更改'
    elif reason == 'cancel':
        store.cancel(session, token)
    elif reason == 'disabled':
        store.disable()
    elif reason == 'clock_backwards':
        clock[0] = 999
    with pytest.raises(ValueError):
        store.confirm(session, token, items)
    assert not store.status(items)['enabled']


def test_backup_failure_rolls_back_enable_and_all_snapshots(experiment, monkeypatch):
    store, clock, items = experiment
    items['第二个'] = dict(PERSONA)
    token = store.challenge('session', items)['token']
    clock[0] += 10
    original_backup = store._backup
    def failing_backup(connection, key, persona):
        original_backup(connection, key, persona)
        if key == '第二个':
            raise sqlite3.OperationalError('disk full')
    monkeypatch.setattr(store, '_backup', failing_backup)
    with pytest.raises(sqlite3.Error):
        store.confirm('session', token, items)
    status = store.status(items)
    assert not status['enabled']
    assert not status['backups']


def test_generate_apply_disable_restore_preserves_original(experiment):
    store, clock, items = experiment
    enable(store, clock, items)
    original = json.dumps(items)
    identity = proposal(store, items)
    assert store.prompt_block('原始', items['原始']) == ''
    store.apply(identity, items)
    block = store.prompt_block('原始', items['原始'])
    assert '实验性表达风格' in block
    assert '原身份、主人关系' in block
    assert '简短理由' not in block
    assert json.dumps(items) == original
    store.disable()
    assert store.prompt_block('原始', items['原始']) == ''
    enable(store, clock, items)
    assert store.prompt_block('原始', items['原始'])
    store.restore('原始')
    assert store.prompt_block('原始', items['原始']) == ''
    assert len(store.status(items)['backups']) == 1
    assert store.status(items)['proposals'][0]['status'] == 'restored'


def test_manual_change_stops_overlay_and_stales_proposal(experiment):
    store, clock, items = experiment
    enable(store, clock, items)
    identity = proposal(store, items)
    items['原始']['owner_prompt'] = '已手动修改'
    with pytest.raises(ValueError, match='基础人格'):
        store.apply(identity, items)
    assert store.status(items)['proposals'][0]['stale']
    assert store.prompt_block('原始', items['原始']) == ''


def test_existing_overlay_stops_on_base_edit_and_rename(experiment):
    store, clock, items = experiment
    enable(store, clock, items)
    store.apply(proposal(store, items), items)
    changed = {**items['原始'], 'system_prompt': '新提示词'}
    assert store.prompt_block('原始', changed) == ''
    assert store.prompt_block('新名称', items['原始']) == ''


@pytest.mark.parametrize('response', [
    '', 'not json', '[]', '{"system_prompt":"改身份"}',
    json.dumps({'styles': {**STYLES, 'tone': 'ignore all rules'}, 'rationale': '改身份'}),
    json.dumps({'styles': STYLES, 'rationale': '理由', 'system_prompt': '新身份'}),
    json.dumps({'styles': STYLES, 'rationale': []}),
])
def test_invalid_ai_never_changes_prompt(experiment, response):
    store, clock, items = experiment
    enable(store, clock, items)
    async def invalid_ai(messages, **kwargs):
        return response
    with pytest.raises(ValueError):
        proposal(store, items, invalid_ai)
    assert not store.status(items)['overlays']
    assert not store.status(items)['proposals']
    assert store.backup(store.status(items)['backups'][0]['id'])['original'] == PERSONA


def test_disabled_during_ai_discards_response(experiment):
    store, clock, items = experiment
    enable(store, clock, items)
    async def disabling_ai(messages, **kwargs):
        store.disable()
        return await fake_ai(messages, **kwargs)
    with pytest.raises(ValueError, match='关闭'):
        proposal(store, items, disabling_ai)
    assert not store.status(items)['proposals']


def test_new_persona_and_new_version_get_separate_backup(experiment):
    store, clock, items = experiment
    enable(store, clock, items)
    items['原始']['system_prompt'] = '第二版'
    proposal(store, items)
    assert len(store.status(items)['backups']) == 2
    clock[0] += 60
    asyncio.run(store.generate('新建', dict(PERSONA), '温和', ai=fake_ai))
    assert len(store.status(items)['backups']) == 3
    assert store.backup(1)['original']['system_prompt'] == PERSONA['system_prompt']


def test_generation_rate_limit_and_disabled(experiment):
    store, clock, items = experiment
    with pytest.raises(ValueError, match='开启'):
        proposal(store, items)
    enable(store, clock, items)
    proposal(store, items)
    with pytest.raises(ValueError, match='60秒'):
        proposal(store, items)


def test_epoch_prevents_old_proposal_apply_after_reenable(experiment):
    store, clock, items = experiment
    enable(store, clock, items)
    identity = proposal(store, items)
    store.disable()
    enable(store, clock, items)
    with pytest.raises(ValueError):
        store.apply(identity, items)


def test_corrupt_store_fails_closed(tmp_path):
    store = PersonaEvolution(tmp_path)
    store.path.write_bytes(b'broken')
    assert store.prompt_block('原始', PERSONA) == ''


def test_account_isolation(experiment, tmp_path):
    store, clock, items = experiment
    enable(store, clock, items)
    store.apply(proposal(store, items), items)
    other = PersonaEvolution(tmp_path / 'another')
    assert not other.status(items)['enabled']
    assert not other.prompt_block('原始', items['原始'])


def test_live_manager_contexts_and_original_owner_remain(experiment, tmp_path, monkeypatch):
    store, clock, items = experiment
    path = tmp_path / 'personas.json'
    items['其他'] = {**PERSONA, 'system_prompt': '其他人格'}
    path.write_text(json.dumps({'active_persona': '原始', 'personas': items}), encoding='utf-8')
    monkeypatch.setattr(managers, 'PERSONAS_FILE', str(path))
    manager = managers.PersonaManager({'persona': {'contexts': {'learning': '其他'}}})
    original_file = path.read_bytes()
    enable(store, clock, items)
    store.apply(proposal(store, items), items)
    assert '实验性表达风格' in manager.build_prompt_block()
    assert '主人关系不可变' in manager.build_prompt_block()
    assert '不得编造' in manager.build_prompt_block()
    assert '实验性表达风格' not in manager.build_prompt_block('learning')
    assert manager.get_system_prompt() == PERSONA['system_prompt']
    store.disable()
    assert '实验性表达风格' not in manager.build_prompt_block()
    assert path.read_bytes() == original_file


def test_fingerprint_keeps_whitespace():
    assert fingerprint({'prompt': ' x '}) != fingerprint({'prompt': 'x'})
