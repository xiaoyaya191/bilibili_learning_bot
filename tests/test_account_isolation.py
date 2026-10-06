import json
import os
import subprocess
import sys
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


def test_source_account_paths_and_cookies_are_fully_isolated(tmp_path):
    script = """
import json
from pathlib import Path
from core import user_data, config
from services.document_export import _resolve_out_dir
from services.mindmap_export import export_mindmap
from utils.storage import get_backup_dir
import web_panel
paths = [user_data.DATA_DIR, user_data.KNOWLEDGE_BASE_DIR, user_data.HIGHLIGHTS_DIR,
         user_data.HTML_EXPORTS_DIR, user_data.MINDMAPS_DIR, user_data.WORD_DIR,
         config.COOKIE_FILE, config.BOT_LOCK_FILE, config.PRIVATE_CONTEXT_FILE,
         config.CIPHER_KEY_FILE, get_backup_dir(), _resolve_out_dir('/outside')]
config_result = config.resolve_knowledge_base_dir({'knowledge_base_dir': '/outside'})
assert Path(config_result) == user_data.KNOWLEDGE_BASE_DIR
assert all(Path(path).resolve().is_relative_to(user_data.USER_DATA_DIR.resolve()) for path in paths)
assert not (user_data.DATA_DIR / 'bilibili_cookies.json').exists()
print('ISOLATED:' + web_panel.app.config['SESSION_COOKIE_NAME'])
"""
    for number in (1, 2):
        account_id = f'account-{number:03d}'
        environment = os.environ.copy()
        environment.update(BILI_ACCOUNT_ID=account_id, BILI_USER_DATA_DIR=str(tmp_path / account_id))
        result = subprocess.run([sys.executable, '-c', script], cwd=PROJECT, env=environment,
                                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
        assert result.returncode == 0, result.stdout + result.stderr
        assert 'ISOLATED:bililearn_' + account_id in result.stdout


def test_account_panel_processes_start_and_stop_independently(tmp_path, monkeypatch):
    import socket
    import time
    from urllib.request import urlopen
    from core.account_workspaces import AccountWorkspaces
    from core.account_processes import AccountProcesses

    def free_port():
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            return probe.getsockname()[1]

    monkeypatch.delenv('BILI_ACCOUNT_ID', raising=False)
    monkeypatch.setenv('WEB_HOST', '127.0.0.1')
    registry = AccountWorkspaces(tmp_path)
    first = registry.create('first', free_port())
    second_port = free_port()
    while second_port == first['port']:
        second_port = free_port()
    second = registry.create('second', second_port)
    manager = AccountProcesses(registry)

    def health(account):
        with urlopen(f"http://127.0.0.1:{account['port']}/api/health", timeout=2) as response:
            return json.loads(response.read())

    def wait_ready(account):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            try:
                result = health(account)
                assert result['account_id'] == account['id']
                return
            except OSError:
                time.sleep(0.2)
        raise AssertionError((Path(account['workspace']) / 'Data' / 'panel_runtime.log').read_text(encoding='utf-8', errors='replace'))

    try:
        manager.start(first['id'])
        manager.start(second['id'])
        wait_ready(first)
        wait_ready(second)
        assert first['port'] != second['port']
        manager.restart(first['id'])
        wait_ready(first)
        manager.stop(first['id'])
        assert health(second)['account_id'] == second['id']
        assert manager.processes[second['id']].poll() is None
    finally:
        manager.close()
