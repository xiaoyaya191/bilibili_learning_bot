import os
from pathlib import Path

import pytest

from core.account_workspaces import AccountWorkspaces
from core.account_processes import AccountProcesses


@pytest.fixture
def manager(tmp_path, monkeypatch):
    monkeypatch.setattr('core.account_workspaces.port_available', lambda port: True)
    monkeypatch.setattr('core.account_processes.port_available', lambda port: True)
    registry = AccountWorkspaces(tmp_path)
    registry.create('主账号')
    registry.create('副账号')
    monkeypatch.setenv('BILI_ACCOUNT_ID', 'account-001')
    instance = AccountProcesses(registry)
    yield instance
    instance.processes.clear()


def test_start_passes_independent_environment(manager, monkeypatch):
    captured = {}
    class Process:
        def poll(self):
            return None
    def popen(command, **kwargs):
        captured.update(kwargs)
        captured['command'] = command
        return Process()
    monkeypatch.setattr('core.account_processes.subprocess.Popen', popen)
    monkeypatch.setattr(manager, '_wait_ready', lambda account, process: None)
    monkeypatch.setenv('BILI_AI_API_KEY', 'main-secret')
    monkeypatch.setenv('BILI_CIPHER_KEY', 'main-cipher')
    result = manager.start('account-002')
    environment = captured['env']
    assert environment['BILI_ACCOUNT_ID'] == 'account-002'
    assert environment['WEB_PORT'] == '18084'
    assert environment['BILI_USER_DATA_DIR'] == str(manager.registry.workspace('account-002'))
    assert environment['BILI_WEB_AUTO_OPEN'] == '0'
    assert 'BILI_AI_API_KEY' not in environment
    assert 'BILI_CIPHER_KEY' not in environment
    assert result['running'] is True
    assert Path(environment['BILI_BACKUP_DIR']).parent == manager.registry.workspace('account-002')


def test_unknown_occupied_port_is_not_adopted(manager, monkeypatch):
    monkeypatch.setattr('core.account_processes.port_available', lambda port: False)
    with pytest.raises(ValueError, match='占用'):
        manager.start('account-002')
    assert not manager.processes


def test_cannot_stop_primary(manager):
    with pytest.raises(ValueError, match='不能'):
        manager.stop('account-001')


def test_stop_targets_only_owned_tree(manager, monkeypatch):
    import psutil
    events = []
    class Owned:
        pid = 12345
        def poll(self):
            return None
        def wait(self, timeout):
            events.append('wait')
    class Tree:
        def __init__(self, pid=None):
            self.pid = pid
        def children(self, recursive):
            return [Tree(12346)]
        def terminate(self):
            events.append(self.pid)
    manager.processes['account-002'] = Owned()
    unrelated = object()
    manager.processes['account-003'] = unrelated
    monkeypatch.setattr(psutil, 'Process', Tree)
    monkeypatch.setattr(psutil, 'wait_procs', lambda processes, timeout: (processes, []))
    manager.stop('account-002')
    assert events == [12346, 12345, 'wait']
    assert manager.processes['account-003'] is unrelated


def test_restart_stops_then_starts(manager, monkeypatch):
    calls = []
    monkeypatch.setattr(manager, 'stop', lambda account_id: calls.append(('stop', account_id)))
    monkeypatch.setattr(manager, 'start', lambda account_id: calls.append(('start', account_id)) or {})
    manager.restart('account-002')
    assert calls == [('stop', 'account-002'), ('start', 'account-002')]
