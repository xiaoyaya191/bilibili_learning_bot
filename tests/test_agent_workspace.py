import asyncio
import json
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
import core.config as config
from agent.core import AgentSession
from agent.registry import ToolDef, ToolRegistry
from services.agent_workspace import Workspace, LIVE, validate_options, scrub
from services.video_watch_queue import VideoWatchQueue


def response(text='', calls=None):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text, tool_calls=calls or []))])


def call(name, arguments=None):
    return SimpleNamespace(id='tool-1', function=SimpleNamespace(name=name, arguments=json.dumps(arguments or {})))


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(config, 'CONFIG_FILE', str(tmp_path/'config.json'))
    monkeypatch.setattr(config, 'CIPHER_KEY_FILE', str(tmp_path/'.cipher_key'))
    config.save_config({'agent': {'enabled': True}})
    store = Workspace(tmp_path, tmp_path/'notes')
    yield store
    LIVE.clear()


def body(**options):
    return {'message': '看看最近视频', 'confirmed': True, **options}


@pytest.mark.parametrize('options', [{'confirmed': False}, {'permissions': ['unsafe']}, {'permissions': 'videos'}, {'max_steps': True}, {'max_steps': 21}, {'model': []}])
def test_validation(options):
    value=body(); value.update(options)
    with pytest.raises(ValueError):
        validate_options(value)


def test_scoped_tools(workspace):
    tools=workspace.registry(['videos','profile','project'])
    assert {tool.name for tool in tools.all()} == {'query_watch_history','get_user_portrait','get_project_guide','finish'}
    assert all(tool.risk=='read' for tool in workspace.registry(list(__import__('services.agent_workspace',fromlist=['PERMISSIONS']).PERMISSIONS)).all())
    assert workspace.registry([]).get('get_recent_contacts') is None
    assert workspace.registry(['contacts']).get('get_recent_contacts')


def test_profiles_and_videos(workspace):
    queue=VideoWatchQueue(workspace.data_dir/'video_watch_queue.sqlite3')
    queue.enqueue([{'bvid':'BV1234567890','title':'Python 学习','category':'技术','up':'作者'}])
    queue.claim()
    queue.finish('BV1234567890','done',score=8.5)
    workspace.save_profile({'description':'初学者','goals':['Python'],'avoid':['广告']})
    result=workspace.videos(query='Python',min_score=8)
    assert len(result['videos'])==1
    assert result['videos'][0]['url'].endswith('BV1234567890')
    assert workspace.videos(min_score=9)['videos']==[]
    assert workspace.portrait()['learning_clues']=={'技术':1}
    assert Workspace(workspace.data_dir).profile()['description']=='初学者'
    with pytest.raises(ValueError): workspace.save_profile({'secret':'bad'})


def test_notes_and_contacts_are_bounded_and_redacted(workspace):
    workspace.knowledge_dir.mkdir()
    (workspace.knowledge_dir/'python.md').write_text('Python api_key=SECRET test@example.com',encoding='utf8')
    assert 'SECRET' not in json.dumps(workspace.search_notes('Python'))
    (workspace.data_dir/'private_message_log.json').write_text(json.dumps({'history':[{'talker_id':42,'sender_name':'测试联系人','timestamp':'2026-10-06','incoming':'BODYSECRET','sent':True}]}),encoding='utf8')
    result=workspace.contacts()
    assert result['contacts'][0]['contact']=='测试联系人'
    assert 'BODYSECRET' not in json.dumps(result) and 'talker_id' not in json.dumps(result)
    assert scrub({'key':'x','api_key':'secret','nested':[{'password':'secret','title':'safe'}]})=={'nested':[{'title':'safe'}]}


def test_atomic_running_and_restart(workspace):
    def send(unused):
        try: return workspace.send(body(),launch=False)
        except ValueError: return None
    with ThreadPoolExecutor(max_workers=4) as pool:
        results=list(pool.map(send,range(4)))
    assert sum(bool(item) for item in results)==1
    result=next(item for item in results if item)
    with workspace.connection() as database: database.execute('UPDATE turns SET deadline=0')
    restarted=Workspace(workspace.data_dir)
    assert restarted.conversation(result['conversation_id'])['turns'][0]['status']=='interrupted'
    assert restarted.send(body(conversation_id=result['conversation_id']),launch=False)


