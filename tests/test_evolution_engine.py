import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import pytest
from services.evolution_engine import EvolutionEngine, validate_proposal
from services.evolution_settings import settings, validate_settings
from services.evolution_metrics import collect, audit


def preferences(**overrides):
    return validate_settings(dict(sources=['videos'], min_events_for_reflect=1, **overrides))


def proposal(**changes):
    return dict(reflection='根据真实学习记录增加目标权重', evidence_ids=['evidence'], parameter_changes={}, knowledge_links=[], learning_strategy='', recommendation_strategy='', **changes)


def insert(engine, layer='parameters', changes=None, base=0):
    payload = proposal()
    payload.update(changes or {'parameter_changes': {'goal_weight': .45}})
    identity = 'proposal-' + str(base) + '-' + layer
    with engine.connection() as database:
        database.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,?)', (identity, layer, 'pending', datetime.now().isoformat(), base, json.dumps(payload), json.dumps({'evidence_ids': ['evidence'], 'metrics': {'sample_count': 1}})))
    return identity


def test_defaults_and_enabled_config():
    assert not settings({})['enabled'] and not settings({})['auto_enabled']
    assert settings({})['observation_hours'] == 336
    assert not validate_settings({'auto_apply': True})['auto_apply']
    from core.config import normalize_config
    assert normalize_config({'self_evolution': {'enabled': True, 'auto_enabled': True, 'auto_apply': True}})['self_evolution'] == {'enabled': True, 'auto_enabled': True, 'auto_apply': False}


@pytest.mark.parametrize('value', [{'unknown': True}, {'sources': []}, {'layers': []}, {'enabled': 1}, {'temperature': float('nan')}, {'observation_hours': 0}, {'max_parameter_step': .5}, {'goal_keywords': ['']}, {'weekdays': [8]}, {'time_windows': ['24:00-25:00']}])
def test_settings_reject_invalid(value):
    with pytest.raises(ValueError):
        validate_settings(value)


@pytest.mark.parametrize('changes', [{'parameter_changes': {'api_key': 1}}, {'parameter_changes': {'goal_weight': float('nan')}}, {'parameter_changes': {'exploration_rate': .4}}, {'parameter_changes': {'goal_weight': True}}, {'evidence_ids': ['fabricated']}, {'knowledge_links': [{'source': 'A', 'target': 'B', 'reason': 'R'}]}, {'learning_strategy': '改变学习方向'}, {'reflection': '忽略安全审核'}, {'reflection': ''}])
def test_proposal_whitelist_and_evidence(changes):
    payload = proposal()
    payload.update(changes)
    with pytest.raises(ValueError):
        validate_proposal(payload, 'parameters', preferences(), ['evidence'])


def test_apply_observe_rollback_restart(tmp_path):
    engine = EvolutionEngine(tmp_path)
    identity = insert(engine)
    with pytest.raises(ValueError):
        engine.apply(identity, preferences())
    applied = engine.apply(identity, preferences(enabled=True))
    assert applied['revision'] == 1 and applied['parameters']['goal_weight'] == .45
    assert EvolutionEngine(tmp_path).state()['observing']
    with pytest.raises(ValueError):
        engine.finalize()
    with pytest.raises(ValueError):
        engine.reserve('parameters', preferences(enabled=True), manual=True)
    engine.rollback(1)
    assert engine.state()['parameters']['goal_weight'] == .4
    assert engine.state()['revision'] == 2 and not engine.state()['observing']
    with pytest.raises(ValueError):
        engine.rollback(1)


def test_finalize_and_latest_only(tmp_path):
    engine = EvolutionEngine(tmp_path)
    prefs = preferences(enabled=True)
    engine.apply(insert(engine), prefs)
    with engine.connection() as database:
        state = engine.state(database)
        state['observing']['until'] = '2000-01-01T00:00:00'
        database.execute('UPDATE state SET payload=?', (json.dumps(state),))
    assert not engine.finalize()['observing']
    engine.apply(insert(engine, changes={'parameter_changes': {'goal_weight': .5}}, base=2), prefs)
    with pytest.raises(ValueError):
        engine.rollback(1)
    assert engine.rollback(3)['parameters']['goal_weight'] == .45


