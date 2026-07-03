"""utils/helpers.py — 通用工具函数"""
import os
import shutil
import json
import re
import random
from datetime import datetime

from core.config import config

# ── URL脱敏：防止API地址泄露到日志 ──
_URL_MASK_RE = re.compile(r'(https?://)([^/\s"\'<>]+)(/[^\s"\'<>]*)?', re.IGNORECASE)


def _mask_urls(text: str) -> str:
    """将文本中的URL域名替换为 ***，防止API地址泄露。
    例: https://your-api.example.com/v1/chat  →  https://***/v1/chat
    """
    if not text:
        return text
    return _URL_MASK_RE.sub(r'\1***\3', text)


def sanitize_filename(name, is_folder=False):
    name = re.sub(r'[\\/*?:"<>|]', "", name).strip()
    if is_folder:
        return name[:10]
    else:
        return name[:100]


def ensure_ai_marker(text):
    text = (text or "").strip()
    marker = config.get("behavior", {}).get("ai_marker", "（内容由AI生成并由AI回复）")
    if not text:
        return marker
    if marker in text or "(内容由AI生成并由AI回复)" in text:
        return text
    return f"{text}{marker}"


def unix_to_iso(ts):
    try:
        return datetime.fromtimestamp(int(ts)).isoformat()
    except Exception:
        return ""


def parse_iso_datetime(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def human_reply_delay():
    low = max(0, float(config.get("behavior", {}).get("min_reply_delay_seconds", 4) or 0))
    if config.get("speed", {}).get("no_human_delay", False):
        return 0.0
    high = max(low, float(config.get("behavior", {}).get("max_reply_delay_seconds", 18) or low))
    return random.uniform(low, high)


def _clean_ai_output(text):
    # 移除 [Referenced files] 块
    text = re.sub(r'\n?\[Referenced files\].*?(?=\n\n|$)', '', text, flags=re.DOTALL)
    # 移除 <file path=...> 标签
    text = re.sub(r'<file path="[^"]*" skipped="missing" />\s*', '', text)
    return text.strip()


def _load_json_file(path, default=None):
    """安全加载 JSON 文件，不存在或损坏时返回 default"""
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return default.copy() if isinstance(default, dict) else default


def _save_json_file(path, data):
    """原子写入 JSON 文件（先写临时文件再重命名）"""
    try:
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        tmp_path = f"{path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
        return True
    except OSError:
        return False




def _safe_task_callback(task_name="unknown"):
    """返回一个 done_callback，捕获并记录 task 异常，防止崩溃。"""
    import asyncio as _asyncio

    def _cb(task: _asyncio.Task):
        try:
            exc = task.exception()
            if exc is not None:
                from utils.display import log as _log
                _log(f"[WARN] 后台任务 [{task_name}] 异常: {exc}", "ERROR")
                import traceback
                traceback.print_exc()
        except _asyncio.CancelledError:
            from utils.display import log as _log
            _log(f"🔇 后台任务 [{task_name}] 被取消 (CancelledError)", "INFO")
        except _asyncio.InvalidStateError:
            pass
        except Exception as e:
            print(f"[_safe_task_callback] 回调自身异常: {e}", flush=True)
    return _cb


# ── ffmpeg/ffprobe 查找（优先系统PATH，回退到 imageio-ffmpeg）──
_FFMPEG_CACHE: str | None = None
_FFPROBE_CACHE: str | None = None


def find_ffmpeg() -> str | None:
    """查找 ffmpeg 可执行文件路径。
    1) 系统 PATH（shutil.which）
    2) imageio-ffmpeg 内嵌（pip install imageio-ffmpeg）
    结果缓存避免重复查找。"""
    global _FFMPEG_CACHE
    if _FFMPEG_CACHE and (os.path.isfile(_FFMPEG_CACHE) or shutil.which(_FFMPEG_CACHE)):
        return _FFMPEG_CACHE

    # 1) 系统 PATH
    for candidate in ["ffmpeg", "ffmpeg.exe"]:
        path = shutil.which(candidate)
        if path:
            _FFMPEG_CACHE = path
            return path

    # 2) imageio-ffmpeg 内嵌
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and (os.path.isfile(exe) or shutil.which(exe)):
            _FFMPEG_CACHE = exe
            return exe
    except (ImportError, RuntimeError):
        pass

    return None


def find_ffprobe() -> str | None:
    """查找 ffprobe 可执行文件路径（同 find_ffmpeg 逻辑）。"""
    global _FFPROBE_CACHE
    if _FFPROBE_CACHE and (os.path.isfile(_FFPROBE_CACHE) or shutil.which(_FFPROBE_CACHE)):
        return _FFPROBE_CACHE

    # 1) 系统 PATH
    for candidate in ["ffprobe", "ffprobe.exe"]:
        path = shutil.which(candidate)
        if path:
            _FFPROBE_CACHE = path
            return path

    # 2) imageio-ffmpeg 通常也包含 ffprobe
    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe:
            # ffprobe 与 ffmpeg 同目录
            ffmpeg_dir = os.path.dirname(exe)
            for name in ["ffprobe", "ffprobe.exe"]:
                probe_path = os.path.join(ffmpeg_dir, name)
                if os.path.isfile(probe_path):
                    _FFPROBE_CACHE = probe_path
                    return probe_path
    except (ImportError, RuntimeError):
        pass

    return None


# save_search_history moved to core/globals.py to avoid circular import
