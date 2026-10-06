"""Independent account registry, storage, migration and port allocation."""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import sys
import tempfile
import threading
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

MAX_ACCOUNTS = 10
DEFAULT_PORT = 18083
DIRECTORIES = ("Data", "KnowledgeBase", "html_exports", "MindMaps", "Word", "highlights", "qr_codes")
_THREAD_LOCK = threading.RLock()


def account_root() -> Path:
    override = os.getenv("BILI_ACCOUNTS_ROOT", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    explicit = os.getenv("BILI_USER_DATA_DIR", "").strip()
    if explicit and not os.getenv("BILI_ACCOUNT_ID"):
        return Path(explicit).expanduser().resolve()
    default = Path(os.getenv("LOCALAPPDATA", str(Path.home() / "AppData" / "Local"))) / "BiliLearn"
    try:
        pointer = json.loads((default / "Data" / "storage_location.json").read_text(encoding="utf-8-sig"))
        target = Path(pointer["path"]).expanduser().resolve() if pointer.get("path") else default.resolve()
        return target if target != target.parent and len(str(target)) > 3 else default.resolve()
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return default.resolve()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def port_available(port: int) -> bool:
    try:
        with socket.socket() as probe:
            if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            elif os.name != "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            probe.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False


class AccountWorkspaces:
    def __init__(self, root: Path | str | None = None):
        self.root = Path(root if root is not None else account_root()).resolve()
        self.index = self.root / "accounts.json"

    @contextmanager
    def locked(self):
        self.root.mkdir(parents=True, exist_ok=True)
        with _THREAD_LOCK, open(self.root / ".accounts.lock", "a+b") as stream:
            stream.seek(0, 2)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + 10
            while True:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise RuntimeError("账号索引正在使用，请稍后重试")
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

    def workspace(self, account_id: str) -> Path:
        if not re.fullmatch(r"account-00[1-9]|account-010", account_id):
            raise ValueError("无效账号 ID")
        base = (self.root / "accounts").resolve()
        if not base.is_relative_to(self.root):
            raise ValueError("账号目录不能指向存储根目录之外")
        target = (base / account_id).resolve()
        if target.parent != base:
            raise ValueError("账号工作空间越界")
        return target

    def _read(self) -> dict:
        if not self.index.exists():
            return {"version": 1, "accounts": []}
        try:
            value = json.loads(self.index.read_text(encoding="utf-8-sig"))
            accounts = value["accounts"]
            if not isinstance(accounts, list) or len(accounts) > MAX_ACCOUNTS:
                raise ValueError()
            ids, ports = set(), set()
            for account in accounts:
                self.workspace(account["id"])
                port = self._port(account["port"])
                if account["id"] in ids or port in ports:
                    raise ValueError()
                ids.add(account["id"])
                ports.add(port)
            if accounts and "account-001" not in ids:
                raise ValueError()
            return value
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ValueError("accounts.json 损坏，请从备份恢复；未覆盖原文件") from exc

    @staticmethod
    def _port(value) -> int:
        if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
            raise ValueError("端口必须是整数")
        port = int(value)
        if not 1024 <= port <= 65535:
            raise ValueError("端口必须在 1024–65535 之间")
        return port

    def list(self) -> list[dict]:
        with self.locked():
            return [dict(account, workspace=str(self.workspace(account["id"]))) for account in self._read()["accounts"]]

    def get(self, account_id: str) -> dict:
        self.workspace(account_id)
        for account in self.list():
            if account["id"] == account_id:
                return account
        raise ValueError("账号不存在")

    def _create(self, value: dict, name: str, port=None, persist=True) -> dict:
        accounts = value["accounts"]
        if len(accounts) >= MAX_ACCOUNTS:
            raise ValueError("最多支持 10 个账号")
        name = str(name).strip()
        if not name or len(name) > 80:
            raise ValueError("账号名称须为 1–80 个字符")
        used_ports = {account["port"] for account in accounts}
        if port is None:
            port = next((candidate for candidate in range(DEFAULT_PORT, 65536)
                         if candidate not in used_ports and port_available(candidate)), None)
            if port is None:
                raise ValueError("没有可用端口")
        port = self._port(port)
        if port in used_ports or not port_available(port):
            raise ValueError("端口已被账号或其他程序占用")
        account_id = next(f"account-{number:03d}" for number in range(1, MAX_ACCOUNTS + 1)
                          if all(account["id"] != f"account-{number:03d}" for account in accounts))
        workspace = self.workspace(account_id)
        if workspace.exists() and any(workspace.iterdir()):
            raise ValueError("目标工作空间已存在数据，请先恢复或备份处理")
        account = {"id": account_id, "name": name, "port": port, "created_at": datetime.now().isoformat(timespec="seconds")}
        try:
            for directory in DIRECTORIES:
                (workspace / directory).mkdir(parents=True, exist_ok=True)
            atomic_json(workspace / "Data" / "config.json", {"web": {"port": port}})
            accounts.append(account)
            if persist:
                atomic_json(self.index, value)
        except Exception:
            if workspace.exists():
                shutil.rmtree(workspace)
            raise
        return dict(account, workspace=str(workspace))

    def create(self, name: str, port=None) -> dict:
        with self.locked():
            return self._create(self._read(), name, port)

    def update(self, account_id: str, name: str | None = None, port=None) -> dict:
        with self.locked():
            value = self._read()
            account = next((item for item in value["accounts"] if item["id"] == account_id), None)
            if account is None:
                raise ValueError("账号不存在")
            if name is not None:
                name = str(name).strip()
                if not name or len(name) > 80:
                    raise ValueError("账号名称须为 1–80 个字符")
                account["name"] = name
            if port is not None:
                port = self._port(port)
                if port != account["port"]:
                    if any(item["port"] == port for item in value["accounts"]) or not port_available(port):
                        raise ValueError("端口已被占用")
                    account["port"] = port
                    config_path = self.workspace(account_id) / "Data" / "config.json"
                    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
                    config.setdefault("web", {})["port"] = port
                    atomic_json(config_path, config)
            atomic_json(self.index, value)
            return dict(account, workspace=str(self.workspace(account_id)))

    def delete(self, account_id: str, confirmation: str) -> str:
        with self.locked():
            value = self._read()
            if confirmation != account_id:
                raise ValueError("请输入账号 ID 二次确认删除")
            if account_id == "account-001":
                raise ValueError("主管理账号不能删除")
            if not any(item["id"] == account_id for item in value["accounts"]):
                raise ValueError("账号不存在")
            workspace = self.workspace(account_id)
            backup_dir = self.root / "backups"
            backup_dir.mkdir(exist_ok=True)
            backup = shutil.make_archive(str(backup_dir / f"{account_id}-{time.time_ns()}"), "zip", workspace)
            shutil.rmtree(workspace)
            value["accounts"] = [item for item in value["accounts"] if item["id"] != account_id]
            atomic_json(self.index, value)
            return backup

    def ensure_default(self, project_dir: Path, preferred_port=None) -> dict:
        with self.locked():
            value = self._read()
            if value["accounts"]:
                return next(dict(item, workspace=str(self.workspace(item["id"])))
                            for item in value["accounts"] if item["id"] == "account-001")
            legacy = self.root / "Data"
            sources = [(legacy, "Data")]
            for directory in DIRECTORIES[1:]:
                source = self.root / directory
                project_source = project_dir / directory
                if directory != 'qr_codes' and not getattr(sys, 'frozen', False) and project_source.exists():
                    source = project_source
                elif not source.exists():
                    source = project_dir / directory
                sources.append((source, directory))
            for filename in (".cipher_key", "bot_memory.json", "bot_journal.md", "knowledge_metadata.json", "learning_log.md"):
                sources.append((self.root / filename, filename))
            if not legacy.exists() and (project_dir / "Data").exists():
                sources[0] = (project_dir / "Data", "Data")
            backup = self.root / "backups" / f"legacy-{time.time_ns()}"
            for source, name in sources:
                if source.exists():
                    destination = backup / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if source.is_dir():
                        shutil.copytree(source, destination)
                    else:
                        shutil.copy2(source, destination)
            legacy_config_path = sources[0][0] / "config.json"
            if legacy_config_path.exists():
                legacy_config = json.loads(legacy_config_path.read_text(encoding="utf-8-sig"))
                custom_paths = {
                    "KnowledgeBase": legacy_config.get("knowledge_base_dir") or (legacy_config.get("knowledge") or {}).get("base_dir"),
                    "MindMaps": (legacy_config.get("mindmap") or {}).get("output_dir"),
                    "Word": (legacy_config.get("document_export") or {}).get("output_dir"),
                }
                for directory, custom in custom_paths.items():
                    if not custom:
                        continue
                    custom_path = Path(custom).expanduser()
                    if not custom_path.is_absolute():
                        custom_path = project_dir / custom_path
                    custom_path = custom_path.resolve()
                    if custom_path == custom_path.parent:
                        raise ValueError("旧配置导出目录不能是磁盘根目录")
                    if backup.resolve().is_relative_to(custom_path):
                        raise ValueError("旧配置导出目录包含备份目标，请先调整旧目录配置")
                    if custom_path.is_dir():
                        shutil.copytree(custom_path, backup / directory, dirs_exist_ok=True)
            account = self._create(value, "主账号", preferred_port, persist=False)
            workspace = Path(account["workspace"])
            try:
                for source in backup.iterdir() if backup.exists() else []:
                    destination = workspace / source.name
                    if source.is_dir():
                        shutil.copytree(source, destination, dirs_exist_ok=True)
                    else:
                        shutil.copy2(source, destination)
                config_path = workspace / "Data" / "config.json"
                config = json.loads(config_path.read_text(encoding="utf-8-sig"))
                config.setdefault("web", {})["port"] = account["port"]
                config.pop("knowledge_base_dir", None)
                if isinstance(config.get("knowledge"), dict):
                    config["knowledge"].pop("base_dir", None)
                if isinstance(config.get("mindmap"), dict):
                    config["mindmap"]["output_dir"] = str(workspace / "MindMaps")
                atomic_json(config_path, config)
                atomic_json(self.index, value)
            except Exception:
                atomic_json(self.index, {"version": 1, "accounts": []})
                shutil.rmtree(workspace)
                raise
            return account


def configure_default_account() -> dict:
    registry = AccountWorkspaces()
    project = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    preferred = os.getenv("WEB_PORT", "").strip() or None
    if preferred is None:
        config_path = registry.root / "Data" / "config.json"
        if config_path.exists():
            preferred = json.loads(config_path.read_text(encoding="utf-8-sig")).get("web", {}).get("port")
    account = registry.ensure_default(project, preferred)
    os.environ.update(BILI_ACCOUNTS_ROOT=str(registry.root), BILI_ACCOUNT_ID=account["id"],
                      BILI_USER_DATA_DIR=account["workspace"], WEB_PORT=str(account["port"]),
                      BILI_BACKUP_DIR=str(Path(account["workspace"]) / "backups"))
    return account
