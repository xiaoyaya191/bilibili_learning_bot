#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
账号数据统一存储：SQLite 文档数据库 + 旧 JSON 兼容镜像。
Data 目录和已登记账号目录的共享读写使用事务、WAL及原始迁移快照；其他路径保持JSON行为。
同时提供 API Key 脱敏工具函数。

用法:
    from utils.storage import JsonStore
    store = JsonStore("/path/to/file.json")
    data = store.read()
    store.write(data)
"""

import json
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Optional


class JsonStore:
    """兼容历史接口的账号数据读写器，管理目录内使用SQLite事务。"""

    def __init__(self, path: Path | str):
        if isinstance(path, str):
            path = Path(path)
        self._path = path
        self._lock = threading.Lock()

    @staticmethod
    def _atomic_dump(data: Any, tmp: Path, target: Path) -> None:
        """写临时文件并替换目标；Windows 下文件被占用时短暂重试。"""
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        last_err: Exception | None = None
        for attempt in range(4):
            try:
                tmp.replace(target)
                return
            except PermissionError as exc:
                last_err = exc
                time.sleep(0.12 * (attempt + 1))
        raise last_err  # type: ignore[misc]

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        from utils.database import DocumentDatabase, managed
        if managed(self._path):
            return DocumentDatabase(self._path.parent).exists(self._path.name)
        return self._path.exists()

    @staticmethod
    def _mirror(data, path):
        temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            JsonStore._atomic_dump(data, temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self, default: Any = None) -> Any:
        """读取 JSON 文件。不存在或损坏时返回 default。"""
        with self._lock:
            try:
                from utils.database import DocumentDatabase, managed
                if managed(self._path):
                    return DocumentDatabase(self._path.parent).read(self._path.name, default if default is not None else {})
                if self._path.exists():
                    # utf-8-sig：兼容带 BOM 的文件（记事本/PowerShell 默认 UTF-8 BOM），
                    # 无 BOM 文件同样可读，避免用户手改配置后静默丢失。
                    return json.loads(self._path.read_text(encoding="utf-8-sig"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                import sys
                print(f"[JSON] 读取失败 {self._path.name}: {e}", file=sys.stderr, flush=True)
        return default if default is not None else {}

    def write(self, data: Any) -> bool:
        """原子写入 JSON（先写临时文件再重命名）。"""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                from utils.database import DocumentDatabase, managed
                if managed(self._path):
                    DocumentDatabase(self._path.parent).write(self._path.name, data, self._mirror)
                else:
                    self._mirror(data, self._path)
                return True
            except Exception as e:
                import sys
                print(f"[JSON] 写入失败 {self._path.name}: {e}", file=sys.stderr, flush=True)
                return False

    def update(self, mutator) -> bool:
        """原子读-改-写（在读锁内完成，防止并发竞争）。
        mutator 是一个接受 data dict 并就地修改的函数。
        """
        with self._lock:
            from utils.database import DocumentDatabase, managed
            if managed(self._path):
                try:
                    DocumentDatabase(self._path.parent).update(self._path.name, mutator, self._mirror)
                    return True
                except Exception as error:
                    import sys
                    print(f"[SQLite] update失败 {self._path.name}: {error}", file=sys.stderr, flush=True)
                    return False
            data = {}
            try:
                if self._path.exists():
                    data = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = {}
            try:
                mutator(data)
            except Exception as e:
                import sys
                print(f"[JSON] update 回调异常 {self._path.name}: {e}", file=sys.stderr, flush=True)
                return False
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                self._atomic_dump(data, self._path.with_suffix(".tmp"), self._path)
                return True
            except Exception as e:
                import sys
                print(f"[JSON] update 写入失败 {self._path.name}: {e}", file=sys.stderr, flush=True)
                return False

    def stat(self) -> dict:
        """获取文件状态信息。"""
        if not self._path.exists():
            return {"exists": False, "size": 0, "mtime": None, "size_fmt": "0 B"}
        s = self._path.stat()
        sz = s.st_size
        from datetime import datetime
        return {
            "exists": True,
            "size": sz,
            "mtime": datetime.fromtimestamp(s.st_mtime).strftime("%m-%d %H:%M"),
            "size_fmt": f"{sz/1024:.1f}K" if sz < 1024*1024 else f"{sz/1048576:.2f}M",
        }


# ── API Key 脱敏 ──
SENSITIVE_KEYS = {
    "api_key", "unified_api_key", "vision_api_key", "headers",
    "password", "recovery_code", "recovery_answer", "access_token", "refresh_token",
    "sessdata", "bili_jct", "dedeuserid", "DedeUserID",
}

def sanitize_export(data: Any) -> Any:
    """递归脱敏：将非空敏感字段替换为 '[已隐藏]'。
    用于导出配置/面板下发配置时防止 API Key、密码哈希等泄露。
    空值不脱敏，避免"未配置"被误显示为"已隐藏"。
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key.lower() in SENSITIVE_KEYS and value not in ("", None):
                result[key] = "[已隐藏]"
            elif isinstance(value, (dict, list)):
                result[key] = sanitize_export(value)
            else:
                result[key] = value
        return result
    elif isinstance(data, list):
        return [sanitize_export(item) for item in data]
    return data


