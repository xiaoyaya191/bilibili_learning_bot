"""Authenticated database operations and explicit native-video capability settings."""
import json
import sqlite3
import tempfile
from pathlib import Path
from flask import Blueprint, current_app, jsonify, request, Response
from services.direct_video import settings
from utils.database import DocumentDatabase, register_directory
from utils.storage import JsonStore

blueprint = Blueprint('data_settings', __name__)


def directory():
    result = current_app.config['DATA_SETTINGS_DIRECTORY']()
    register_directory(result)
    return Path(result)


@blueprint.errorhandler(ValueError)
def invalid(error):
    return jsonify(ok=False, message=str(error)), 400


@blueprint.errorhandler(sqlite3.Error)
@blueprint.errorhandler(OSError)
def failed(error):
    return jsonify(ok=False, message='数据库或本地存储操作失败，未删除原始JSON，请检查磁盘和权限'), 500


@blueprint.route('/api/direct-video/settings', methods=['GET', 'POST'])
def direct_video_settings():
    store = JsonStore(directory() / 'config.json')
    config = store.read({})
    if request.method == 'GET':
        return jsonify(ok=True, settings=settings(config.get('direct_video', {})),
                       protocol='chat_completions_video_url_base64_mp4')
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or set(value) - {'settings', 'confirmed'}:
        raise ValueError('设置请求格式错误')
    if not isinstance(value.get('settings'), dict):
        raise ValueError('缺少设置内容')
    preferences = settings(value['settings'])
    if preferences['enabled'] and value.get('confirmed') is not True:
        raise ValueError('请确认视频将发送至所选模型API并可能产生费用')
    def update(document):
        document['direct_video'] = preferences
    if not store.update(update):
        raise OSError('save failed')
    import core.config as core_config
    if Path(core_config.CONFIG_FILE).resolve() == store.path.resolve():
        current = core_config.load_config()
        core_config.config.clear()
        core_config.config.update(current)
    return jsonify(ok=True, settings=preferences, message='视频直传设置已保存')


@blueprint.get('/api/storage/database')
def database_status():
    return jsonify(ok=True, **DocumentDatabase(directory()).status())


@blueprint.post('/api/storage/database/migrate')
def migrate():
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or value.get('confirmed') is not True:
        raise ValueError('请确认迁移当前账号JSON；保留原文件及原始快照')
    try:
        result = DocumentDatabase(directory()).migrate(include_root=True)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError('某个JSON损坏，整批迁移已回滚；请修复原文件再重试') from None
    return jsonify(ok=True, message='当前账号JSON已事务迁移至SQLite，保留兼容文件及原始快照', **result)


@blueprint.post('/api/storage/database/download')
def download():
    value = request.get_json(silent=True)
    if not isinstance(value, dict) or value.get('confirmed') is not True:
        raise ValueError('数据库包含API密钥、Cookie与聊天数据，请确认下载并妥善保管')
    with tempfile.TemporaryDirectory(prefix='bili-db-backup-') as temporary:
        target = Path(temporary) / 'account_data.sqlite3'
        DocumentDatabase(directory()).snapshot(target)
        raw = target.read_bytes()
    return Response(raw, mimetype='application/vnd.sqlite3',
                    headers={'Content-Disposition': 'attachment; filename="account_data.sqlite3"', 'Cache-Control': 'no-store'})