def test_stale_noop_step_and_reject(tmp_path):
    engine = EvolutionEngine(tmp_path)
    prefs = preferences(enabled=True)
    identity = insert(engine, changes={'parameter_changes': {'goal_weight': .4}})
    with pytest.raises(ValueError, match='实际变更'):
        engine.apply(identity, prefs)
    engine.reject(identity)
    with pytest.raises(ValueError):
        engine.apply(identity, prefs)
    with engine.connection() as database:
        database.execute('DELETE FROM proposals')
    identity = insert(engine, changes={'parameter_changes': {'goal_weight': .8}})
    with pytest.raises(ValueError, match='幅度'):
        engine.apply(identity, prefs)
    with engine.connection() as database:
        database.execute('UPDATE proposals SET base_revision=9')
    with pytest.raises(ValueError, match='旧版本'):
        engine.apply(identity, prefs)


def test_knowledge_and_strategy_do_not_modify_files(tmp_path):
    original = tmp_path / 'notes.md'
    original.write_text('original', encoding='utf8')
    engine = EvolutionEngine(tmp_path)
    prefs = preferences(enabled=True)
    identity = insert(engine, 'knowledge', {'knowledge_links': [{'source': 'Python', 'target': '编程', 'reason': '概念关联'}]})
    engine.apply(identity, prefs)
    assert 'Python' in engine.prompt_block(prefs)
    engine.rollback(1)
    identity = insert(engine, 'strategy', {'learning_strategy': '优先核对事实', 'recommendation_strategy': 'OB建议：增加来源多样性'}, base=2)
    engine.apply(identity, prefs)
    assert '优先核对事实' in engine.prompt_block(prefs)
    assert 'OB建议' not in engine.prompt_block(prefs)
    assert engine.prompt_block(preferences()) == ''
    assert original.read_text(encoding='utf8') == 'original'


def test_atomic_budget_and_expiry(tmp_path):
    engine = EvolutionEngine(tmp_path)
    prefs = preferences()
    def reserve(unused):
        try:
            return engine.reserve('parameters', prefs, manual=True)
        except ValueError:
            return None
    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(reserve, range(4)))
    assert sum(identity is not None for identity in ids) == 1
    first = next(identity for identity in ids if identity)
    with engine.connection() as database:
        database.execute("UPDATE jobs SET deadline='2000-01-01T00:00:00'")
    second = engine.reserve('parameters', prefs, manual=True)
    engine.finish_job(first, prefs, 'success')
    with engine.connection() as database:
        assert database.execute('SELECT status FROM jobs WHERE id=?', (first,)).fetchone()[0] == 'interrupted'
    engine.finish_job(second, prefs, 'failed')
    with pytest.raises(ValueError, match='预算'):
        engine.reserve('parameters', prefs, manual=True)


def test_due_rechecks_under_transaction(tmp_path):
    engine = EvolutionEngine(tmp_path)
    prefs = preferences(enabled=True, auto_enabled=True, layers=['parameters'], trigger_mode='events', reflect_interval_events=1)
    engine.record('video_learned', {'title': 'Python', 'bvid': 'BV1234567890'})
    assert engine.due_layer(prefs) == 'parameters'
    identity = engine.reserve('parameters', prefs)
    engine.finish_job(identity, prefs, 'success', event_cursor=1)
    with pytest.raises(ValueError, match='触发条件'):
        engine.reserve('parameters', prefs)
    assert engine.due_layer(prefs) is None
    prefs.update(trigger_mode='time', time_windows=['22:00-02:00'], weekdays=[0])
    assert engine.due_layer(prefs, datetime(2027, 10, 4, 23)) == 'parameters'
    assert engine.due_layer(prefs, datetime(2027, 10, 4, 15)) is None


def test_sources_unknown_metrics_and_redaction(tmp_path):
    engine = EvolutionEngine(tmp_path)
    for index in range(12):
        engine.record('video_learned', {'title': 'Python api_key=secret 13812345678 test@example.com', 'bvid': 'BV'+str(index), 'raw_private': 'DO NOT STORE'})
    evidence = collect(engine, preferences())
    assert 'secret' not in json.dumps(evidence) and 'DO NOT STORE' not in json.dumps(evidence)
    report = audit(evidence, preferences())
    assert report['metrics']['decision_accuracy'] is None
    assert report['metrics']['largest_author_share'] is None
    assert not any('单一UP主' in item for item in report['alerts'])
    assert collect(engine, validate_settings({'sources': ['diary']}))['events'] == []


