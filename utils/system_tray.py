"""Small optional Windows system-tray integration for the local project."""
from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from collections.abc import Callable
from typing import Any


TRAY_OWNER_MUTEX_NAME = "BiliLearn_Tray_Owner_v1"
_tray_owner_mutex = None


def acquire_tray_ownership() -> bool:
    """[N1] 全项目托盘所有权：Windows 命名互斥体保证同一时刻只有一个进程显示托盘。

    desktop_app.exe / web_panel.py / main.py 三个入口创建托盘前都要先抢这把锁，
    抢不到说明别的实例已经在显示托盘，本进程直接跳过，从根本上避免出现两个图标。
    非 Windows 平台恒返回 True（Termux 等环境由各自开关控制）。
    """
    global _tray_owner_mutex
    if os.name != "nt":
        return True
    if _tray_owner_mutex is not None:
        # 本进程已持有所有权（可重入）：直接放行
        return True
    try:
        import ctypes

        # [FIX] 必须用 use_last_error=True 的 WinDLL + ctypes.get_last_error()。
        # 之前用 ctypes.windll.kernel32.GetLastError() 会被中间调用污染，
        # 偶发检测失效 → 两个进程同时创建托盘图标（双图标问题根因）。
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        handle = kernel32.CreateMutexW(None, False, TRAY_OWNER_MUTEX_NAME)
        if not handle:
            return True
        err = ctypes.get_last_error()
        if err == 183:  # ERROR_ALREADY_EXISTS：已有实例持有托盘
            kernel32.CloseHandle(handle)
            return False
        _tray_owner_mutex = handle
        return True
    except Exception:
        return True


def release_tray_ownership() -> None:
    """主动释放托盘所有权（进程退出或隐藏托盘时调用，便于下一次启动立即抢到锁）。"""
    global _tray_owner_mutex
    handle = _tray_owner_mutex
    _tray_owner_mutex = None
    if handle is None or os.name != "nt":
        return
    try:
        import ctypes

        ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle(handle)
    except Exception:
        pass


OFFICIAL_SITE_URL = "https://bxya.top"
ISSUES_URL = "https://github.com/xiaoyaya191/bilibili_learning_bot/issues"
REPOSITORY_URL = "https://github.com/xiaoyaya191/bilibili_learning_bot"


class SystemTray:
    """Keep project shortcuts available without making pystray a hard dependency."""

    def __init__(self, panel_url: str, on_exit: Callable[[], None] | None = None,
                 on_show_panel: Callable[[], None] | None = None) -> None:
        self.panel_url = panel_url
        self.on_exit = on_exit
        self.on_show_panel = on_show_panel
        self._icon: Any | None = None
        self.last_error = ""

    @staticmethod
    def _image():
        from PIL import Image, ImageDraw

        project_icon = Path(__file__).resolve().parents[1] / "app-icons" / "7de15f3bb6e5ac30291e48bc3f15e23f.png"
        if project_icon.exists():
            try:
                image = Image.open(project_icon).convert("RGBA")
                image.thumbnail((64, 64), Image.Resampling.LANCZOS)
                canvas = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                canvas.alpha_composite(image, ((64 - image.width) // 2, (64 - image.height) // 2))
                return canvas
            except (OSError, ValueError):
                pass

        image = Image.new("RGBA", (64, 64), (24, 32, 44, 255))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((8, 8, 56, 56), radius=13, fill=(27, 145, 201, 255))
        draw.rectangle((22, 20, 42, 38), fill=(255, 255, 255, 255))
        draw.rectangle((26, 24, 38, 28), fill=(27, 145, 201, 255))
        draw.rectangle((26, 32, 34, 36), fill=(27, 145, 201, 255))
        return image

    @staticmethod
    def _open(url: str) -> None:
        webbrowser.open(url, new=2)

    def _show_panel(self, _icon=None, _item=None) -> None:
        if self.on_show_panel:
            self.on_show_panel()
        else:
            self._open(self.panel_url)

    def _quit(self, icon, _item=None) -> None:
        icon.stop()
        if self.on_exit:
            self.on_exit()

    def _build_icon(self):
        import pystray

        return pystray.Icon(
            "bilibili_learning_bot",
            self._image(),
            "bilibili_learning_bot",
            pystray.Menu(
                pystray.MenuItem("显示网页", self._show_panel, default=True),
                pystray.MenuItem("官网", lambda _i, _m: self._open(OFFICIAL_SITE_URL)),
                pystray.MenuItem("意见反馈", lambda _i, _m: self._open(ISSUES_URL)),
                pystray.MenuItem("开源链接", lambda _i, _m: self._open(REPOSITORY_URL)),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("退出", self._quit),
            ),
        )

    def start(self) -> bool:
        """Start the icon on a detached UI loop. Returns False on unsupported hosts."""
        if os.name != "nt":
            return False
        if not acquire_tray_ownership():
            self.last_error = "tray-owner-conflict"
            self._icon = None
            return False
        try:
            self._icon = self._build_icon()
            # [FIX] 不用 run_detached（内部线程非 daemon，快速 stop 会残留线程
            # 导致进程退出挂起）；改为自建 daemon 线程跑 run()，行为一致。
            import threading

            threading.Thread(
                target=lambda: self._icon and self._icon.run(),
                name="BiliLearnTrayLoop",
                daemon=True,
            ).start()
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self._icon = None
            return False

    def run(self) -> bool:
        """Run the icon loop in the current thread for the desktop launcher."""
        if os.name != "nt":
            return False
        if not acquire_tray_ownership():
            self.last_error = "tray-owner-conflict"
            self._icon = None
            return False
        try:
            self._icon = self._build_icon()
            self._icon.run()
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self._icon = None
            return False

    def stop(self) -> None:
        if self._icon is not None:
            try:
                self._icon.stop()
            except Exception:
                pass
            self._icon = None
        release_tray_ownership()

    def notify(self, title: str, message: str) -> bool:
        """Show a native bottom-right notification (Windows toast, pystray fallback)."""
        if os.name == "nt":
            if self._windows_toast(str(title), str(message)):
                return True
        if self._icon is None:
            return False
        try:
            self._icon.notify(str(message), str(title))
            return True
        except Exception as exc:
            self.last_error = str(exc)
            return False

    @staticmethod
    def _windows_toast(title: str, message: str) -> bool:
        """Fire a Windows 10+ toast notification via PowerShell (no extra deps)."""
        import subprocess

        title = title.replace("'", "''")[:80]
        message = message.replace("'", "''")[:240]
        script = (
            "$null=[Windows.UI.Notifications.ToastNotificationManager,"
            "Windows.UI.Notifications,ContentType=WindowsRuntime];"
            "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
            "[Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
            "$x=$t.GetElementsByTagName('text');"
            "$x.Item(0).AppendChild($t.CreateTextNode('" + title + "'))|Out-Null;"
            "$x.Item(1).AppendChild($t.CreateTextNode('" + message + "'))|Out-Null;"
            "$n=[Windows.UI.Notifications.ToastNotification]::new($t);"
            "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
            "'BiliLearn').Show($n)"
        )
        exe = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32", "WindowsPowerShell", "v1.0", "powershell.exe",
        )
        if not os.path.exists(exe):
            exe = "powershell"
        try:
            subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", script],
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
            )
            return True
        except Exception:
            return False
