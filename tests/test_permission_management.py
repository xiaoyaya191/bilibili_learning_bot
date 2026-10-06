import asyncio
from unittest.mock import AsyncMock

import pytest
from flask import Flask

from services.action_permissions import ACTIONS, allowed, defaults, request_actions, require
from services.platform_favorites import OPERATIONS, execute, propose, validate_payload


def authorized(*actions):
    return {'ai_permissions': {'enabled': True, 'actions': {action: True for action in actions}}}


@pytest.mark.parametrize('action', list(ACTIONS))
def test_default_authorization_is_safe(action):
    assert allowed(action, {}) is (ACTIONS[action][1] == 'local')


def test_explicit_permission_requires_master_and_revocation_is_live(monkeypatch):
    config = authorized('favorite_remove')
    monkeypatch.setattr('core.config.load_config', lambda: config)
    assert allowed('favorite_remove')
    assert not allowed('favorite_delete')
    config['ai_permissions']['enabled'] = False
    assert not allowed('favorite_remove')
    assert allowed('knowledge_write')


@pytest.mark.parametrize('source', [{'enabled': 'true', 'actions': {'coin': True}}, {'enabled': True, 'actions': {'coin': 'false'}}, {'enabled': True, 'actions': []}])
def test_malformed_permission_is_fail_closed(source):
    assert not allowed('coin', {'ai_permissions': source})
    assert not allowed('not_registered', {'ai_permissions': source})


@pytest.mark.parametrize('path,data,actions', [
    ('/x/web-interface/archive/like', {'like': 2}, ['video_unlike']),
    ('/x/web-interface/archive/like/triple', {}, ['video_like', 'coin', 'favorite']),
    ('/x/v3/fav/resource/deal', {'add_media_ids': '1', 'del_media_ids': '2'}, ['favorite', 'favorite_remove']),
    ('/x/v3/fav/resource/batch-del', {}, ['favorite_remove']),
    ('/x/v3/fav/folder/del', {}, ['favorite_delete']),
    ('/x/relation/modify', {'act': 2}, ['unfollow_user']),
    ('/x/v2/reply/action', {}, ['comment_like']),
    ('/unknown/write', {}, ['unregistered_platform_write']),
    ('/x/v2/history/report', {}, []),
])
def test_sdk_request_classification(path, data, actions):
    assert request_actions('https://api.bilibili.com' + path, data) == actions
    assert request_actions('https://api.bilibili.com' + path, data, 'GET') == []


def test_authentication_post_is_not_disabled():
    assert request_actions('https://passport.bilibili.com/x/passport-login/web/login') == []


def test_registry_hides_and_blocks_unauthorized_tool(monkeypatch):
    from agent.registry import ToolDef, ToolRegistry
    monkeypatch.setattr('core.config.load_config', lambda: {})
    calls = []
    registry = ToolRegistry()
    registry.register(ToolDef('video_interact', 'test', lambda **kwargs: calls.append(kwargs), risk='write'))
    result = asyncio.run(registry.invoke('video_interact', {'action': 'coin', 'allow_write': True, 'confirmed': True}))
    assert not result['ok'] and not calls
    registry.register(ToolDef('unknown_write', 'test', lambda: calls.append(True), risk='write'))
    assert 'unknown_write' not in [item['function']['name'] for item in registry.schemas()]
    assert not asyncio.run(registry.invoke('unknown_write', {}))['ok']


@pytest.mark.parametrize('operation,payload', [('delete', {'media_id': 0}), ('remove', {'media_id': 1, 'bvid': 'bad'}), ('move', {'media_id': 1, 'target_id': 1, 'aids': [1]}), ('copy', {'media_id': 1, 'target_id': 2, 'aids': [True]}), ('create', {'title': ''}), ('create', {'title': 'name', 'private': 'false'}), ('delete', {'media_id': 1, 'confirmed': True})])
def test_collection_payload_rejects_unsafe_values(operation, payload):
    with pytest.raises(ValueError):
        validate_payload(operation, payload)


def test_platform_remove_is_only_proposed_and_revocation_blocks_execute(tmp_path, monkeypatch):
    config = authorized('favorite_remove')
    monkeypatch.setattr('core.config.load_config', lambda: config)
    result = propose('remove', {'media_id': 7, 'bvid': 'BV1ab411c7mD'}, tmp_path)
    assert result['queued'] and result['review_id']
    from services.like_review import ActionReviewInbox
    assert ActionReviewInbox(tmp_path)._read()[0]['payload']['media_id'] == 7
    config['ai_permissions']['enabled'] = False
    with pytest.raises(PermissionError):
        asyncio.run(execute('remove', {'media_id': 7, 'bvid': 'BV1ab411c7mD'}, object()))