def test_normal_chat_and_followup(workspace,monkeypatch):
    captured=[]
    async def fake(messages,**kwargs):
        captured.append(messages.copy())
        return response('这里是项目助理回答')
    monkeypatch.setattr('services._services_ai.call_ai_raw',fake)
    first=workspace.send(body(permissions=[]),launch=False)
    first_session=LIVE[(str(workspace.path),first['turn_id'])]
    first_session.status='running';first_session.started_at=time.time()
    asyncio.run(first_session._loop())
    saved=workspace.conversation(first['conversation_id'])
    assert saved['turns'][0]['status']=='finished'
    assert saved['turns'][0]['payload']['summary']=='这里是项目助理回答'
    second=workspace.send(body(conversation_id=first['conversation_id'],message='继续解释'),launch=False)
    session=LIVE[(str(workspace.path),second['turn_id'])]
    assert any('项目助理回答' in item['content'] for item in session.context)
    assert first_session.steps==1


def test_write_tools_never_execute_even_if_model_invents_call(tmp_path,monkeypatch):
    executed=[]
    registry=ToolRegistry()
    registry.register(ToolDef('danger','write',lambda:executed.append(True) or {'ok':True},risk='write'))
    responses=[response(calls=[call('danger')]),response('无法执行写操作')]
    async def fake(messages,**kwargs):
        assert kwargs['tools']==[]
        return responses.pop(0)
    monkeypatch.setattr('services._services_ai.call_ai_raw',fake)
    session=AgentSession('目标',registry=registry,allow_write=False,chat_mode=True,max_steps=2)
    session.status='running';session.started_at=time.time()
    monkeypatch.setattr(session,'_persist',lambda:None)
    asyncio.run(session._loop())
    assert not executed and session.tool_calls==1
    assert session.events_after(0)[2]['type'] in {'tool_call','tool_result'}


def test_stop_prevents_post_response_tools(workspace,monkeypatch):
    result=workspace.send(body(),launch=False)
    session=LIVE[(str(workspace.path),result['turn_id'])]
    async def fake(messages,**kwargs):
        session.stop()
        return response(calls=[call('query_watch_history')])
    monkeypatch.setattr('services._services_ai.call_ai_raw',fake)
    session.status='running';session.started_at=time.time()
    asyncio.run(session._loop())
    assert session.status=='stopped' and session.tool_calls==0


def test_queue_requires_real_evidence_and_confirmation(workspace):
    result=workspace.send(body(),launch=False)
    session=LIVE[(str(workspace.path),result['turn_id'])]
    session.emit('tool_result',{'name':'query_watch_history','result':{'videos':[{'bvid':'BV1234567890','title':'真实视频'}]}})
    with pytest.raises(ValueError):workspace.approve_queue({'conversation_id':result['conversation_id'],'bvid':'BV1234567890'})
    with pytest.raises(ValueError):workspace.approve_queue({'confirmed':True,'conversation_id':result['conversation_id'],'bvid':'BV9999999999'})
    assert workspace.approve_queue({'confirmed':True,'conversation_id':result['conversation_id'],'bvid':'BV1234567890'})['added']==['BV1234567890']


def test_disabled_agent(workspace):
    config.save_config({'agent':{'enabled':False}})
    with pytest.raises(ValueError):workspace.send(body(),launch=False)


def test_existing_config_and_follow_tools_do_not_write(monkeypatch):
    import agent.tools as tools
    monkeypatch.setattr(config,'save_config',lambda value:pytest.fail('configuration changed'))
    assert not asyncio.run(tools.panel_config_update('reply_safety',{'enabled':False}))['ok']
    assert not asyncio.run(tools.follow_up(42))['ok']
