"""Account permission UI companion routes."""
from flask import Blueprint, jsonify, request, current_app

blueprint = Blueprint('permission_management', __name__)
LEGACY_ACTIONS = {'enable_comment': 'public_comment', 'enable_reply_comment': 'public_comment',
                 'enable_reply_dm': 'private_reply', 'enable_active_dm': 'private_reply',
                 'enable_owner_share': 'private_reply', 'enable_like': 'video_like',
                 'enable_coin': 'coin', 'enable_favorite': 'favorite', 'enable_follow': 'follow_up',
                 'enable_watch_later': 'watch_later', 'enable_dynamic_draft': 'dynamic_draft',
                 'enable_dynamic_publish': 'dynamic_publish'}


@blueprint.route('/api/collection-settings', methods=['GET', 'POST'])
def collection_settings():
    from core.config_schema import FavoriteSettings
    from pydantic import ValidationError
    config = current_app.config['LEARNING_READ_CONFIG']()
    try:
        if request.method == 'POST':
            body = request.get_json(silent=True)
            keys = set(FavoriteSettings.model_fields)
            if not isinstance(body, dict) or set(body) - keys:
                raise ValueError('未知收藏设置')
            source = dict(config.get('local_favorites', {}))
            source.update(body)
            config['local_favorites'] = FavoriteSettings.model_validate(source).model_dump()
            if not current_app.config['LEARNING_WRITE_CONFIG'](config):
                return jsonify(ok=False, message='保存失败'), 500
        return jsonify(ok=True, settings=FavoriteSettings.model_validate(config.get('local_favorites', {})).model_dump())
    except (ValueError, ValidationError):
        return jsonify(ok=False, message='收藏设置格式不正确'), 400


@blueprint.route('/api/platform-favorites', methods=['GET', 'POST'])
def platform_favorites():
    from services.platform_favorites import propose
    try:
        if request.method == 'POST':
            body = request.get_json(silent=True)
            if not isinstance(body, dict) or set(body) - {'operation', 'payload'}:
                raise ValueError('请求必须包含 operation 与 payload')
            return jsonify(propose(body.get('operation'), body.get('payload'), current_app.config['LEARNING_DATA_DIRECTORY']()))
        from api.client import BiliClient
        from bilibili_api import favorite_list
        import asyncio
        client = BiliClient()
        client._load_credential()
        if not client.credential:
            return jsonify(ok=False, message='请先登录 B 站'), 409
        folder = request.args.get('media_id', type=int)
        page = request.args.get('page', 1, type=int)
        if not 1 <= page <= 10000 or (folder is not None and folder <= 0):
            raise ValueError('收藏夹或页码无效')
        async def read():
            if folder:
                return await favorite_list.FavoriteList(media_id=folder, credential=client.credential).get_content_video(page=page)
            return await favorite_list.get_video_favorite_list(uid=int(client.credential.dedeuserid), credential=client.credential)
        return jsonify(ok=True, data=asyncio.run(read()))
    except PermissionError as error:
        return jsonify(ok=False, message=str(error)), 403
    except (TypeError, ValueError) as error:
        return jsonify(ok=False, message=str(error)), 400
    except Exception:
        return jsonify(ok=False, message='平台接口读取失败，请检查登录及网络'), 502