@pytest.mark.parametrize('operation', list(OPERATIONS))
def test_all_collection_operations_use_exact_targets(operation, monkeypatch):
    from bilibili_api import favorite_list
    from bilibili_api.video import Video
    monkeypatch.setattr('core.config.load_config', lambda: authorized(*OPERATIONS.values()))
    names = {'create': 'create_video_favorite_list', 'edit': 'modify_video_favorite_list', 'delete': 'delete_video_favorite_list', 'clean': 'clean_video_favorite_list_content', 'copy': 'copy_video_favorite_list_content', 'move': 'move_video_favorite_list_content'}
    target = AsyncMock(return_value={'code': 0})
    if operation in {'add', 'remove'}:
        monkeypatch.setattr(Video, 'set_favorite', target)
        payload = {'media_id': 7, 'bvid': 'BV1ab411c7mD'}
    else:
        monkeypatch.setattr(favorite_list, names[operation], target)
        payload = {'media_id': 7} if operation != 'create' else {}
        if operation in {'create', 'edit'}: payload['title'] = '测试收藏夹'
        if operation in {'copy', 'move'}: payload.update(target_id=8, aids=[123])
    assert asyncio.run(execute(operation, payload, None)) == {'code': 0}
    if operation in {'add', 'remove'}:
        target.assert_awaited_once_with(**{'add_media_ids' if operation == 'add' else 'del_media_ids': [7]})
    else:
        target.assert_awaited_once()


def test_collection_routes_validate_and_do_not_execute(tmp_path, monkeypatch):
    from services.permission_routes import blueprint
    config = {}
    app = Flask(__name__)
    app.config.update(LEARNING_READ_CONFIG=lambda: config, LEARNING_WRITE_CONFIG=lambda value: config.update(value) or True, LEARNING_DATA_DIRECTORY=lambda: tmp_path)
    app.register_blueprint(blueprint)
    monkeypatch.setattr('core.config.load_config', lambda: {})
    client = app.test_client()
    assert client.get('/api/collection-settings').json['settings']['destination'] == 'local'
    assert client.post('/api/collection-settings', json={'destination': 'both'}).status_code == 400
    assert client.post('/api/platform-favorites', json={'operation': 'delete', 'payload': {'media_id': 7}}).status_code == 403


def test_local_collection_respects_target_and_permission(tmp_path):
    from services.local_favorites import auto_collect_video
    video = {'bvid': 'BV1ab411c7mD', 'score': 9}
    assert not auto_collect_video({'local_favorites': {'destination': 'platform'}}, video, interested=True, data_dir=tmp_path)['added']
    assert not auto_collect_video({'ai_permissions': {'actions': {'local_favorite': False}}}, video, interested=True, data_dir=tmp_path)['added']
    assert auto_collect_video({}, video, interested=True, data_dir=tmp_path)['added']


def test_settings_defaults_and_legacy_asr_migration():
    from core.config import normalize_config
    config = normalize_config({'interaction': {'enable_asr': True}})
    assert config['asr']['enabled'] is True
    assert 'enable_asr' not in config['interaction']
    assert config['subtitles']['enabled'] is True
    assert config['ai_permissions']['enabled'] is False


def test_subtitle_off_prevents_network(monkeypatch):
    from api.subtitles import fetch_bilibili_subtitles
    monkeypatch.setattr('core.config.load_config', lambda: {'subtitles': {'enabled': False}})
    assert not asyncio.run(fetch_bilibili_subtitles('BV1ab411c7mD'))[0]


def test_sdk_guard_denies_before_transport(monkeypatch):
    from bilibili_api.utils.network import Api
    from services.action_permissions import install_sdk_guard
    monkeypatch.setattr('core.config.load_config', lambda: {})
    install_sdk_guard()
    with pytest.raises(PermissionError):
        asyncio.run(Api(url='https://api.bilibili.com/x/v3/fav/folder/del', method='POST').request())


def test_panel_permission_routes_live_strict_and_save_failure(monkeypatch):
    import web_panel
    monkeypatch.setattr(web_panel.app, 'testing', True)
    config = {}
    monkeypatch.setattr('core.config.load_config', lambda: config)
    monkeypatch.setattr('core.config.save_config', lambda value: True)
    client = web_panel.app.test_client()
    assert client.get('/api/ai-permissions').json['enabled'] is False
    for body in ({'enabled': 'false'}, {'actions': {'coin': 1}}, {'actions': {'unknown': True}}, {'unexpected': True}):
        assert client.post('/api/ai-permissions', json=body).status_code == 400
    assert client.post('/api/ai-permissions', json={'enabled': True, 'actions': {'coin': True}}).status_code == 200
    assert client.get('/api/interaction-switches').json['switches']['enable_coin'] is True
    assert client.post('/api/interaction-switches', json={'enable_coin': True}).status_code == 409
    assert client.post('/api/interaction-switches', json={'enable_asr': 'false'}).status_code == 400
    assert client.post('/api/interaction-switches', json={'enable_asr': True, 'subtitles_enabled': False}).status_code == 200
    assert config['asr']['enabled'] is True and config['subtitles']['enabled'] is False
    monkeypatch.setattr('core.config.save_config', lambda value: False)
    assert client.post('/api/ai-permissions', json={'enabled': False}).status_code == 500


def test_review_rechecks_permission_before_credential_loading(monkeypatch):
    import web_panel
    from api import client
    monkeypatch.setattr('core.config.load_config', lambda: {})
    monkeypatch.setattr(client, 'BiliClient', lambda: pytest.fail('must deny before credential access'))
    with pytest.raises(PermissionError):
        web_panel._execute_review_action({'action_type': 'favorite_remove', 'payload': {'operation': 'remove', 'media_id': 7, 'bvid': 'BV1ab411c7mD'}})


