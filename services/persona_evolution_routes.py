"""Authenticated personality experiment API with server-enforced consent delay."""
import asyncio
import secrets
import sqlite3
from flask import Blueprint, current_app, jsonify, request, session
from services.persona_evolution import PersonaEvolution

blueprint = Blueprint('persona_experiment', __name__)


def store():
    return PersonaEvolution(current_app.config['PERSONA_EVOLUTION_DATA_DIR']())


def personas():
    return current_app.config['PERSONA_EVOLUTION_PERSONAS']()['items']


def owner():
    if 'persona_evolution_owner' not in session:
        session['persona_evolution_owner'] = secrets.token_urlsafe(24)
    return session['persona_evolution_owner']


def body():
    value = request.get_json(silent=True)
    if not isinstance(value, dict):
        raise ValueError('请求必须是JSON对象')
    return value


@blueprint.errorhandler(ValueError)
def invalid(error):
    return jsonify(ok=False, message=str(error)), 400


@blueprint.errorhandler(sqlite3.Error)
@blueprint.errorhandler(OSError)
def storage_error(error):
    return jsonify(ok=False, message='人格备份或实验数据保存失败，操作未完成，请检查账号数据目录'), 500


@blueprint.get('/api/persona-evolution')
def status():
    return jsonify(ok=True, **store().status(personas()))


@blueprint.post('/api/persona-evolution/challenge')
def challenge():
    return jsonify(ok=True, **store().challenge(owner(), personas()))


@blueprint.post('/api/persona-evolution/confirm')
def confirm():
    store().confirm(owner(), str(body().get('token') or ''), personas())
    return jsonify(ok=True, message='原始人格已备份，测试功能已开启；建议需人工审核应用')


@blueprint.post('/api/persona-evolution/cancel')
def cancel():
    store().cancel(owner(), str(body().get('token') or ''))
    return jsonify(ok=True)


@blueprint.post('/api/persona-evolution/disable')
def disable():
    store().disable()
    return jsonify(ok=True, message='已关闭，表达附加层立即停用，原始备份保留')


@blueprint.get('/api/persona-evolution/backups/<int:identity>')
def backup(identity):
    return jsonify(ok=True, backup=store().backup(identity))


@blueprint.post('/api/persona-evolution/generate')
def generate():
    value = body()
    key = value.get('key')
    items = personas()
    if not isinstance(key, str) or key not in items:
        raise ValueError('请先保存并选择一个人格')
    if value.get('confirmed') is not True:
        raise ValueError('请确认将所选人格与优化目标发送给已配置的AI，可能消耗额度')
    try:
        identity = asyncio.run(store().generate(key, items[key], value.get('goal')))
    except (TimeoutError, RuntimeError):
        return jsonify(ok=False, message='AI生成失败或超时，原人格不变，请稍后重试'), 502
    return jsonify(ok=True, id=identity, message='建议已生成，请审核后应用')


@blueprint.post('/api/persona-evolution/apply')
def apply():
    value = body()
    if value.get('confirmed') is not True:
        raise ValueError('请确认应用建议')
    store().apply(str(value.get('id') or ''), personas())
    return jsonify(ok=True, message='表达风格附加层已应用，基础提示词未改写')


@blueprint.post('/api/persona-evolution/restore')
def restore():
    value = body()
    if value.get('confirmed') is not True or not isinstance(value.get('key'), str):
        raise ValueError('请确认恢复基础人格效果')
    store().restore(value['key'])
    return jsonify(ok=True, message='已移除该人格的进化附加层，原始备份保留')
