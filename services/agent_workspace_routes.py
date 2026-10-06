"""Authenticated Flask endpoints for the account-local assistant workspace."""
import sqlite3
from flask import Blueprint, current_app, jsonify, request

blueprint = Blueprint('agent_assistant', __name__)


def workspace():
    from core.config import load_config, resolve_knowledge_base_dir
    from services.agent_workspace import Workspace
    return Workspace(current_app.config['AGENT_WORKSPACE_DATA_DIR'](), resolve_knowledge_base_dir(load_config()))


@blueprint.errorhandler(ValueError)
def invalid(error):
    from services.diary_scheduler import clean_text
    return jsonify(ok=False, message=clean_text(str(error))[:400]), 400


@blueprint.errorhandler(sqlite3.Error)
@blueprint.errorhandler(OSError)
def storage_failure(error):
    return jsonify(ok=False, message='本地数据读取或保存失败，请检查数据目录；原始记录未被清空'), 500


@blueprint.get('/api/agent/assistant')
def overview():
    from services.agent_workspace import PERMISSIONS, DEFAULT_PERMISSIONS
    return jsonify(ok=True, conversations=workspace().conversations(), permissions=PERMISSIONS, defaults=DEFAULT_PERMISSIONS)


@blueprint.get('/api/agent/assistant/<identity>')
def conversation(identity):
    return jsonify(ok=True, conversation=workspace().conversation(identity))


@blueprint.post('/api/agent/assistant/send')
def send():
    result = workspace().send(request.get_json(silent=True))
    return jsonify(ok=True, **result), 202


@blueprint.post('/api/agent/assistant/stop')
def stop():
    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        raise ValueError('请求必须是对象')
    return jsonify(ok=workspace().stop(str(body.get('turn_id') or '')))


@blueprint.route('/api/agent/portrait', methods=['GET', 'POST'])
def portrait():
    store = workspace()
    if request.method == 'POST':
        store.save_profile(request.get_json(silent=True))
    return jsonify(**store.portrait())


@blueprint.post('/api/agent/assistant/queue')
def queue():
    return jsonify(**workspace().approve_queue(request.get_json(silent=True)))
