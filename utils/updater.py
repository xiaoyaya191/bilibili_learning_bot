"""启动期更新检查（共享模块）。

查询项目的更新服务器 gengxin.bxya.app/v{当前版本}，判断是否存在更新的已发布版本。
逻辑与 web_panel.py 的 /api/check-update 保持一致，供桌面启动器（原生弹窗）复用。
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.request
from pathlib import Path

UPDATE_BASE = "https://gengxin.bxya.app"
REPOSITORY_URL = "https://github.com/xiaoyaya191/bilibili_learning_bot/releases"

# 桌面弹窗用 MB_OK | MB_ICONINFORMATION
_MB_INFO = 0x40


def _resource_dir() -> Path:
    """项目根目录：frozen 时为 _MEIPASS，否则为 utils 的上一级。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).resolve().parent))
    return Path(__file__).resolve().parent.parent


def _data_dir() -> Path:
    """与 core.user_data.DATA_DIR 一致的跳过记录存放位置。"""
    env = os.getenv("BILI_USER_DATA_DIR", "").strip()
    if env:
        base = Path(env).expanduser()
    else:
        local = os.getenv("LOCALAPPDATA", "").strip()
        base = Path(local) / "BiliLearn" if local else Path.home() / "AppData" / "Local" / "BiliLearn"
    return base / "Data"


def get_local_version() -> str:
    verf = _resource_dir() / "VERSION"
    if verf.exists():
        return verf.read_text(encoding="utf-8", errors="replace").strip()
    return ""


def _skipped_version() -> str:
    try:
        f = _data_dir() / "skipped_version.json"
        if f.exists():
            d = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            return str(d.get("version") or "").strip()
    except Exception:
        pass
    return ""


def write_skipped_version(version: str) -> None:
    """记录用户跳过的更新版本（同时写入时间戳）。"""
    try:
        d = _data_dir()
        d.mkdir(parents=True, exist_ok=True)
        (d / "skipped_version.json").write_text(
            json.dumps({"version": version or "",
                        "at": time.strftime("%Y-%m-%d %H:%M:%S")},
                       ensure_ascii=False),
            encoding="utf-8")
    except Exception:
        pass


def _vnum(s: str) -> tuple:
    nums = re.findall(r"\d+", s)
    t = tuple(int(x) for x in nums[:3])
    return t + (0,) * (3 - len(t))


def check_for_update(timeout: int = 12, current_version: str = "", retries: int = 5) -> dict:
    """检查一次更新，返回状态字典。

    网络异常时不立即放弃，而是按 retries 次重试（默认 5 次，指数退避重试）。
    返回的键：ok, current_version, latest_version, update_available,
    skipped_version, server_unknown_current, release_name, release_body,
    release_url, message, error
    """
    current = (current_version or get_local_version() or "3.1.6")
    ver = current if current.lower().startswith("v") else "v" + current
    url = f"{UPDATE_BASE}/{ver}"
    result = {
        "ok": True,
        "current_version": ver,
        "latest_version": "",
        "update_available": False,
        "skipped_version": _skipped_version(),
        "server_unknown_current": False,
        "release_name": "",
        "release_body": "",
        "release_url": REPOSITORY_URL,
        "message": "当前已是最新版本",
        "error": "",
    }
    retries = max(1, int(retries or 5))
    data = None
    last_err = ""
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "BiliLearn/" + ver, "Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "replace"))
            last_err = ""
            break
        except Exception as e:  # 网络异常：重试，仍失败则静默降级，不打扰用户
            last_err = str(e)
            if attempt + 1 < retries:
                time.sleep(min(0.5 * (attempt + 1), 3))
    if data is None:
        result["error"] = "检查更新失败: " + last_err
        result["message"] = "网络异常，无法连接更新服务器"
        return result

    latest = str(data.get("latest_version", "") or "")
    result["latest_version"] = latest
    result["release_name"] = str(data.get("release_name", "") or "")
    result["release_body"] = str(data.get("release_body", "") or "")
    result["release_url"] = str(data.get("release_url", "") or REPOSITORY_URL)

    have_update = bool(latest) and _vnum(latest) > _vnum(current)
    skipped = result["skipped_version"]
    # 该版本被用户跳过则不再提示（仍回传状态，便于前端判断）
    if have_update and skipped and _vnum(skipped) >= _vnum(latest):
        have_update = False
    result["update_available"] = have_update
    result["server_unknown_current"] = bool(latest) and _vnum(latest) < _vnum(current)
    result["message"] = "发现新版本 " + latest if have_update else "当前已是最新版本"
    return result


def notify_update_popup() -> None:
    """后台线程入口：检查一次更新，有新版本则弹原生 Windows 消息框提醒。"""
    try:
        info = check_for_update()
    except Exception:
        return
    if not info.get("update_available"):
        return
    try:
        import ctypes

        latest = info.get("latest_version", "")
        current = info.get("current_version", "")
        url = info.get("release_url") or REPOSITORY_URL
        body = (info.get("release_body") or "").strip().replace("\r", "")
        if len(body) > 600:
            body = body[:600] + "…"
        msg = (
            f"发现新版本 {latest}（当前 {current}）\n\n"
            + (body + "\n\n" if body else "")
            + f"下载 / 查看更新：\n{url}"
        )
        ctypes.windll.user32.MessageBoxW(None, msg, "BiliLearn 更新提醒", _MB_INFO)
    except Exception:
        pass


def start_update_check() -> None:
    """启动一次后台更新检查（不阻塞调用方）。"""
    t = threading.Thread(target=notify_update_popup, daemon=True)
    t.start()


if __name__ == "__main__":
    import pprint
    pprint.pprint(check_for_update())
