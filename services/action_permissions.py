"""Live, account-scoped authorization for AI side effects."""
from functools import wraps
from urllib.parse import urlsplit


ACTIONS = {
    'knowledge_write': ('知识与学习记录', 'local', True),
    'memory_write': ('记忆与画像更新', 'local', True),
    'local_favorite': ('项目内收藏', 'local', True),
    'file_export': ('导出文件', 'local', True),
    'dynamic_draft': ('保存动态草稿', 'local', True),
    'video_like': ('视频点赞', 'platform', False),
    'video_unlike': ('取消视频点赞', 'platform', False),
    'coin': ('投币（不可撤回）', 'platform', False),
    'favorite': ('平台收藏视频', 'platform', False),
    'favorite_remove': ('从平台收藏夹删除视频', 'platform', False),
    'favorite_create': ('创建平台收藏夹', 'platform', False),
    'favorite_edit': ('修改平台收藏夹', 'platform', False),
    'favorite_delete': ('删除平台收藏夹', 'platform', False),
    'favorite_copy': ('复制收藏夹视频', 'platform', False),
    'favorite_move': ('移动收藏夹视频', 'platform', False),
    'favorite_clean': ('清理失效收藏', 'platform', False),
    'follow_up': ('关注用户', 'platform', False),
    'unfollow_user': ('取消关注', 'platform', False),
    'public_comment': ('发布或回复评论', 'platform', False),
    'comment_like': ('评论点赞', 'platform', False),
    'comment_delete': ('删除评论', 'platform', False),
    'private_reply': ('发送或回复私信', 'platform', False),
    'send_danmaku': ('发送弹幕', 'platform', False),
    'danmaku_like': ('弹幕点赞', 'platform', False),
    'watch_later': ('平台稍后再看同步', 'platform', False),
    'dynamic_publish': ('发布动态', 'platform', False),
    'dynamic_delete': ('删除动态', 'platform', False),
    'dynamic_like': ('动态点赞', 'platform', False),
    'dynamic_repost': ('转发动态', 'platform', False),
}


def defaults():
    return {'enabled': False, 'actions': {key: value[2] for key, value in ACTIONS.items()}}


def settings(config=None):
    result = defaults()
    if config is None:
        from core.config import load_config
        config = load_config()
    source = config.get('ai_permissions', {}) if isinstance(config, dict) else {}
    if isinstance(source, dict):
        result['enabled'] = source.get('enabled') is True
        if isinstance(source.get('actions'), dict):
            for key in ACTIONS:
                if key in source['actions'] and type(source['actions'][key]) is bool:
                    result['actions'][key] = source['actions'][key]
    result['actions'] = {key: result['actions'][key] for key in ACTIONS}
    return result


def allowed(action, config=None):
    if action not in ACTIONS:
        return False
    try:
        if config is None:
            from core.config import load_config
            config = load_config()
        source = config.get('ai_permissions', {})
        if not isinstance(source, dict) or not isinstance(source.get('actions', {}), dict):
            return False
        if action in source.get('actions', {}) and type(source['actions'][action]) is not bool:
            return False
        current = settings(config)
        permitted = current['actions'].get(action, False) is True
        return permitted and (ACTIONS[action][1] == 'local' or current['enabled'])
    except Exception:
        return False


def require(action, config=None):
    if not allowed(action, config):
        raise PermissionError('AI 操作权限未授权: ' + str(action))


TOOL_ACTIONS = {'reply_comment': 'public_comment', 'follow_up': 'follow_up',
                'kb_add': 'knowledge_write', 'memory_write': 'memory_write', 'local_favorite_add': 'local_favorite'}


def tool_allowed(tool, arguments=None):
    if tool.risk == 'read':
        return True
    if tool.name == 'manage_platform_action':
        from services.platform_management import ACTIONS as managed_actions
        if arguments is None:
            return any(allowed(action) for action in managed_actions)
        return arguments.get('action') in managed_actions and allowed(arguments['action'])
    if tool.name == 'manage_platform_favorites':
        from services.platform_favorites import OPERATIONS
        if arguments is None:
            return any(allowed(value) for value in OPERATIONS.values())
        return allowed(OPERATIONS.get(arguments.get('operation')))
    if tool.name == 'video_interact':
        actions = {'like': 'video_like', 'coin': 'coin', 'favorite': 'favorite', 'comment': 'public_comment'}
        if arguments is None:
            return allowed('local_favorite') or any(allowed(value) for value in actions.values())
        if arguments.get('action') == 'favorite':
            from core.config import load_config
            if load_config().get('local_favorites', {}).get('destination', 'local') == 'local':
                return allowed('local_favorite')
        return allowed(actions.get(arguments.get('action')))
    return allowed(TOOL_ACTIONS.get(tool.name))