def test_asr_disabled_blocks_even_mismatched_subtitle_whisper(monkeypatch):
    from brain import _brain_video
    monkeypatch.setattr('core.config.load_config', lambda: {'asr': {'enabled': False}, 'subtitles': {'enabled': True}})
    async def wrong_subtitles(*args, **kwargs):
        return False, '[字幕语义不匹配:WHISPER_FALLBACK]', '', False
    monkeypatch.setattr(_brain_video, 'fetch_bilibili_subtitles', wrong_subtitles)
    class Brain(_brain_video.BrainVideoMixin):
        cookies = {}
        @staticmethod
        def _is_vision_globally_disabled():
            return True
        async def _download_video_for_asr(self, *args, **kwargs):
            pytest.fail('ASR total switch must prevent download')
    assert not asyncio.run(Brain()._understand_super_smart('BV1ab411c7mD', 'Python'))[0]


def test_owner_ai_favorite_default_is_local_not_platform(tmp_path, monkeypatch):
    from services.utils import BiliToolbox
    from services import utils
    toolbox = BiliToolbox(None, 1)
    monkeypatch.setattr(utils, 'DATA_DIR', tmp_path)
    monkeypatch.setattr(toolbox, 'is_owner', lambda uid: True)
    monkeypatch.setattr(toolbox, 'self_status', lambda **kwargs: asyncio.sleep(0, result={}))
    monkeypatch.setattr('core.config.load_config', lambda: {})
    result = asyncio.run(toolbox.request_video_action('favorite', 'BV1ab411c7mD', 'AI 收藏理由', '收藏这个视频', 1))
    assert result['ok'] and result['destination'] == 'local'
    from services.local_favorites import read_library
    assert len(read_library(tmp_path)['items']) == 1


@pytest.mark.parametrize('action,payload', [
    ('video_like', {'bvid': 'BV1ab411c7mD'}), ('video_unlike', {'bvid': 'BV1ab411c7mD'}),
    ('coin', {'bvid': 'BV1ab411c7mD', 'num': 1}), ('follow_up', {'uid': 7}), ('unfollow_user', {'uid': 7}),
    ('public_comment', {'oid': 9, 'text': 'test reply'}), ('comment_like', {'oid': 9, 'rpid': 11}),
    ('comment_delete', {'oid': 9, 'rpid': 11}), ('private_reply', {'receiver_id': 7, 'text': 'test'}),
    ('send_danmaku', {'bvid': 'BV1ab411c7mD', 'text': 'test'}),
    ('danmaku_like', {'bvid': 'BV1ab411c7mD', 'dmid': 11, 'cid': 9}),
    ('dynamic_delete', {'dynamic_id': 11}), ('dynamic_like', {'dynamic_id': 11}),
    ('dynamic_repost', {'dynamic_id': 11, 'text': 'test repost'}),
])
def test_managed_platform_actions_use_mocked_sdk_and_exact_permission(action, payload, tmp_path, monkeypatch):
    from services import platform_management as management
    from bilibili_api import video, user, comment, session, dynamic
    monkeypatch.setattr('core.config.load_config', lambda: authorized(action))
    execute = AsyncMock(return_value={'code': 0})
    class Target:
        def __init__(self, *args, **kwargs):
            pass
        like = execute
        pay_coin = execute
        send_danmaku = execute
        like_danmaku = execute
        modify_relation = execute
        delete = execute
        set_like = execute
        repost = execute
    monkeypatch.setattr(video, 'Video', Target)
    monkeypatch.setattr(user, 'User', Target)
    monkeypatch.setattr(comment, 'Comment', Target)
    monkeypatch.setattr(dynamic, 'Dynamic', Target)
    monkeypatch.setattr(comment, 'send_comment', execute)
    monkeypatch.setattr(session, 'send_msg', execute)
    monkeypatch.setattr('xingye_bot.bilibili_ops._political_hits', lambda text: [])
    proposed = management.propose(action, payload, tmp_path)
    assert proposed['queued'] and proposed['review_id']
    execute.assert_not_awaited()
    assert asyncio.run(management.execute(action, payload, None)) == {'code': 0}
    execute.assert_awaited_once()
    if action == 'video_unlike':
        execute.assert_awaited_once_with(status=False)
    if action == 'coin':
        execute.assert_awaited_once_with(num=1, like=False)


@pytest.mark.parametrize('action,payload', [('comment_delete', {'oid': 1, 'rpid': True}), ('dynamic_delete', {'dynamic_id': 0}), ('coin', {'bvid': 'BV1ab411c7mD', 'num': 3}), ('private_reply', {'receiver_id': 7, 'text': ''}), ('video_unlike', {'bvid': 'BV1ab411c7mD', 'confirmed': True})])
def test_managed_platform_actions_reject_invalid_targets(action, payload):
    from services.platform_management import validate
    with pytest.raises(ValueError):
        validate(action, payload)
