"""Authenticated account management routes on the primary panel."""
import os
import threading
from pathlib import Path

from flask import jsonify, render_template, request

from core.account_processes import AccountProcesses
from core.account_workspaces import AccountWorkspaces, MAX_ACCOUNTS


class AccountWeb:
    def __init__(self):
        self.manager = None
        self.lock = threading.RLock()

    def get_manager(self):
        if self.manager is None:
            registry = AccountWorkspaces()
            if not registry.index.exists():
                raise ValueError("请重启面板以初始化多账号工作空间")
            self.manager = AccountProcesses(registry)
        return self.manager

    def register(self, app):
        @app.route('/api/accounts/context')
        def accounts_context():
            current_id = os.getenv('BILI_ACCOUNT_ID', '')
            try:
                registry = self.get_manager().registry
                primary = registry.get('account-001')
                return jsonify(ok=True, current_account_id=current_id,
                               is_primary=current_id == 'account-001', primary_port=primary['port'])
            except (ValueError, OSError, RuntimeError) as exc:
                return jsonify(ok=False, message=str(exc)), 400

        @app.route('/accounts')
        def accounts_page():
            return render_template('accounts.html', embedded=request.args.get('embedded') == '1')

        @app.route('/api/accounts', methods=['GET', 'POST'])
        @app.route('/api/accounts/<account_id>', methods=['PATCH', 'DELETE'])
        @app.route('/api/accounts/<account_id>/<action>', methods=['POST'])
        def accounts_api(account_id=None, action=None):
            if os.getenv('BILI_ACCOUNT_ID') != 'account-001':
                return jsonify(ok=False, message='请从主账号面板管理账号'), 403
            try:
                with self.lock:
                    manager = self.get_manager()
                    registry = manager.registry
                    body = request.get_json(silent=True) or {}
                    if not isinstance(body, dict):
                        raise ValueError('请求必须为 JSON 对象')
                    if request.method == 'GET':
                        return jsonify(ok=True, max_accounts=MAX_ACCOUNTS,
                                       current_account_id=os.getenv('BILI_ACCOUNT_ID'),
                                       accounts=[manager.status(item['id']) for item in registry.list()])
                    if request.method == 'DELETE':
                        if body.get('confirmation') != account_id:
                            raise ValueError('请输入账号 ID 二次确认删除')
                        status = manager.status(account_id)
                        if status['running'] or status['status'] == 'occupied':
                            raise ValueError('请先停止账号面板；未知占用进程不能安全删除')
                        return jsonify(ok=True, backup=registry.delete(account_id, body['confirmation']))
                    if request.method == 'PATCH':
                        status = manager.status(account_id)
                        if body.get('port') is not None and (status['running'] or status['status'] == 'occupied'):
                            raise ValueError('请先停止账号再修改端口')
                        return jsonify(ok=True, account=registry.update(account_id, body.get('name'), body.get('port')))
                    if account_id is None:
                        return jsonify(ok=True, account=registry.create(body.get('name', ''), body.get('port')))
                    if action not in ('start', 'stop', 'restart', 'open'):
                        raise ValueError('不支持的账号操作')
                    status = manager.start(account_id) if action == 'open' else getattr(manager, action)(account_id)
                    return jsonify(ok=True, account=status, port=status['port'])
            except (ValueError, OSError, RuntimeError) as exc:
                return jsonify(ok=False, message=str(exc)), 400


account_web = AccountWeb()