def sanitize_config_for_export(config: dict) -> dict:
    """对配置对象做导出脱敏，保留结构但隐藏敏感值。"""
    return sanitize_export(config)



HIDDEN_PLACEHOLDER = "[已隐藏]"


def is_hidden_placeholder(value) -> bool:
    """判断是否为脱敏占位符（导出时写入的 '[已隐藏]'）。"""
    return value == HIDDEN_PLACEHOLDER


def strip_hidden_placeholders(obj, existing=None):
    """递归移除导入数据中的 '[已隐藏]' 脱敏占位符。

    导出配置时敏感字段会被替换为 '[已隐藏]'；如果直接导入会覆盖真实配置，
    导致 API Key / Cookie 变成无效占位符。导入时应：
    - 目标文件已有有效值时：保留现有值；
    - 目标文件没有值时：删除该字段（缺失字段按空值处理，等待用户重新填写）。
    """
    if isinstance(obj, dict):
        result = {}
        for key, value in obj.items():
            if value == "[已隐藏]":
                if isinstance(existing, dict) and existing.get(key) not in (None, "", "[已隐藏]"):
                    result[key] = existing[key]
                continue
            if isinstance(value, (dict, list)):
                existing_child = existing.get(key) if isinstance(existing, dict) else None
                result[key] = strip_hidden_placeholders(value, existing_child)
            else:
                result[key] = value
        return result
    if isinstance(obj, list):
        previous = {item.get("id"): item for item in existing or [] if isinstance(item, dict) and item.get("id")} if isinstance(existing, list) else {}
        return [strip_hidden_placeholders(item, previous.get(item.get("id")) if isinstance(item, dict) else None) for item in obj if item != "[已隐藏]"]
    return obj



# ── 路径安全校验 ──
def is_safe_path(filepath: Path | str, base_dir: Path | str) -> bool:
    """检查 filepath 是否在 base_dir 目录树内（防路径穿越）。
    
    Returns:
        True 如果 filepath 解析后的真实路径在 base_dir 下，且不包含 '..' 组件。
    """
    if isinstance(filepath, str):
        filepath = Path(filepath)
    if isinstance(base_dir, str):
        base_dir = Path(base_dir)
    
    # 拒绝包含路径穿越组件的字符串
    fname = str(filepath)
    if ".." in fname.split("/") + fname.split("\\"):
        return False
    
    try:
        resolved = (base_dir / filepath).resolve()
        base_resolved = base_dir.resolve()
        return str(resolved).startswith(str(base_resolved) + os.sep) or resolved == base_resolved
    except (ValueError, OSError):
        return False


# ── 平台无关备份目录 ──
def get_backup_dir() -> Path:
    """获取平台无关的备份目录。
    Windows → C:\\bilibili_claw_backup
    Android/Termux → /storage/emulated/0/bilibili_claw_backup (共享存储，文件管理器可见)
    其他 → ~/bilibili_claw_backup
    """
    import sys
    if os.getenv("BILI_ACCOUNT_ID"):
        return Path(os.environ["BILI_USER_DATA_DIR"]) / "backups"
    custom_dir = os.getenv("BILI_BACKUP_DIR", "").strip()
    if custom_dir:
        return Path(custom_dir).expanduser()
    if sys.platform == 'win32':
        return Path.home() / "bilibili_claw_backup"
    # Android (Termux) 检测：使用共享存储，方便文件管理器访问/跨实例迁移
    android_storage = Path("/storage/emulated/0")
    if android_storage.exists():
        return android_storage / "bilibili_claw_backup"
    return Path.home() / "bilibili_claw_backup"
