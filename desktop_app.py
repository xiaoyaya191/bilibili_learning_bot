#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Windows launcher for the local BiliLearn Web control panel."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
import runpy
from pathlib import Path

from utils.system_tray import SystemTray
from utils.web_launcher import get_web_port, is_our_panel

APP_NAME = "BiliLearn"
HOST = "127.0.0.1"
PORT = get_web_port()
URL = f"http://{HOST}:{PORT}"


def _resource_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent


def _is_server_ready() -> bool:
    return is_our_panel(PORT, timeout=1)


def _start_reminder_notifications(tray: SystemTray, stop_event: threading.Event) -> None:
    """Deliver local reminders through the desktop tray without contacting Bilibili."""
    def worker() -> None:
        from services.reminders import take_due
        while not stop_event.wait(10):
            for reminder in take_due():
                tray.notify("BiliLearn 提醒", str(reminder.get("content") or "你有一条待办提醒"))

    threading.Thread(target=worker, name="BiliLearnReminder", daemon=True).start()


def _start_panel_notifications(tray: SystemTray, stop_event: threading.Event) -> None:
    """Relay child-process review and AI alerts through the one desktop tray."""
    def worker() -> None:
        from core.user_data import DATA_DIR
        from utils.desktop_notifications import take_pending
        while not stop_event.wait(0.8):
            for item in take_pending(DATA_DIR):
                tray.notify(item["title"], item["message"])

    threading.Thread(target=worker, name="BiliLearnPanelNotifications", daemon=True).start()


def _is_port_open() -> bool:
    try:
        with socket.create_connection((HOST, PORT), timeout=0.5):
            return True
    except OSError:
        return False


def _configure_child_text_streams() -> None:
    """Prevent non-ASCII logs from crashing a windowed frozen child process."""
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError, ValueError):
            pass


def _serve() -> int:
    resource_dir = _resource_dir()
    os.chdir(resource_dir)
    sys.path.insert(0, str(resource_dir))
    os.environ["WEB_HOST"] = HOST
    os.environ["WEB_PORT"] = str(PORT)
    os.environ["BILI_DISCLAIMER_SKIP"] = "1"
    # The desktop launcher owns browser opening. Avoid a second tab from the
    # panel's normal standalone auto-open behavior.
    os.environ["BILI_WEB_AUTO_OPEN"] = "0"

    from web_panel import main as run_web_panel

    run_web_panel()
    return 0


def _run_bot() -> int:
    """Run the CLI bot within the frozen executable."""
    _configure_child_text_streams()
    os.environ["BILI_DISCLAIMER_SKIP"] = "1"
    os.environ["BILI_TRAY_DISABLED"] = "1"
    from main import main as run_bot
    run_bot()
    return 0


def _run_auxiliary_module(module: str) -> int:
    """Run a bot sub-mode embedded in the frozen application payload."""
    _configure_child_text_streams()
    os.environ["BILI_DISCLAIMER_SKIP"] = "1"
    os.environ["BILI_TRAY_DISABLED"] = "1"
    if module == "brain.monitor":
        os.environ["BILI_MONITOR_SELF_LOG"] = "1"
    runpy.run_module(module, run_name="__main__")
    return 0


def _start_server() -> subprocess.Popen[bytes]:
    environment = os.environ.copy()
    environment["WEB_HOST"] = HOST
    environment["WEB_PORT"] = str(PORT)
    environment["BILI_DISCLAIMER_SKIP"] = "1"
    environment["BILI_WEB_AUTO_OPEN"] = "0"
    environment["BILI_BOT_AUTO_START"] = "0"
    environment["BILI_TRAY_DISABLED"] = "1"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if getattr(sys, "frozen", False):
        command = [sys.executable, "--serve"]
    else:
        command = [sys.executable, str(_resource_dir() / "web_panel.py")]
    return subprocess.Popen(
        command,
        cwd=str(_resource_dir()),
        env=environment,
        creationflags=creation_flags,
    )


def _show_error(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, APP_NAME, 0x10)
    except Exception:
        print(message, file=sys.stderr)


def main() -> int:
    if "--monitor" in sys.argv:
        return _run_auxiliary_module("brain.monitor")
    if "--standby" in sys.argv:
        return _run_auxiliary_module("brain.standby")
    if "--bot" in sys.argv:
        return _run_bot()
    if "--serve" in sys.argv:
        return _serve()

    process: subprocess.Popen[bytes] | None = None
    if _is_server_ready():
        webbrowser.open(URL)
    elif _is_port_open():
        _show_error(f"端口 {PORT} 已被占用，但 BiliLearn Web 面板未响应。请关闭占用程序后重试。")
        return 1
    else:
        process = _start_server()
        for _ in range(30):
            if _is_server_ready():
                webbrowser.open(URL)
                break
            if process.poll() is not None:
                _show_error("BiliLearn Web 面板启动失败，请检查项目依赖和日志。")
                return process.returncode or 1
            time.sleep(0.5)
        else:
            _show_error(f"BiliLearn Web 面板未在 15 秒内启动。请访问 {URL} 或检查日志。")
            return 1

    reminder_stop = threading.Event()

    def _exit_desktop() -> None:
        reminder_stop.set()
        if process is not None and process.poll() is None:
            process.terminate()

    tray = SystemTray(URL, on_exit=_exit_desktop)
    _start_reminder_notifications(tray, reminder_stop)
    _start_panel_notifications(tray, reminder_stop)
    if tray.run():
        return 0
    _show_error("系统托盘无法启动。请安装 pystray 后重试。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
