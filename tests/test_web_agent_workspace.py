import json
import sqlite3
import pytest
import core.config as config
import web_panel
from services.agent_workspace import Workspace, LIVE


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(web_panel, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(web_panel.app, 'testing', True)
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path/'config.json'))
    monkeypatch.setattr(config, 'CIPHER_KEY_FILE', str(tmp_path/'.cipher_key'))
    config.save_config({'agent':{'enabled':True}})
    monkeypatch.setattr('services.agent_workspace.WorkspaceSession.start',lambda self:True)
    with web_panel.app.test_client() as client:
        yield client
    LIVE.clear()


def test_ui_routes_profiles_and_chat(client,tmp_path):
    html=client.get('/').get_data(as_text=True)
    assert 'id="assistantTranscript"' in html and '/assets/js/agent-assistant.js' in html
    for asset in ['js/agent-assistant.js','css/agent-assistant.css']:
        assert client.get('/assets/'+asset).status_code==200
    info=client.get('/api/agent/assistant').get_json()
    assert 'contacts' not in info['defaults'] and info['conversations']==[]
    result=client.post('/api/agent/portrait',json={'description':'Python 初学者','goals':['Python'],'avoid':[]})
    assert result.status_code==200 and result.get_json()['self_report']['description']=='Python 初学者'
    sent=client.post('/api/agent/assistant/send',json={'confirmed':True,'message':'帮我了解项目','permissions':['project']})
    assert sent.status_code==202
    identity=sent.get_json()['conversation_id']
    saved=client.get('/api/agent/assistant/'+identity).get_json()['conversation']
    assert saved['turns'][0]['payload']['options']['permissions']==['project']
    assert client.post('/api/agent/assistant/send',json={'confirmed':True,'message':'重复请求'}).status_code==400
    assert client.post('/api/agent/assistant/stop',json={'turn_id':sent.get_json()['turn_id']}).get_json()['ok']


@pytest.mark.parametrize('body',[None,[],{'message':'not confirmed'},{'confirmed':True,'message':'x','permissions':['shell']},{'confirmed':True,'message':'x','max_steps':500},{'confirmed':True,'message':'x','conversation_id':'../private'}])
def test_send_validation(client,body):
    assert client.post('/api/agent/assistant/send',json=body).status_code==400


@pytest.mark.parametrize('body',[[],{'secret':'no'},{'goals':[1]},{'description':'x'*2001}])
def test_profile_validation(client,body):
    assert client.post('/api/agent/portrait',json=body).status_code==400


def test_auth_remains_required(client,monkeypatch):
    monkeypatch.setattr(web_panel.app,'testing',False)
    assert client.get('/api/agent/assistant').status_code==401
    assert client.get('/api/agent/portrait').status_code==401
    assert client.post('/api/agent/assistant/send',json={'confirmed':True,'message':'x'}).status_code==401


def test_old_task_requires_explicit_write_confirmation(client):
    assert client.post('/api/agent/start',json={'goal':'点赞','allow_write':True}).status_code==400
    assert client.post('/api/agent/start',json={'goal':'x','allow_write':'false'}).status_code==400


def test_queue_and_unknown_conversation_validation(client):
    assert client.post('/api/agent/assistant/queue',json={}).status_code==400
    assert client.get('/api/agent/assistant/unknown').status_code==400
    assert client.post('/api/agent/assistant/stop',json=[]).status_code==400


def test_event_cursor_does_not_skip_batches(client,monkeypatch):
    from agent.core import AgentSession
    session=AgentSession('test')
    for index in range(250): session.emit('system',{'message':str(index)})
    monkeypatch.setattr('agent.core.get_active',lambda:session)
    first=client.get('/api/agent/events?after=0').get_json()
    assert first['last_seq']==200
    second=client.get('/api/agent/events?after=200').get_json()
    assert len(second['events'])==50 and second['last_seq']==250


def test_blueprint_storage_errors_are_visible(client,monkeypatch):
    def broken(self): raise sqlite3.OperationalError('bad')
    monkeypatch.setattr(Workspace,'conversations',broken)
    result=client.get('/api/agent/assistant')
    assert result.status_code==500 and not result.get_json()['ok']
