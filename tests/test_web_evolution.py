import json
import subprocess
from pathlib import Path

import pytest
import core.config as config
import web_panel
from services.evolution_engine import EvolutionEngine


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(web_panel.app, 'testing', True)
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path / 'config.json'))
    monkeypatch.setattr(config, 'CIPHER_KEY_FILE', str(tmp_path / '.cipher_key'))
    config.save_config({'self_evolution': {'enabled': False}, 'api': {'key': 'preserved'}})
    with web_panel.app.test_client() as instance:
        yield instance


def test_settings_entry_assets_and_safety(client):
    result = client.get('/api/evolution').get_json()
    assert result['ok'] and not result['settings']['enabled']
    assert result['portrait']['metrics']['decision_accuracy'] is None
    result = client.post('/api/evolution/settings', json={'enabled': True, 'auto_enabled': True, 'sources': ['videos'], 'time_windows': ['22:00-02:00'], 'goal_keywords': ['Python']})
    assert result.status_code == 200
    assert config.load_config()['self_evolution']['enabled']
    assert config.load_config()['api']['key'] == 'preserved'
    assert client.post('/api/evolution/settings', json={'api_key': 'forbidden'}).status_code == 400
    for asset in ('js/evolution.js', 'css/evolution.css'):
        assert client.get('/assets/' + asset).status_code == 200
    html = client.get('/').get_data(as_text=True)
    assert 'id="pg-evolution"' in html and '/assets/js/evolution.js' in html


@pytest.mark.parametrize('body', [{}, [1], {'confirmed': False}, {'confirmed': True, 'layer': 'unsafe'}])
def test_generate_requires_valid_confirmation(client, body):
    assert client.post('/api/evolution/generate', json=body).status_code == 400


@pytest.mark.parametrize('body', [{}, [1], {'confirmed': False}, {'confirmed': True, 'action': 'unsafe'}, {'confirmed': True, 'action': 'rollback', 'version_id': '1'}])
def test_action_validation(client, body):
    assert client.post('/api/evolution/action', json=body).status_code == 400


def test_generation_manual_and_duplicate(client, tmp_path, monkeypatch):
    tasks = []
    class DeferredThread:
        def __init__(self, target, **kwargs):
            tasks.append(target)
        def start(self):
            pass
    monkeypatch.setattr(web_panel.threading, 'Thread', DeferredThread)
    response = client.post('/api/evolution/generate', json={'confirmed': True, 'layer': 'parameters'})
    assert response.status_code == 202
    assert not config.load_config()['self_evolution']['enabled']
    assert client.post('/api/evolution/generate', json={'confirmed': True}).status_code == 400
    tasks[0]()
    assert EvolutionEngine(tmp_path).snapshot()['jobs'][0]['status'] == 'skipped'


def test_review_apply_and_rollback(client, tmp_path):
    engine = EvolutionEngine(tmp_path)
    payload = {'reflection': '来源多样性微调', 'evidence_ids': ['event'], 'parameter_changes': {'goal_weight': .45}}
    with engine.connection() as database:
        database.execute('INSERT INTO proposals VALUES(?,?,?,?,?,?,?)', ('review-test', 'parameters', 'pending', '2026-10-06', 0, json.dumps(payload), json.dumps({'evidence_ids': ['event'], 'metrics': {}})))
    assert client.post('/api/evolution/action', json={'confirmed': True, 'action': 'apply', 'proposal_id': 'review-test'}).status_code == 400
    client.post('/api/evolution/settings', json={'enabled': True})
    assert client.post('/api/evolution/action', json={'confirmed': True, 'action': 'apply', 'proposal_id': 'review-test'}).get_json()['ok']
    assert engine.state()['observing']
    assert client.post('/api/evolution/action', json={'confirmed': True, 'action': 'finalize'}).status_code == 400
    assert client.post('/api/evolution/action', json={'confirmed': True, 'action': 'rollback', 'version_id': 1}).get_json()['ok']
    assert engine.state()['parameters']['goal_weight'] == .4



def test_authentication_still_required(client, monkeypatch):
    monkeypatch.setattr(web_panel.app, 'testing', False)
    assert client.get('/api/evolution').status_code == 401
    assert client.post('/api/evolution/settings', json={'enabled': True}).status_code == 401


def test_js_render_handles_numeric_evidence(tmp_path):
    script_path = Path(__file__).resolve().parents[1] / 'assets/js/evolution.js'
    harness = r"""
const fs=require('fs'),vm=require('vm');
var box={innerHTML:'',querySelectorAll:()=>[]};
var context={esc:value=>value.replace(/&/g,'&amp;').replace(/</g,'&lt;'),document:{getElementById:()=>box},setInterval:()=>1,clearInterval:()=>{}};
vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const prefs={layers:['parameters'],sources:['videos'],weekdays:[0],time_windows:['22:00-02:00'],goal_keywords:['Python']};
context.renderEvolution({settings:prefs,state:{revision:0,parameters:{}},portrait:{metrics:{}},proposals:[{id:'test',layer:'parameters',status:'pending',base_revision:0,payload:{reflection:'<unsafe>',evidence_ids:['1','2']}}],jobs:[],versions:[]});
if(!box.innerHTML.includes('证据 2 条')||box.innerHTML.includes('<unsafe>')||!box.innerHTML.includes('22:00-02:00'))throw Error('render regression');
"""
    result = subprocess.run(['node', '-e', harness, str(script_path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
