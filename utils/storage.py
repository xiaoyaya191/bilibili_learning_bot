#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
json_utils.py — 线程安全的 JSON 文件读写工具
替换散落在各处的裸 json.load/json.dump，统一加锁防止并发写入文件损坏。
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
from pathlib import Path
from typing import Any, Optional


class JsonStore:
    """线程安全的 JSON 文件读写器。每个文件一个实例，自动管理路径和锁。"""

    def __init__(self, path: Path | str):
        if isinstance(path, str):
            path = Path(path)
        self._path = path
        self._lock = threading.Lock()

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()

    def read(self, default: Any = None) -> Any:
        """读取 JSON 文件。不存在或损坏时返回 default。"""
        with self._lock:
            try:
                if self._path.exists():
                    return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError, UnicodeDecodeError) as e:
                import sys
                print(f"[JSON] 读取失败 {self._path.name}: {e}", file=sys.stderr, flush=True)
        return default if default is not None else {}

    def write(self, data: Any) -> bool:
        """原子写入 JSON（先写临时文件再重命名）。"""
        with self._lock:
            try:
                self._path.parent.mkdir(parents=True, exist_ok=True)
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(self._path)
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
                tmp = self._path.with_suffix(".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
                tmp.replace(self._path)
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
    "api_key", "unified_api_key", "vision_api_key",
    "password", "access_token", "refresh_token",
    "sessdata", "bili_jct", "dedeuserid", "DedeUserID",
}

def sanitize_export(data: Any) -> Any:
    """递归脱敏：将敏感字段替换为 '[已隐藏]'。
    用于导出配置时防止 API Key 泄露。
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            if key.lower() in SENSITIVE_KEYS:
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
    if sys.platform == 'win32':
        return Path("C:/bilibili_claw_backup")
    # Android (Termux) 检测：使用共享存储，方便文件管理器访问/跨实例迁移
    android_storage = Path("/storage/emulated/0")
    if android_storage.exists():
        return android_storage / "bilibili_claw_backup"
    return Path.home() / "bilibili_claw_backup"
