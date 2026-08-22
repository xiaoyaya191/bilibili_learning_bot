"""Shared web-panel port selection, health checks, and browser startup."""
from __future__ import annotations

import json
import os
import socket
import time
import urllib.error
import urllib.request
import webbrowser


DEFAULT_WEB_PORT = 18083
WEB_SERVICE_ID = "bilibili-learning-bot-web"


def get_web_port() -> int:
    """Return a validated WEB_PORT, falling back to the project default.

    优先级: 环境变量 WEB_PORT > config.json web.port > 默认端口。
    """
    raw = os.getenv("WEB_PORT", "").strip()
    if not raw:
        # [P1-7] 自定义端口：从 config.json 的 web.port 读取（延迟导入避免循环依赖）
        try:
            import json as _json
            from core.config import CONFIG_FILE as _CONFIG_FILE
            if os.path.exists(_CONFIG_FILE):
                with open(_CONFIG_FILE, "r", encoding="utf-8-sig") as f:
                    _cfg = _json.load(f)
                raw = str((_cfg.get("web", {}) or {}).get("port") or "").strip()
        except Exception:
            raw = ""
    if not raw:
        raw = str(DEFAULT_WEB_PORT)
    try:
        port = int(raw)
    except ValueError:
        return DEFAULT_WEB_PORT
    return port if 1024 <= port <= 65535 else DEFAULT_WEB_PORT


def panel_url(port: int) -> str:
    return f"http://127.0.0.1:{port}"


def is_port_open(port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def is_our_panel(port: int, timeout: float = 1.0) -> bool:
    """Distinguish this panel from unrelated processes occupying the port."""
    request = urllib.request.Request(
        f"{panel_url(port)}/api/health",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, urllib.error.URLError):
        return False
    return payload.get("ok") is True and payload.get("service") == WEB_SERVICE_ID


def find_available_port(preferred: int, attempts: int = 20) -> int:
    """Return the preferred port or a nearby free port without disturbing its owner."""
    for port in range(preferred, min(65536, preferred + max(1, attempts))):
        if not is_port_open(port):
            return port
    raise RuntimeError(f"端口 {preferred}-{preferred + attempts - 1} 均被占用")


def open_browser_when_ready(port: int, timeout: float = 20.0) -> bool:
    """Wait for the real panel health endpoint before opening the browser."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_our_panel(port):
            return bool(webbrowser.open(panel_url(port)))
        time.sleep(0.25)
    return False