def request_actions(url, data=None, method='POST'):
    path = urlsplit(url).path
    data = data or {}
    if method.upper() in ('GET', 'HEAD', 'OPTIONS'):
        return []
    fixed = {
        '/x/v3/fav/folder/add': 'favorite_create', '/x/v3/fav/folder/edit': 'favorite_edit',
        '/x/v3/fav/folder/del': 'favorite_delete', '/x/v3/fav/resource/copy': 'favorite_copy',
        '/x/v3/fav/resource/move': 'favorite_move', '/x/v3/fav/resource/batch-del': 'favorite_remove',
        '/x/v3/fav/resource/clean': 'favorite_clean', '/x/v2/dm/post': 'send_danmaku',
        '/x/v2/dm/thumbup/add': 'danmaku_like', '/web_im/v1/web_im/send_msg': 'private_reply',
        '/x/v2/reply/add': 'public_comment', '/x/v2/reply/like': 'comment_like',
        '/x/v2/reply/action': 'comment_like',
        '/x/v2/reply/del': 'comment_delete', '/x/v2/history/toview/add': 'watch_later',
        '/x/v2/history/toview/del': 'watch_later', '/x/v2/history/toview/clear': 'watch_later',
        '/x/dynamic/feed/draw/upload_bfs': 'dynamic_publish',
        '/x/dynamic/feed/create/dyn': 'dynamic_publish', '/x/dynamic/feed/create/submit_check': 'dynamic_publish',
        '/dynamic_svr/v1/dynamic_svr/create': 'dynamic_publish',
        '/dynamic_svr/v1/dynamic_svr/create_draw': 'dynamic_publish',
        '/dynamic_svr/v1/dynamic_svr/rm_dynamic': 'dynamic_delete',
        '/dynamic_like/v1/dynamic_like/thumb': 'dynamic_like',
        '/dynamic_repost/v1/dynamic_repost/repost': 'dynamic_repost',
        '/dynamic_repost/v1/dynamic_repost/share': 'dynamic_repost',
        '/dynamic_draft/v1/dynamic_draft/publish_now': 'dynamic_publish',
        '/dynamic_draft/v1/dynamic_draft/add_draft': 'dynamic_publish',
        '/dynamic_draft/v1/dynamic_draft/modify_draft': 'dynamic_publish',
        '/dynamic_draft/v1/dynamic_draft/rm_draft': 'dynamic_delete',
    }
    if path in fixed:
        return [fixed[path]]
    if path == '/x/web-interface/coin/add':
        return ['coin', 'video_like'] if str(data.get('select_like', '0')) == '1' else ['coin']
    if path == '/x/web-interface/archive/like':
        return ['video_unlike' if str(data.get('like')) == '2' else 'video_like']
    if path == '/x/web-interface/archive/like/triple':
        return ['video_like', 'coin', 'favorite']
    if path == '/x/v3/fav/resource/deal':
        return (['favorite'] if data.get('add_media_ids') else []) + (['favorite_remove'] if data.get('del_media_ids') else []) or ['favorite']
    if path == '/x/relation/modify':
        return ['follow_up' if str(data.get('act')) == '1' else 'unfollow_user']
    if urlsplit(url).hostname == 'passport.bilibili.com':
        return []
    if path in {'/x/v2/history/report', '/x/click-interface/click/web/h5'}:
        return []
    return ['unregistered_platform_write']


def install_sdk_guard():
    from bilibili_api.utils.network import Api
    if getattr(Api.request, '_ai_permissions', False):
        return
    original = Api.request

    @wraps(original)
    async def guarded(api, *args, **kwargs):
        for action in request_actions(api.url, getattr(api, 'data', {}), api.method):
            require(action)
        return await original(api, *args, **kwargs)

    guarded._ai_permissions = True
    Api.request = guarded