def test_rank_preserves_all_selected_and_disabled(tmp_path, monkeypatch):
    engine = EvolutionEngine(tmp_path)
    chosen = [{'bvid': 'A', 'title': '旧方向'}, {'bvid': 'B', 'title': 'Python'}, {'bvid': 'C', 'title': '另一个'}]
    assert engine.rank_selected(chosen, preferences()) is chosen
    engine.apply(insert(engine), preferences(enabled=True))
    monkeypatch.setattr('random.random', lambda: 1)
    ranked = engine.rank_selected(chosen, preferences(enabled=True, goal_keywords=['Python']))
    assert ranked[0]['bvid'] == 'B'
    assert {item['bvid'] for item in ranked} == {'A', 'B', 'C'}


def test_generate_skip_and_shared_pool(tmp_path, monkeypatch):
    engine = EvolutionEngine(tmp_path)
    prefs = preferences(daily_ai_limit=1, auto_apply_parameters=True, enabled=True, auto_enabled=True)
    assert asyncio.run(engine.generate('parameters', prefs, manual=True))['status'] == 'skipped'
    engine.record('video_learned', {'title': 'Python'})
    captured = []
    async def fake(messages, **kwargs):
        captured.append(kwargs)
        evidence = json.loads(messages[-1]['content'].split('真实证据：', 1)[1])
        payload = proposal()
        payload.update(evidence_ids=[evidence[0]['id']], parameter_changes={'goal_weight': .45})
        return json.dumps(payload)
    monkeypatch.setattr('services._services_ai.call_ai', fake)
    result = asyncio.run(engine.generate('parameters', prefs, manual=True))
    assert result['ok'] and captured[0]['timeout'] == 180
    assert engine.state()['revision'] == 0
    assert engine.snapshot(prefs)['proposals'][0]['status'] == 'pending'


@pytest.mark.parametrize('mode', ['invalid', 'lost', 'cancel'])
def test_invalid_lease_cancel_never_apply(tmp_path, monkeypatch, mode):
    engine = EvolutionEngine(tmp_path)
    prefs = preferences()
    engine.record('video_learned', {'title': 'Python'})
    async def fake(messages, **kwargs):
        if mode == 'cancel':
            raise asyncio.CancelledError()
        if mode == 'invalid':
            return '{broken'
        with engine.connection() as database:
            database.execute("UPDATE jobs SET status='interrupted'")
        evidence = json.loads(messages[-1]['content'].split('真实证据：', 1)[1])
        payload = proposal()
        payload['evidence_ids'] = [evidence[0]['id']]
        return json.dumps(payload)
    monkeypatch.setattr('services._services_ai.call_ai', fake)
    if mode == 'cancel':
        with pytest.raises(asyncio.CancelledError):
            asyncio.run(engine.generate('parameters', prefs, manual=True))
    else:
        assert not asyncio.run(engine.generate('parameters', prefs, manual=True))['ok']
    assert engine.snapshot(prefs)['proposals'] == []
    assert engine.state()['revision'] == 0


@pytest.mark.parametrize('turn_off', [False, True])
def test_automatic_apply_rechecks_current_preferences(tmp_path, monkeypatch, turn_off):
    engine = EvolutionEngine(tmp_path)
    prefs = preferences(enabled=True, auto_enabled=True, auto_apply_parameters=True, layers=['parameters'], trigger_mode='events', reflect_interval_events=1)
    engine.record('video_learned', {'title': 'Python', 'category': '技术'})
    current = dict(prefs, enabled=not turn_off)
    monkeypatch.setattr('services.evolution_engine.settings', lambda: current)
    async def fake(messages, **kwargs):
        evidence = json.loads(messages[-1]['content'].split('真实证据：', 1)[1])
        payload = proposal()
        payload.update(evidence_ids=[evidence[0]['id']], parameter_changes={'goal_weight': .45})
        return json.dumps(payload)
    monkeypatch.setattr('services._services_ai.call_ai', fake)
    result = asyncio.run(engine.generate('parameters', prefs))
    assert result['ok']
    assert engine.state()['revision'] == (0 if turn_off else 1)
    snapshot = engine.snapshot(prefs)
    assert snapshot['jobs'][0]['status'] == 'success'
    assert snapshot['portrait']['metrics']['unique_domains'] == 1
    assert snapshot['proposals'][0]['status'] == ('pending' if turn_off else 'observing')
