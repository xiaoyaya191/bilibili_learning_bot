"""Small optional Windows system-tray integration for the local project."""
from __future__ import annotations

import os
import webbrowser
from pathlib import Path
from collections.abc import Callable
from typing import Any


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
        try:
            self._icon = self._build_icon()
            self._icon.run_detached()
            return True
        except Exception as exc:
            self.last_error = str(exc)
            self._icon = None
            return False

    def run(self) -> bool:
        """Run the icon loop in the current thread for the desktop launcher."""
        if os.name != "nt":
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

    def notify(self, title: str, message: str) -> bool:
        """Show a native bottom-right notification.

        Prefer the live tray icon's balloon (Shell_NotifyIcon NIF_INFO) because
        Windows 10+ renders it as a real toast without AppId registration. Only
        fall back to the PowerShell toast path when no icon is running; that
        path silently drops notifications for unregistered AppIds, so its
        result is now checked instead of assumed.
        """
        if self._icon is not None:
            try:
                self._icon.notify(str(message), str(title))
                return True
            except Exception as exc:
                self.last_error = str(exc)
        if os.name != "nt":
            return False
        return self._windows_toast(str(title), str(message))

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
            result = subprocess.run(
                [exe, "-NoProfile", "-NonInteractive", "-Command", script],
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            # PowerShell 可能起成功但 toast 静默失败（未注册 AppId 等），
            # stderr 有输出或退出码非 0 都视为失败，交还调用方走其它路径。
            return result.returncode == 0 and not (result.stderr or "").strip()
        except Exception:
            return False
