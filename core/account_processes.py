"""Manage only owned account panel process trees, never unrelated ports."""
from __future__ import annotations

import atexit
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.request import urlopen

from core.account_workspaces import AccountWorkspaces, port_available


class AccountProcesses:
    def __init__(self, registry: AccountWorkspaces):
        self.registry = registry
        self.processes = {}
        self.lock = threading.RLock()
        atexit.register(self.close)

    def status(self, account_id: str) -> dict:
        account = self.registry.get(account_id)
        process = self.processes.get(account_id)
        running = process is not None and process.poll() is None
        current = account_id == os.getenv("BILI_ACCOUNT_ID")
        return dict(account, running=running or current,
                    status="current" if current else "running" if running else "occupied" if not port_available(account["port"]) else "stopped")

    def start(self, account_id: str) -> dict:
        with self.lock:
            account = self.registry.get(account_id)
            process = self.processes.get(account_id)
            if account_id == os.getenv("BILI_ACCOUNT_ID") or (process is not None and process.poll() is None):
                return self.status(account_id)
            if not port_available(account["port"]):
                raise ValueError("账号端口已占用；不会自动切换端口或接管未知进程")
            workspace = Path(account["workspace"])
            environment = os.environ.copy()
            environment.update(BILI_USER_DATA_DIR=str(workspace), BILI_ACCOUNTS_ROOT=str(self.registry.root),
                               BILI_ACCOUNT_ID=account_id, WEB_PORT=str(account["port"]),
                               WEB_HOST=os.getenv("WEB_HOST", "127.0.0.1"), BILI_WEB_AUTO_OPEN="0",
                               BILI_BOT_AUTO_START="0", BILI_TRAY_DISABLED="1",
                               BILI_DISCLAIMER_SKIP="1", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
                               BILI_BACKUP_DIR=str(workspace / "backups"))
            for key in tuple(environment):
                if key.startswith("BILI_AI_") or key == "BILI_CIPHER_KEY":
                    environment.pop(key)
            project = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
            command = [sys.executable, "--serve"] if getattr(sys, "frozen", False) else [sys.executable, str(project / "web_panel.py")]
            options = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)} if os.name == "nt" else {"start_new_session": True}
            with open(workspace / "Data" / "panel_runtime.log", "ab") as log:
                process = subprocess.Popen(command, cwd=project, env=environment, stdin=subprocess.DEVNULL,
                                           stdout=log, stderr=subprocess.STDOUT, **options)
            self.processes[account_id] = process
            try:
                self._wait_ready(account, process)
            except ValueError:
                self.stop(account_id)
                raise
            return self.status(account_id)

    def _wait_ready(self, account: dict, process) -> None:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                raise ValueError("账号面板启动失败，请查看账号 Data/panel_runtime.log")
            try:
                with urlopen(f"http://127.0.0.1:{account['port']}/api/health", timeout=1) as response:
                    health = json.loads(response.read())
                if health.get('ok') and health.get('account_id') == account['id']:
                    return
            except (OSError, ValueError):
                pass
            time.sleep(0.2)
        raise ValueError("账号面板启动超时，请查看账号 Data/panel_runtime.log")

    def stop(self, account_id: str) -> dict:
        with self.lock:
            self.registry.get(account_id)
            if account_id == os.getenv("BILI_ACCOUNT_ID"):
                raise ValueError("主管理面板不能在此停止，请使用托盘退出")
            process = self.processes.get(account_id)
            if process is not None and process.poll() is None:
                import psutil
                try:
                    parent = psutil.Process(process.pid)
                    descendants = parent.children(recursive=True)
                    for child in reversed(descendants):
                        try:
                            child.terminate()
                        except psutil.NoSuchProcess:
                            pass
                    parent.terminate()
                    _, alive = psutil.wait_procs(descendants + [parent], timeout=5)
                    for child in alive:
                        child.kill()
                    process.wait(timeout=5)
                except psutil.NoSuchProcess:
                    pass
            self.processes.pop(account_id, None)
            return self.status(account_id)

    def restart(self, account_id: str) -> dict:
        with self.lock:
            self.stop(account_id)
            return self.start(account_id)

    def close(self) -> None:
        for account_id in tuple(self.processes):
            try:
                self.stop(account_id)
            except (OSError, ValueError):
                pass
