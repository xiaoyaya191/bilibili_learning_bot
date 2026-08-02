#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false, reportUnknownParameterType=false, reportMissingParameterType=false, reportPrivateUsage=false, reportPrivateLocalImportUsage=false, reportUnusedCallResult=false, reportDeprecated=false, reportMissingTypeStubs=false, reportMissingImports=false, reportAny=false
"""
bilibili_learning_bot · Web 管理面板 
功能：仪表盘 | 机器人启停 | B站扫码登录 | 配置编辑 | 实时日志
     人格管理 | 评论日志 | 用户画像 | 记忆知识库 | 日记进化 | 操作日志
"""
import os, sys, json, time, io, base64, threading, asyncio, subprocess, signal, queue, hashlib, secrets, uuid as _uuid_module, collections, traceback, re, ast
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, quote, urlsplit
from http.cookiejar import CookieJar
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen

# ── 线程安全 JSON 工具 ──
from utils.storage import JsonStore, sanitize_config_for_export, is_safe_path, get_backup_dir, strip_hidden_placeholders
from utils.display import redact_sensitive_text
from utils.lock import bot_lock_status
from utils.web_launcher import (
    WEB_SERVICE_ID,
    find_available_port,
    get_web_port,
    is_our_panel,
    is_port_open,
    open_browser_when_ready,
    panel_url,
)
from utils.system_tray import SystemTray

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

def _disclaimer_confirm_terminal():
    """显示红色免责声明，输入'我同意'后继续。"""
    from colorama import Fore, Style
    _TARGET = "\u6211\u540c\u610f"  # 我同意
    banner = f"""
{Fore.RED}{'=' * 60}
  \u26a0  免责声明 / DISCLAIMER
{'=' * 60}
  本项目仅供学习参考，
  若因使用本项目产生任何后果，本人概不负责。

  This project is for learning purposes only.
  Any consequences are solely your own responsibility.
{'=' * 60}{Style.RESET_ALL}
"""
    print(banner)
    user_input = input(f"{Fore.YELLOW}请输入 '{_TARGET}' 以继续:{Style.RESET_ALL}").strip()
    if user_input != _TARGET:
        print(f"{Fore.RED}\u2717 输入不匹配，程序退出。{Style.RESET_ALL}")
        sys.exit(1)
    print(f"{Fore.GREEN}\u2713 已确认，欢迎使用...{Style.RESET_ALL}\n")
    return True

os.environ.setdefault('PYTHONIOENCODING', 'utf-8')


def _background_process_flags() -> int:
    """Keep web-managed workers out of the launcher batch console on Windows."""
    if os.name != "nt":
        return 0
    # A detached process cannot receive Ctrl+C events aimed at ``启动网页版.bat``.
    # stdout/stderr remain explicitly piped to the web panel below.
    return (
        subprocess.CREATE_NEW_PROCESS_GROUP
        | subprocess.DETACHED_PROCESS
        | subprocess.CREATE_NO_WINDOW
    )

try:
    from flask import Flask, request, jsonify, Response, stream_with_context, session, redirect
except ImportError:
    print("[ERROR] Please install Flask: pip install flask")
    sys.exit(1)

try:
    import qrcode as qrlib
    from qrcode.image.pil import PilImage
except ImportError:
    qrlib = None

# ── 路径：代码保留在项目目录，用户数据统一保存在用户目录 ──
BASE_DIR = Path(__file__).resolve().parent
from core.user_data import (
    DATA_DIR as _DEFAULT_DATA_DIR,
    HIGHLIGHTS_DIR,
    HTML_EXPORTS_DIR,
    KNOWLEDGE_BASE_DIR,
    MINDMAPS_DIR,
    QR_CODES_DIR,
    USER_DATA_DIR,
    WORD_DIR,
)
from core.factory_reset import DEFAULT_RESET_GROUP_IDS, RESET_GROUPS, erase_all_user_data, preview_reset_targets

DATA_DIR = _DEFAULT_DATA_DIR
DATA_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA_DIR / "config.json"
COOKIE_FILE = DATA_DIR / "bilibili_cookies.json"

_VERSION_FILE = BASE_DIR / "VERSION"
try:
    APP_VERSION = _VERSION_FILE.read_text(encoding="utf-8").strip() or "dev"
except OSError:
    APP_VERSION = "dev"

app = Flask(__name__, static_folder=None)

# ── 🔐 密码哈希（SHA-256 + salt，不引入额外依赖） ──
def _hash_password(password: str) -> str:
    """对密码做 salted hash，格式: $sha256$<salt>$<hash_hex>"""
    salt = os.urandom(16).hex()
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000)
    return f'$sha256${salt}${h.hex()}'

def _verify_password(password: str, stored: str) -> bool:
    """验证密码是否匹配存储的哈希"""
    if not stored or not stored.startswith('$sha256$'):
        # 兼容旧版明文密码：直接比较（已废弃，建议重新设置密码以启用加密存储）
        import warnings
        warnings.warn("检测到旧版明文密码存储，建议进入 Web 面板重新设置密码以启用安全哈希", DeprecationWarning)
        return password == stored
    _, _, salt, hash_hex = stored.split('$', 3)
    h = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100_000)
    return h.hex() == hash_hex


RECOVERY_DIR_NAME = "账号恢复"
RECOVERY_FILE_NAME = "网页端账号恢复.txt"


def _recovery_file_path() -> Path:
    return Path(DATA_DIR).parent / RECOVERY_DIR_NAME / RECOVERY_FILE_NAME


def _new_recovery_code() -> str:
    raw = secrets.token_hex(12).upper()
    return "-".join(raw[i:i + 4] for i in range(0, len(raw), 4))


def _normalize_security_answer(answer: str) -> str:
    return " ".join(str(answer).strip().casefold().split())


def _write_recovery_file(username: str, recovery_code: str) -> bool:
    path = _recovery_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_suffix(path.suffix + ".tmp")
        temp_path.write_text(
            "网页端账号恢复\n"
            "================\n"
            f"用户名: {username}\n"
            f"一次性恢复码: {recovery_code}\n\n"
            "登录时填写上面的用户名，并把一次性恢复码填入密码框。\n"
            "恢复登录成功后，本文件中的恢复码会自动更新，旧码立即失效。\n"
            "请勿把此文件发送给其他人。\n",
            encoding="utf-8",
        )
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, path)
        return True
    except OSError as exc:
        log_line(f"账号恢复文件写入失败: {exc}")
        return False


def _rotate_recovery_code(config: dict, username: str) -> bool:
    code = _new_recovery_code()
    config.setdefault("web", {})["recovery_code"] = _hash_password(code)
    if not write_json(CONFIG_FILE, config):
        return False
    return _write_recovery_file(username, code)


def _ensure_recovery_file() -> bool:
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.get("web", {})
    username = str(web_cfg.get("username", "")).strip()
    if not username or not web_cfg.get("password"):
        return False
    if web_cfg.get("recovery_code") and _recovery_file_path().exists():
        return True
    return _rotate_recovery_code(config, username)

# ── 🔑 Session 密钥持久化（避免重启后所有用户被踢出） ──
DATA_DIR.mkdir(parents=True, exist_ok=True)
SECRET_KEY_FILE = DATA_DIR / ".web_secret_key"
if SECRET_KEY_FILE.exists():
    app.secret_key = SECRET_KEY_FILE.read_text().strip()
else:
    app.secret_key = os.urandom(24).hex()
    SECRET_KEY_FILE.write_text(app.secret_key)

DATA_DIR.mkdir(parents=True, exist_ok=True)

# ── 全局状态 ──
bot_process: subprocess.Popen | None = None
bot_running = False
bot_start_time: datetime | None = None
panel_start = datetime.now()
bot_output_lines: list[str] = []
bot_output_lock = threading.Lock()
bot_state_lock = threading.RLock()
bot_last_exit_code: int | None = None
bot_last_error = ""
_system_tray: SystemTray | None = None
_critical_ai_failure_lock = threading.Lock()
_critical_ai_failure_handled = False
_bili_profile_cache: dict = {"expires_at": 0.0, "profile": None}
BOT_RUNTIME_LOG_FILE = DATA_DIR / "web_bot_runtime.log"
MONITOR_RUNTIME_LOG_FILE = DATA_DIR / "web_monitor_runtime.log"
system_metrics_history = collections.deque(maxlen=60)
system_metrics_lock = threading.Lock()

# QR 登录状态。session_id prevents a cancelled QR worker from overwriting a newer QR.
qr_state = {"active": False, "url": "", "status": "idle", "message": "", "uid": "", "img_b64": "", "session_id": ""}
qr_state_lock = threading.Lock()


def _new_qr_session():
    """Create an isolated QR session and invalidate any previous worker."""
    global qr_state
    with qr_state_lock:
        return _new_qr_session_locked()


def _new_qr_session_locked():
    """Create a QR session while ``qr_state_lock`` is already held."""
    global qr_state
    session_id = _uuid_module.uuid4().hex
    qr_state = {
        "active": True,
        "url": "",
        "status": "generating",
        "message": "正在生成二维码...",
        "uid": "",
        "img_b64": "",
        "session_id": session_id,
    }
    return session_id


def _qr_session_is_current(session_id):
    with qr_state_lock:
        return qr_state.get("session_id") == session_id


def _update_qr_state(session_id, **changes):
    """Apply state only while this worker still owns the active QR session."""
    with qr_state_lock:
        if qr_state.get("session_id") != session_id:
            return False
        qr_state.update(changes)
        return True


def _qr_callback_payload(event):
    """Return the response object holding the QR completion callback URL."""
    fallback = event if isinstance(event, dict) else {}
    queue = [fallback]
    while queue:
        candidate = queue.pop(0)
        callback_url = str(candidate.get("url") or "")
        if callback_url:
            if "SESSDATA=" in callback_url:
                return candidate
            fallback = candidate
        queue.extend(value for value in candidate.values() if isinstance(value, dict))
    return fallback


def _cookies_from_qr_done_event(event):
    """Extract QR callback cookies even when the upstream response wraps ``data``."""
    payload = _qr_callback_payload(event)

    callback_url = str(payload.get("url") or "")
    values = parse_qs(urlsplit(callback_url).query, keep_blank_values=True)

    def _value(name):
        items = values.get(name, [])
        return str(items[-1] if items else "").strip()

    # login_v2's Credential object stores an URL-encoded SESSDATA. Preserve
    # that representation because the rest of this project sends cookies raw.
    sessdata = quote(_value("SESSDATA"), safe="/")
    return {
        "SESSDATA": sessdata,
        "bili_jct": _value("bili_jct"),
        "DedeUserID": _value("DedeUserID"),
        "buvid3": "",
        "ac_time_value": str(payload.get("refresh_token") or "").strip(),
    }


def _cookies_from_qr_callback_redirect(callback_url):
    """Follow B站's modern QR callback and collect its Set-Cookie response safely."""
    if not callback_url:
        return {}
    jar = CookieJar()
    opener = build_opener(HTTPCookieProcessor(jar))
    request_obj = Request(
        callback_url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
            "Referer": "https://www.bilibili.com/",
        },
    )
    with opener.open(request_obj, timeout=12) as response:
        response.read(1)
    cookies = {cookie.name: cookie.value for cookie in jar}
    return {
        "SESSDATA": str(cookies.get("SESSDATA") or "").strip(),
        "bili_jct": str(cookies.get("bili_jct") or "").strip(),
        "DedeUserID": str(cookies.get("DedeUserID") or "").strip(),
        "buvid3": str(cookies.get("buvid3") or "").strip(),
    }


def _has_complete_qr_cookies(cookies):
    return (
        len(str((cookies or {}).get("SESSDATA") or "").strip()) >= 10
        and len(str((cookies or {}).get("bili_jct") or "").strip()) >= 8
        and str((cookies or {}).get("DedeUserID") or "").strip().isdigit()
    )


def _qr_cookie_lengths(cookies):
    """Return diagnostics safe for logs; never include Cookie values."""
    return ", ".join(
        f"{key}_len={len(str((cookies or {}).get(key) or ''))}"
        for key in ("SESSDATA", "bili_jct", "DedeUserID", "ac_time_value")
    )


def _qr_event_shape(event):
    """Describe only response structure for login diagnostics, never response values."""
    if not isinstance(event, dict):
        return f"type={type(event).__name__}"
    top_keys = ",".join(sorted(str(key) for key in event.keys())[:12])
    nested = event.get("data")
    nested_keys = ",".join(sorted(str(key) for key in nested.keys())[:12]) if isinstance(nested, dict) else "-"
    url_lengths = []
    queue = [event]
    while queue:
        candidate = queue.pop(0)
        url = candidate.get("url")
        if isinstance(url, str):
            url_lengths.append(str(len(url)))
        queue.extend(value for value in candidate.values() if isinstance(value, dict))
    return f"keys={top_keys}; data_keys={nested_keys}; url_lens={','.join(url_lengths) or '-'}"


async def _poll_qr_login_event(qr):
    """Read one QR event and retain its callback URL for the DONE transition."""
    from bilibili_api import login_v2 as bilibili_login_v2
    from bilibili_api.utils.network import Api, Credential

    qr_key = getattr(qr, "_QrCodeLogin__qr_key", "")
    event_api = bilibili_login_v2.API["qrcode"]["web"]["get_events"]
    return await Api(credential=Credential(), **event_api).update_params(qrcode_key=qr_key).result

def log_line(msg: str):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {redact_sensitive_text(msg)}"
    with bot_output_lock:
        bot_output_lines.append(line)
        if len(bot_output_lines) > 500:
            del bot_output_lines[:-400]
        if not os.getenv("PYTEST_CURRENT_TEST"):
            try:
                if BOT_RUNTIME_LOG_FILE.exists() and BOT_RUNTIME_LOG_FILE.stat().st_size > 2 * 1024 * 1024:
                    previous = BOT_RUNTIME_LOG_FILE.read_text(encoding="utf-8", errors="replace")[-1024 * 1024:]
                    BOT_RUNTIME_LOG_FILE.write_text(previous, encoding="utf-8")
                with BOT_RUNTIME_LOG_FILE.open("a", encoding="utf-8") as handle:
                    handle.write(line + "\n")
            except OSError:
                pass
    print(line, flush=True)
    return line


def _append_runtime_log(path: Path, line: str) -> None:
    """Persist web-visible child-process output without terminal escape codes."""
    if os.getenv("PYTEST_CURRENT_TEST"):
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
            path.write_text(path.read_text(encoding="utf-8", errors="replace")[-1024 * 1024:], encoding="utf-8")
        with path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass


_LOG_CLOCK_RE = re.compile(r"(\d{2}:\d{2}:\d{2})")


def _normalize_platform_result_line(line: str) -> str:
    """Turn raw Bilibili result dictionaries into a useful, safe log record."""
    text = str(line or "").strip()
    prefix_match = re.match(r"^(\[[0-9:]+\]\s*)", text)
    prefix = prefix_match.group(1) if prefix_match else ""
    candidate = text[len(prefix):]
    if not (candidate.startswith("{") and candidate.endswith("}")):
        return redact_sensitive_text(text)
    try:
        payload = ast.literal_eval(candidate)
    except (SyntaxError, ValueError):
        return redact_sensitive_text(text)
    if not isinstance(payload, dict) or "code" not in payload:
        return redact_sensitive_text(text)
    code = payload.get("code")
    message = str(payload.get("message") or payload.get("msg") or "平台未提供说明").strip()
    if str(code) == "-509":
        return prefix + "[WARN] [PLATFORM] B站请求频率受限（-509），将在 10 秒后重试"
    if str(code) == "21047":
        return prefix + "[WARN] [PLATFORM] 私信未发送：对方主动回复或关注前，平台最多允许发送 1 条"
    tone = "[INFO]" if str(code) in {"0", "None"} else "[WARN]"
    return prefix + redact_sensitive_text(f"{tone} [PLATFORM] B站返回代码 {code}：{message}")


def _timestamp_runtime_line(line: str) -> str:
    """Give child-process lines a sortable clock without duplicating one."""
    text = _normalize_platform_result_line(line)
    if not text:
        return ""
    if _LOG_CLOCK_RE.search(text):
        return text
    return f"[{datetime.now().strftime('%H:%M:%S')}] {text}"


def _runtime_log_sort_key(line: str, index: int) -> tuple[str, int]:
    """Keep the complete log chronological across bot, monitor and review sources."""
    match = _LOG_CLOCK_RE.search(str(line or ""))
    return (match.group(1) if match else "99:99:99", index)


def _read_runtime_log(path: Path, memory_lines, limit: int = 1200) -> list[str]:
    """Read the persisted tail, using process memory when no file exists yet."""
    def _clean(line: str) -> str:
        ansi = globals().get('_ANSI_ESCAPE_RE')
        text = ansi.sub('', line) if ansi else line
        return _normalize_platform_result_line(text)
    try:
        if path.exists():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            return [_clean(line) for line in lines[-max(1, min(int(limit), 5000)):]]
    except OSError:
        pass
    return [_clean(line) for line in list(memory_lines)[-max(1, min(int(limit), 5000)):]]

# ── 文件工具（线程安全）──
def read_json(path: Path, default=None):
    """线程安全读取 JSON（通过 JsonStore）。"""
    return JsonStore(path).read(default if default is not None else {})

def write_json(path: Path, data):
    """线程安全写入 JSON（原子写临时文件再 rename）。"""
    return JsonStore(path).write(data)

def file_stat(path: Path):
    if not path.exists(): return {"exists": False, "size": 0, "mtime": None, "size_fmt": "0 B"}
    s = path.stat()
    sz = s.st_size
    return {"exists": True, "size": sz, "mtime": datetime.fromtimestamp(s.st_mtime).strftime("%m-%d %H:%M"),
            "size_fmt": f"{sz/1024:.1f}K" if sz<1024*1024 else f"{sz/1048576:.2f}M"}


def active_knowledge_base_dir() -> Path:
    from core.config import resolve_knowledge_base_dir
    return Path(resolve_knowledge_base_dir(read_json(CONFIG_FILE, {}))).resolve()


def _watch_history_metadata_path() -> Path:
    return Path(DATA_DIR) / "watch_history_metadata.json"


def _favorite_library_path() -> Path:
    return Path(DATA_DIR) / "video_favorites.json"


def _read_favorite_library() -> dict:
    from services.local_favorites import read_library
    return read_library(DATA_DIR)


def _write_favorite_library(data: dict) -> None:
    from services.local_favorites import write_library
    write_library(data, DATA_DIR)


def _new_favorite_folder(name: str) -> dict:
    from services.local_favorites import new_folder
    return new_folder(name)


def _safe_watch_bvid(value) -> str:
    """Accept a BV id or a normal Bilibili video URL without storing the URL."""
    text = str(value or "").strip()
    match = re.search(r"\bBV([0-9A-Za-z]{10})\b", text, flags=re.IGNORECASE)
    return f"BV{match.group(1)}" if match else ""


def _watch_history_duration(value) -> int:
    try:
        return max(0, int(float(value or 0)))
    except (TypeError, ValueError):
        return 0


def _watch_history_duration_label(value) -> str:
    seconds = _watch_history_duration(value)
    if not seconds:
        return "--:--"
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes}:{seconds:02d}"


def _watch_history_time(value) -> str:
    text = str(value or "").strip()
    if not text:
        return "--"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError):
        return text[:16]


def _timeline_question_segments(segments: list[dict], question: str, limit: int = 28) -> list[dict]:
    """Pick evidence cues for a question while retaining exact cue boundaries."""
    words = [word.casefold() for word in re.findall(r"[\u4e00-\u9fff]{1,5}|[A-Za-z0-9_]{2,}", question or "")]
    if not words:
        return segments[:limit]
    ranked = []
    for index, item in enumerate(segments):
        text = str(item.get("text") or "").casefold()
        score = sum(2 if len(word) >= 3 and word in text else 1 if word in text else 0 for word in words)
        if score:
            ranked.append((score, index, item))
    if not ranked:
        return segments[:limit]
    selected = sorted(ranked, key=lambda row: (-row[0], row[1]))[:limit]
    return [row[2] for row in sorted(selected, key=lambda row: row[1])]


def _load_timeline_for_web(bvid: str, refresh: bool = False) -> dict:
    from api.subtitles import fetch_bilibili_subtitles, get_cached_subtitle_timeline

    timeline = {} if refresh else get_cached_subtitle_timeline(bvid)
    if isinstance(timeline.get("segments"), list) and timeline["segments"]:
        return timeline
    cookies = None
    if COOKIE_FILE.exists():
        try:
            cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            cookies = None
    _run_coro(fetch_bilibili_subtitles(bvid, cookies_obj=cookies))
    return get_cached_subtitle_timeline(bvid)


# Older scored records were created before the time-axis cache existed.  Backfill
# them one-by-one while the bot is idle so this never turns into a burst of
# Bilibili requests or competes with the live learning loop.
_timeline_backfill_lock = threading.Lock()
_timeline_backfill_state = {
    "running": False,
    "queued": 0,
    "completed": 0,
    "available": 0,
    "unavailable": 0,
    "current": "",
    "last_started_at": "",
    "last_finished_at": "",
}


def _timeline_backfill_state_path() -> Path:
    return Path(DATA_DIR) / "subtitle_timeline_backfill.json"


def _read_timeline_backfill_results() -> dict:
    data = read_json(_timeline_backfill_state_path(), {})
    return data if isinstance(data, dict) else {}


def _write_timeline_backfill_results(data: dict) -> None:
    write_json(_timeline_backfill_state_path(), data)


def _scored_timeline_backfill_candidates(limit: int = 20) -> list[str]:
    """Return scored local videos that still need an exact CC time axis."""
    from api.subtitles import get_cached_subtitle_timeline

    attempted = _read_timeline_backfill_results()
    candidates = []
    for card in _watch_history_cards():
        bvid = _safe_watch_bvid(card.get("bvid"))
        if not bvid or bvid in candidates:
            continue
        try:
            score = float(card.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        if score <= 0:
            continue
        cached = get_cached_subtitle_timeline(bvid)
        if isinstance(cached.get("segments"), list) and cached["segments"]:
            continue
        previous = attempted.get(bvid) if isinstance(attempted.get(bvid), dict) else {}
        # No CC track is a stable result.  A manual per-video refresh still
        # bypasses this cooldown when a creator adds subtitles later.
        if previous.get("status") == "unavailable":
            continue
        candidates.append(bvid)
        if len(candidates) >= limit:
            break
    return candidates


def _timeline_backfill_snapshot() -> dict:
    state = dict(_timeline_backfill_state)
    state["pending"] = len(_scored_timeline_backfill_candidates())
    return state


def _run_scored_timeline_backfill(limit: int = 20, delay_seconds: float = 20.0) -> None:
    if not _timeline_backfill_lock.acquire(blocking=False):
        return
    try:
        candidates = _scored_timeline_backfill_candidates(limit)
        _timeline_backfill_state.update({
            "running": True,
            "queued": len(candidates),
            "completed": 0,
            "available": 0,
            "unavailable": 0,
            "current": "",
            "last_started_at": datetime.now().isoformat(timespec="seconds"),
        })
        if candidates:
            log_line(f"[TIMELINE] 开始低频回填 {len(candidates)} 条已评分视频的字幕时间轴")
        results = _read_timeline_backfill_results()
        for index, bvid in enumerate(candidates, start=1):
            # The active learning loop already owns the API cadence.
            if _refresh_bot_state():
                log_line("[TIMELINE] 机器人正在运行，已暂停旧视频时间轴回填")
                break
            _timeline_backfill_state["current"] = bvid
            log_line(f"[TIMELINE] 回填 {index}/{len(candidates)}: {bvid}")
            try:
                timeline = _load_timeline_for_web(bvid)
                segments = timeline.get("segments", []) if isinstance(timeline, dict) else []
                if isinstance(segments, list) and segments:
                    _timeline_backfill_state["available"] += 1
                    results[bvid] = {
                        "status": "available",
                        "segments": len(segments),
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    log_line(f"[TIMELINE] 已缓存 {len(segments)} 条精确字幕片段: {bvid}")
                else:
                    _timeline_backfill_state["unavailable"] += 1
                    results[bvid] = {
                        "status": "unavailable",
                        "updated_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    log_line(f"[TIMELINE] {bvid} 没有可定位的 CC 字幕，未生成伪时间轴")
            except Exception as exc:
                results[bvid] = {
                    "status": "error",
                    "message": redact_sensitive_text(str(exc))[:220],
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }
                log_line(f"[TIMELINE] 回填失败 {bvid}: {results[bvid]['message']}")
            finally:
                _timeline_backfill_state["completed"] += 1
                _write_timeline_backfill_results(results)
            if index < len(candidates):
                time.sleep(max(12.0, float(delay_seconds)))
    finally:
        _timeline_backfill_state.update({
            "running": False,
            "current": "",
            "last_finished_at": datetime.now().isoformat(timespec="seconds"),
        })
        _timeline_backfill_lock.release()


def _start_scored_timeline_backfill(limit: int = 20) -> bool:
    if _timeline_backfill_state.get("running") or _refresh_bot_state():
        return False
    thread = threading.Thread(
        target=_run_scored_timeline_backfill,
        kwargs={"limit": max(1, min(20, int(limit)))},
        name="subtitle-timeline-backfill",
        daemon=True,
    )
    thread.start()
    return True


def _fetch_watch_history_metadata(bvid: str) -> dict:
    """Fetch public Bilibili metadata only when the user asks to enrich cards."""
    safe_bvid = _safe_watch_bvid(bvid)
    if not safe_bvid:
        return {}
    request = Request(
        f"https://api.bilibili.com/x/web-interface/view?bvid={safe_bvid}",
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Referer": f"https://www.bilibili.com/video/{safe_bvid}",
        },
    )
    try:
        with urlopen(request, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, URLError, ValueError, json.JSONDecodeError):
        return {}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict) or payload.get("code") != 0:
        return {}
    owner = data.get("owner") if isinstance(data.get("owner"), dict) else {}
    stat = data.get("stat") if isinstance(data.get("stat"), dict) else {}
    return {
        "pic": str(data.get("pic") or "").strip(),
        "duration": _watch_history_duration(data.get("duration")),
        "category": str(data.get("tname") or "").strip(),
        "description": str(data.get("desc") or "").strip()[:500],
        "published_at": int(data.get("pubdate") or 0),
        "view_count": int(stat.get("view") or 0),
        "like_count": int(stat.get("like") or 0),
        "coin_count": int(stat.get("coin") or 0),
        "favorite_count": int(stat.get("favorite") or 0),
        "danmaku_count": int(stat.get("danmaku") or 0),
        "up": str(owner.get("name") or "").strip(),
        "title": str(data.get("title") or "").strip(),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }


def _cache_watch_history_metadata(bvids: list[str], maximum: int = 8) -> tuple[int, int]:
    """Fetch a small, deduplicated batch of public video cards into the local cache."""
    wanted = []
    for value in bvids:
        bvid = _safe_watch_bvid(value)
        if bvid and bvid not in wanted:
            wanted.append(bvid)
        if len(wanted) >= maximum:
            break
    if not wanted:
        return 0, 0

    cache = read_json(_watch_history_metadata_path(), {})
    cache = cache if isinstance(cache, dict) else {}
    missing = [bvid for bvid in wanted if not isinstance(cache.get(bvid), dict)]
    if not missing:
        return 0, 0

    fetched = failed = 0
    with ThreadPoolExecutor(max_workers=min(3, len(missing)), thread_name_prefix="favorite-meta") as pool:
        futures = {pool.submit(_fetch_watch_history_metadata, bvid): bvid for bvid in missing}
        for future in as_completed(futures):
            bvid = futures[future]
            try:
                detail = future.result()
            except Exception:
                detail = {}
            if detail:
                cache[bvid] = detail
                fetched += 1
            else:
                failed += 1
    if fetched:
        write_json(_watch_history_metadata_path(), cache)
    return fetched, failed


def _watch_history_is_archived(bvid: str) -> bool:
    if not bvid:
        return False
    kb_dir = active_knowledge_base_dir()
    if not kb_dir.exists():
        return False
    try:
        return any(bvid in filename for _, _, files in os.walk(kb_dir) for filename in files)
    except OSError:
        return False


def _watch_history_cards() -> list[dict]:
    """Merge old interaction entries and new view entries into one card per BV."""
    source = read_json(Path(DATA_DIR) / "history_videos.json", {})
    entries = source.get("videos", []) if isinstance(source, dict) else []
    metadata = read_json(_watch_history_metadata_path(), {})
    metadata = metadata if isinstance(metadata, dict) else {}
    grouped: dict[str, dict] = {}
    for raw in entries if isinstance(entries, list) else []:
        if not isinstance(raw, dict):
            continue
        bvid = _safe_watch_bvid(raw.get("bvid"))
        if not bvid:
            continue
        item = grouped.setdefault(bvid, {
            "bvid": bvid, "title": "", "up": "", "aid": 0, "pic": "", "duration": 0,
            "category": "", "interest_reason": "", "source": "历史互动", "result": "已互动",
            "actions": set(), "score": 0.0, "time": "", "revisit_count": 0,
        })
        action = str(raw.get("action") or "view").strip().lower()
        item["actions"].add(action)
        for field in ("title", "up", "pic", "category", "interest_reason", "source", "result"):
            value = raw.get(field)
            if value not in (None, ""):
                item[field] = str(value)
        item["aid"] = raw.get("aid") or item["aid"]
        item["duration"] = _watch_history_duration(raw.get("duration")) or item["duration"]
        try:
            item["score"] = max(float(item["score"]), float(raw.get("score") or 0))
        except (TypeError, ValueError):
            pass
        item["revisit_count"] = max(item["revisit_count"], int(raw.get("revisit_count") or 0))
        if str(raw.get("time") or "") >= item["time"]:
            item["time"] = str(raw.get("time") or item["time"])

    archive_index = ""
    kb_dir = active_knowledge_base_dir()
    if kb_dir.exists():
        try:
            archive_index = "\n".join(filename for _, _, files in os.walk(kb_dir) for filename in files)
        except OSError:
            archive_index = ""

    cards = []
    action_labels = {"view": "已浏览", "like": "已点赞", "fav": "已收藏", "coin": "已投币"}
    for bvid, item in grouped.items():
        detail = metadata.get(bvid, {}) if isinstance(metadata.get(bvid), dict) else {}
        for field in ("title", "up", "pic", "category"):
            if not item.get(field) and detail.get(field):
                item[field] = str(detail[field])
        item["duration"] = item["duration"] or _watch_history_duration(detail.get("duration"))
        actions = [action_labels[action] for action in ("view", "like", "fav", "coin") if action in item["actions"]]
        result = item["result"] or "已互动"
        archived = bvid in archive_index
        cards.append({
            "bvid": bvid,
            "title": item["title"] or bvid,
            "up": item["up"] or "未知 UP",
            "aid": item["aid"],
            "cover": item["pic"],
            "duration": _watch_history_duration_label(item["duration"]),
            "category": item["category"],
            "watched_at": _watch_history_time(item["time"]),
            "score": round(item["score"], 1),
            "interest_reason": item["interest_reason"],
            "source": item["source"] or "历史互动",
            "result": result,
            "actions": actions,
            "archived": archived,
            "revisit_count": item["revisit_count"],
            "url": f"https://www.bilibili.com/video/{bvid}",
            # Unknown public metrics stay unknown. Rendering them as zero makes
            # an unhydrated local record look like real Bilibili data.
            "view_count": detail.get("view_count") if isinstance(detail.get("view_count"), int) else None,
            "like_count": detail.get("like_count") if isinstance(detail.get("like_count"), int) else None,
            "coin_count": detail.get("coin_count") if isinstance(detail.get("coin_count"), int) else None,
            "favorite_count": detail.get("favorite_count") if isinstance(detail.get("favorite_count"), int) else None,
            "published_at": int(detail.get("published_at") or 0),
        })
    return sorted(cards, key=lambda card: card["watched_at"], reverse=True)

def _cleanup_qr_images():
    """删除 qr_codes 文件夹中的所有二维码图片"""
    try:
        qr_dir = QR_CODES_DIR
        if qr_dir.is_dir():
            for fpath in qr_dir.iterdir():
                if fpath.is_file():
                    fpath.unlink()
                    log_line(f"已删除过期二维码: {fpath}")
    except Exception as e:
        log_line(f"清理二维码失败: {e}")

# ═══════════════════════════════════════════
#  QR 登录流程（在线程中跑 asyncio）
# ═══════════════════════════════════════════
def do_qr_login(session_id=None):
    """在后台线程中执行 B 站扫码登录"""
    if session_id is None:
        session_id = _new_qr_session()

    async def _login():
        try:
            from bilibili_api.login_v2 import QrCodeLogin

            qr = QrCodeLogin()
            await qr.generate_qrcode()
            url = getattr(qr, "_QrCodeLogin__qr_link", None)

            if not _qr_session_is_current(session_id):
                return
            if not url:
                _update_qr_state(session_id, status="error", message="获取登录链接失败", active=False)
                return

            _update_qr_state(session_id, url=url)
            # 生成二维码图片 base64 (供 Web 展示) + 保存到 qr_codes 文件夹
            img_b64 = ""
            qr_png_path = None
            try:
                if qrlib is None:
                    raise ImportError("qrcode library not available")
                qr_img = qrlib.QRCode(box_size=8, border=2)
                qr_img.add_data(url)
                qr_img.make(fit=True)
                img = qr_img.make_image(fill_color="black", back_color="white")
                buf = io.BytesIO()
                img.save(buf, format="PNG")
                img_b64 = base64.b64encode(buf.getvalue()).decode()
                # 同时保存到 qr_codes 文件夹
                qr_dir = QR_CODES_DIR
                qr_dir.mkdir(exist_ok=True)
                qr_png_path = qr_dir / "bilibili_login_qr.png"
                img.save(str(qr_png_path))
                log_line(f"二维码已保存至: {qr_png_path}")
            except Exception as e:
                log_line(f"QR图片生成失败: {e}")

            if not _update_qr_state(
                session_id,
                img_b64=img_b64,
                status="waiting_scan",
                message="请使用 B站APP 扫描二维码",
            ):
                return

            last_event = None
            while _qr_session_is_current(session_id):
                with qr_state_lock:
                    active = qr_state.get("active", False)
                if not active:
                    return
                try:
                    event = await _poll_qr_login_event(qr)
                    event_code = int((event or {}).get("code", -1))
                    if event_code == 86101:
                        status = "scan"
                    elif event_code == 86090:
                        status = "confirm"
                    elif event_code == 86038:
                        status = "timeout"
                    elif event_code == 0:
                        status = "done"
                    else:
                        raise RuntimeError(f"B站二维码状态异常：{event_code}")
                    if not _qr_session_is_current(session_id):
                        return
                    if status != last_event:
                        log_line(f"[LOGIN] 二维码状态：{status}")
                        last_event = status
                    if status == "done":
                        _update_qr_state(session_id, status="success", message="登录成功！正在保存...")
                        cookies = _cookies_from_qr_done_event(event)
                        source = "callback"
                        if not _has_complete_qr_cookies(cookies):
                            callback_url = str(_qr_callback_payload(event).get("url") or "")
                            try:
                                redirected = await asyncio.to_thread(_cookies_from_qr_callback_redirect, callback_url)
                                for key, value in redirected.items():
                                    if value:
                                        cookies[key] = value
                                source = "callback-redirect"
                            except Exception as e:
                                source = "callback-redirect-error"
                                log_line(f"[LOGIN] 登录回调换取 Cookie 失败: {type(e).__name__}")
                        log_line(f"[LOGIN] 二维码完成事件结构 ({_qr_event_shape(event)})")
                        log_line(f"[LOGIN] 二维码凭据已提取 ({source}; {_qr_cookie_lengths(cookies)})")
                        if not _has_complete_qr_cookies(cookies):
                            _update_qr_state(
                                session_id,
                                status="error",
                                message="B站未返回完整登录凭据，请重新生成二维码后扫码确认",
                                active=False,
                            )
                            log_line("[LOGIN] 登录凭据不完整，未写入 Cookie")
                            return
                        if not _qr_session_is_current(session_id):
                            return
                        previous_cookies = read_json(COOKIE_FILE, {}) if COOKIE_FILE.exists() else {}
                        previous_uid = str(previous_cookies.get("DedeUserID") or "").strip()
                        next_uid = str(cookies.get("DedeUserID") or "").strip()
                        if previous_uid and next_uid and previous_uid != next_uid:
                            log_line(f"[LOGIN] Account changed ({previous_uid} -> {next_uid}); stopping active automation")
                            _stop_automation_for_account_switch()
                            from services.like_review import ActionReviewInbox
                            cancelled = ActionReviewInbox(DATA_DIR).cancel_pending_for_account_switch(
                                previous_uid, next_uid)
                            if cancelled:
                                log_line(f"[LOGIN] Cancelled {cancelled} pending review action(s) from the previous account")
                            log_line("[LOGIN] New account is ready. Automation remains stopped until manually started.")
                        write_json(COOKIE_FILE, cookies)
                        _clear_bili_profile_cache()
                        _update_qr_state(
                            session_id,
                            uid=cookies.get("DedeUserID", ""),
                            message=f"登录成功！UID: {cookies.get('DedeUserID', '?')}",
                            active=False,
                        )
                        log_line(f"B站扫码登录成功 UID={cookies.get('DedeUserID', '?')}")
                        _cleanup_qr_images()  # 登录成功，删除二维码图片
                        return
                    elif status == "scan":
                        _update_qr_state(session_id, status="waiting_scan", message="等待使用 B站APP 扫描二维码")
                    elif status == "confirm":
                        _update_qr_state(session_id, status="scanned", message="已扫描，请在手机 B站APP 内确认登录")
                    elif status == "timeout":
                        if _update_qr_state(session_id, status="timeout", message="二维码已过期，请重新生成", active=False):
                            _cleanup_qr_images()  # 超时也删除过期二维码
                        return
                    await asyncio.sleep(1.5)
                except Exception as e:
                    log_line(f"QR状态查询错误: {e}")
                    await asyncio.sleep(2)
        except Exception as e:
            _update_qr_state(session_id, status="error", message=f"登录异常: {e}", active=False)
            log_line(f"B站登录失败: {e}")

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(_login())
    except Exception as e:
        _update_qr_state(session_id, status="error", message=str(e), active=False)

# ═══════════════════════════════════════════
#  机器人进程管理
# ═══════════════════════════════════════════
def _is_critical_ai_failure(text: str) -> bool:
    normalized = str(text or "").lower()
    return (
        "fatal_ai_failure" in normalized
        or (
            "http 402" in normalized
            and any(marker in normalized for marker in ("insufficient balance", "insufficient quota", "quota exceeded", "余额", "配额"))
        )
    )


def _handle_critical_ai_failure(source_line: str) -> None:
    """Stop the child before a billing failure can trigger local fallback actions."""
    global _critical_ai_failure_handled, bot_last_error
    with _critical_ai_failure_lock:
        if _critical_ai_failure_handled:
            return
        _critical_ai_failure_handled = True
    bot_last_error = "AI account balance or quota is unavailable (HTTP 402)"
    log_line("[ALERT] AI account balance or quota is unavailable. The robot will stop automatically.")
    tray = _system_tray
    if tray is not None:
        tray.notify("BiliLearn AI error", "AI account balance or quota is unavailable. The robot has stopped.")
    from utils.desktop_notifications import enqueue as enqueue_desktop_notification
    enqueue_desktop_notification(DATA_DIR, "BiliLearn AI error", "AI account balance or quota is unavailable. The robot has stopped.")
    threading.Thread(
        target=lambda: stop_bot_process(immediate=True),
        name="critical-ai-stop",
        daemon=True,
    ).start()


def _bot_reader(pipe, prefix=""):
    """读取子进程输出"""
    handoff_monitor = False
    try:
        for line in iter(pipe.readline, ""):
            if not line: break
            text = line.rstrip()
            if text:
                if _is_critical_ai_failure(text):
                    _handle_critical_ai_failure(text)
                if text == "[SESSION] HANDOFF_MONITOR_REQUESTED":
                    handoff_monitor = True
                    log_line("[SESSION] 刷视频限制已完成，准备切换到实时监听")
                else:
                    log_line(prefix + text)
    except OSError as e:
        log_line(f"⚠ 读取子进程输出异常: {e}")
    finally:
        try: pipe.close()
        except OSError as e:
            log_line(f"⚠ 关闭管道异常: {e}")
    if handoff_monitor:
        # EOF means the browsing child has exited. Reconcile its lock/process
        # before starting the separately managed monitor process.
        for _ in range(20):
            if not _refresh_bot_state():
                break
            time.sleep(0.1)
        ok, message = _start_monitor_process()
        log_line(f"[SESSION] {message}" if ok else f"[SESSION] 自动切换监听失败: {message}")

def _refresh_bot_state():
    """Reconcile cached UI state with the actual child process."""
    global bot_process, bot_running, bot_last_exit_code
    with bot_state_lock:
        if bot_process is None:
            bot_running = False
            return False
        code = bot_process.poll()
        if code is None:
            bot_running = True
            return True
        if bot_running:
            log_line(f"机器人进程已退出（退出码 {code}）")
        bot_last_exit_code = code
        bot_running = False
        bot_process = None
        return False

def start_bot_process(mode=None):
    global bot_process, bot_running, bot_start_time, bot_last_error, bot_last_exit_code, _critical_ai_failure_handled
    started = time.perf_counter()
    if _refresh_bot_state():
        return False, "机器人已在运行"

    if not _has_valid_bili_cookies():
        message = "B站尚未完成登录。请在“B站登录”扫码并在手机确认后，再启动机器人。"
        bot_last_error = message
        log_line(f"启动已取消：{message}")
        return False, message

    lock_state = bot_lock_status(clean_stale=True)
    if lock_state["locked"]:
        owner_pid = lock_state["pid"] or "未知"
        message = f"检测到另一个机器人实例正在运行（PID: {owner_pid}），请先停止它。"
        bot_last_error = message
        log_line(f"启动已取消：{message}")
        return False, message

    frozen_runtime = bool(getattr(sys, "frozen", False))
    agent_path = BASE_DIR / "main.py"
    if not frozen_runtime and not agent_path.exists():
        return False, f"找不到 {agent_path}"

    log_line("🚀 正在启动机器人进程...")
    try:
        with _critical_ai_failure_lock:
            _critical_ai_failure_handled = False
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        # 设置环境变量跳过子进程的免责声明交互
        env["BILI_DISCLAIMER_SKIP"] = "1"
        # 关键：自动启动模式——子进程直接以已配置模式运行机器人，
        # 不再走交互菜单（此前只喂 "1\n" 会卡在二级"选择启动模式"子菜单，机器人永不真正运行）
        env["BILI_AUTO_START"] = "1"
        # 由网页端下拉选择启动模式（smart=智能省token / current=当前模式）
        if mode == "smart":
            env["BILI_AUTO_START_MODE"] = "smart"
        elif mode == "current":
            env["BILI_AUTO_START_MODE"] = "current"

        command = [sys.executable, "--bot"] if frozen_runtime else [sys.executable, str(agent_path)]
        bot_process = subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_background_process_flags(),
        )
        bot_running = True
        bot_start_time = datetime.now()
        bot_last_error = ""
        bot_last_exit_code = None

        threading.Thread(target=_bot_reader, args=(bot_process.stdout, ""), daemon=True).start()
        time.sleep(0.25)
        if bot_process.poll() is not None:
            code = bot_process.returncode
            bot_running = False
            bot_last_exit_code = code
            bot_process = None
            return False, f"机器人启动后立即退出（退出码 {code}），请查看日志"
        log_line(f"✅ 机器人进程已启动（{time.perf_counter() - started:.2f}s）")
        return True, "机器人已启动"
    except Exception as e:
        bot_last_error = str(e)
        bot_running = False
        log_line(f"❌ 启动失败: {e}")
        return False, str(e)

def stop_bot_process(immediate: bool = False):
    global bot_process, bot_running
    started = time.perf_counter()
    if not _refresh_bot_state():
        return True, "机器人已处于停止状态"
    try:
        if bot_process:
            log_line("⏹ 正在停止机器人...")
            try:
                if bot_process.stdin and not bot_process.stdin.closed:
                    bot_process.stdin.write("0\n")
                    bot_process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError) as e:
                log_line(f"⚠ 发送退出命令失败 (管道断开): {e}")
            if not immediate:
                time.sleep(0.5)
            bot_process.terminate()
            try: bot_process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                log_line("⚠ 进程未响应 terminate，尝试 kill...")
                try: bot_process.kill()
                except Exception as e: log_line(f"⚠ kill 失败: {e}")
            bot_process = None
    except Exception as e:
        log_line(f"停止异常: {e}")
    bot_running = False
    log_line(f"✅ 机器人已停止（{time.perf_counter() - started:.2f}s）")
    return True, "已停止"


def _stop_automation_for_account_switch() -> None:
    """Stop all account-writing automation before replacing Bilibili cookies."""
    global monitor_process, monitor_running, monitor_started_at
    global standby_process, standby_running

    stop_bot_process(immediate=True)

    external_monitor = _external_monitor_details()
    processes = (("monitor_process", monitor_process), ("standby_process", standby_process))
    for process_name, process in processes:
        if process is None or process.poll() is not None:
            continue
        try:
            process.terminate()
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except OSError:
                pass
        except OSError:
            pass
        globals()[process_name] = None

    if external_monitor:
        try:
            import psutil
            process = psutil.Process(external_monitor["pid"])
            process.terminate()
            try:
                process.wait(timeout=5)
            except psutil.TimeoutExpired:
                process.kill()
        except Exception as exc:
            log_line(f"[LOGIN] Unable to stop previous monitor: {exc}")

    monitor_running = False
    monitor_started_at = None
    standby_running = False

# ═══════════════════════════════════════════
#  HTML 模板（从文件加载，回退到内嵌模板）
# ═══════════════════════════════════════════
_HTML_FILE = BASE_DIR / "web_panel.html"

def _load_html() -> str:
    """从 web_panel.html 文件加载模板，不存在则使用内嵌默认"""
    if _HTML_FILE.exists():
        try:
            html = _HTML_FILE.read_text(encoding="utf-8")
        except OSError:
            html = _DEFAULT_HTML
    else:
        html = _DEFAULT_HTML
    # 替换账号相关的占位符
    html = html.replace('{{ACCOUNT_TITLE}}', '控制面板')
    html = html.replace('{{ACCOUNT_HEADER}}', '控制面板')
    return html

_DEFAULT_HTML = r'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="color-scheme" content="light dark">
<title>{{ACCOUNT_TITLE}}</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
<script>if(typeof Chart==='undefined'){document.write('<script src="https://cdn.bootcdn.net/ajax/libs/Chart.js/4.4.0/chart.umd.min.js"><\/script>')}</script>
<script>if(typeof Chart==='undefined'){document.write('<script src="https://unpkg.com/chart.js@4.4.0/dist/chart.umd.min.js"><\/script>')}</script>
<style>
/* ===== 多主题系统 (inspired by xiongdaa-card) ===== */
:root,[data-theme="aurora"]{
--bg:#0b0f19;--bg2:rgba(17,24,39,.55);--bg3:rgba(30,41,59,.5);--bg4:rgba(40,53,72,.5);
--border:rgba(42,58,80,.5);--border2:rgba(55,72,96,.6);
--text:#e8f0ff;--text2:rgba(200,215,240,.75);--text3:rgba(100,120,150,.7);
--accent:#6ee7b7;--accent2:#60a5fa;
--accent-g:linear-gradient(135deg,#6ee7b7 0%,#60a5fa 100%);
--green:#34d399;--green-g:linear-gradient(135deg,#34d399 0%,#06b6d4 100%);
--orange:#fbbf24;--red:#f87171;--pink:#f472b6;--purple:#a78bfa;
--glow:rgba(110,231,183,.25);--glow2:rgba(96,165,250,.2);
--r:16px;--rs:10px;--rs2:14px;
--shadow:0 4px 24px rgba(0,0,0,.35);--shadow-lg:0 12px 48px rgba(0,0,0,.5);
--glass:rgba(15,20,40,.45);--glass-border:rgba(110,200,255,.12);
--glass-blur:blur(24px) saturate(160%);
--sidebar-bg:rgba(12,16,30,.65);--overlay:radial-gradient(ellipse at 30% 20%,rgba(110,231,183,.06) 0%,transparent 50%),radial-gradient(ellipse at 70% 80%,rgba(96,165,250,.05) 0%,transparent 50%);
}
[data-theme="cyberpunk"]{
--bg:#0a0014;--bg2:rgba(20,0,40,.55);--bg3:rgba(40,10,60,.5);--bg4:rgba(60,20,80,.5);
--border:rgba(255,0,128,.15);--border2:rgba(255,0,128,.25);
--text:#fff0f5;--text2:rgba(255,200,220,.65);--text3:rgba(180,100,130,.6);
--accent:#ff2d7b;--accent2:#00f0ff;
--accent-g:linear-gradient(135deg,#ff2d7b 0%,#00f0ff 100%);
--green:#00f0ff;--green-g:linear-gradient(135deg,#00f0ff 0%,#ff2d7b 100%);
--glow:rgba(255,45,123,.3);--glow2:rgba(0,240,255,.2);
--r:8px;--rs:6px;--rs2:10px;
--shadow:0 4px 24px rgba(255,0,128,.15);--shadow-lg:0 12px 48px rgba(0,0,0,.5);
--glass:rgba(10,0,25,.55);--glass-border:rgba(255,0,128,.2);
--glass-blur:blur(20px) saturate(200%);
--sidebar-bg:rgba(10,0,20,.7);--overlay:radial-gradient(ellipse at 50% 0%,rgba(255,0,128,.08) 0%,transparent 60%);
}
[data-theme="sakura"]{
--bg:#1a0a10;--bg2:rgba(40,15,25,.55);--bg3:rgba(60,25,40,.5);--bg4:rgba(80,35,55,.5);
--border:rgba(255,182,193,.18);--border2:rgba(255,182,193,.28);
--text:#fff0f3;--text2:rgba(255,200,210,.7);--text3:rgba(200,120,140,.6);
--accent:#ff9eb5;--accent2:#ffd1dc;
--accent-g:linear-gradient(135deg,#ff9eb5 0%,#ffd1dc 100%);
--green:#ffd1dc;--green-g:linear-gradient(135deg,#ffd1dc 0%,#ff9eb5 100%);
--glow:rgba(255,158,181,.25);--glow2:rgba(255,209,220,.2);
--r:20px;--rs:12px;--rs2:16px;
--shadow:0 4px 24px rgba(200,100,130,.15);--shadow-lg:0 12px 48px rgba(0,0,0,.4);
--glass:rgba(30,10,20,.5);--glass-border:rgba(255,182,193,.2);
--glass-blur:blur(22px) saturate(140%);
--sidebar-bg:rgba(25,8,15,.7);--overlay:radial-gradient(ellipse at 40% 30%,rgba(255,158,181,.06) 0%,transparent 50%);
}
[data-theme="galaxy"]{
--bg:#050010;--bg2:rgba(15,5,40,.55);--bg3:rgba(25,15,60,.5);--bg4:rgba(40,25,80,.5);
--border:rgba(147,130,255,.15);--border2:rgba(147,130,255,.25);
--text:#e8e0ff;--text2:rgba(180,170,220,.7);--text3:rgba(130,120,180,.6);
--accent:#b388ff;--accent2:#ff80ab;
--accent-g:linear-gradient(135deg,#b388ff 0%,#ff80ab 100%);
--green:#b388ff;--green-g:linear-gradient(135deg,#b388ff 0%,#ff80ab 100%);
--glow:rgba(179,136,255,.25);--glow2:rgba(255,128,171,.2);
--r:18px;--rs:10px;--rs2:14px;
--shadow:0 4px 24px rgba(100,50,200,.15);--shadow-lg:0 12px 48px rgba(0,0,0,.5);
--glass:rgba(10,5,30,.5);--glass-border:rgba(147,130,255,.15);
--glass-blur:blur(28px) saturate(140%);
--sidebar-bg:rgba(8,3,25,.7);--overlay:radial-gradient(ellipse at 60% 20%,rgba(179,136,255,.06) 0%,transparent 50%);
}
*{box-sizing:border-box;margin:0;padding:0}
html{scroll-behavior:smooth}
body{font-family:'Noto Sans SC',system-ui,-apple-system,"Segoe UI","PingFang SC","Microsoft YaHei",sans-serif;background:var(--bg);color:var(--text);display:flex;min-height:100vh;line-height:1.5;-webkit-font-smoothing:antialiased;transition:background .6s cubic-bezier(.4,0,.2,1)}

/* ── BACKGROUND LAYERS ── */
.bg-layer{position:fixed;inset:0;z-index:0;overflow:hidden;pointer-events:none}
.bg-layer img,.bg-layer video{width:100%;height:100%;object-fit:cover;opacity:.35;transition:opacity .8s}
.bg-layer .bg-default{width:100%;height:100%;background:linear-gradient(135deg,#0a0e1a 0%,#0d1b2a 40%,#1b2838 100%);transition:opacity .6s}
.overlay{position:fixed;inset:0;z-index:1;pointer-events:none;background:var(--overlay);transition:background .6s}
#ambientCanvas{position:fixed;inset:0;z-index:2;pointer-events:none;opacity:.4}
a{color:var(--accent);text-decoration:none;transition:color .2s}
a:hover{color:var(--purple)}

/* SCROLLBAR */
::-webkit-scrollbar{width:5px;height:5px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--bg4);border-radius:4px}
::-webkit-scrollbar-thumb:hover{background:var(--border2)}

/* ── SIDEBAR ── */
.sidebar{width:240px;min-width:240px;background:var(--sidebar-bg);backdrop-filter:var(--glass-blur);-webkit-backdrop-filter:var(--glass-blur);border-right:1px solid var(--glass-border);display:flex;flex-direction:column;position:fixed;top:0;left:0;bottom:0;z-index:100;transition:transform .3s cubic-bezier(.4,0,.2,1)}
.sidebar.hide{transform:translateX(-100%)}
.sb-hd{padding:20px 16px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px}
.sb-av{width:40px;height:40px;border-radius:12px;background:var(--accent-g);display:flex;align-items:center;justify-content:center;font-size:20px;box-shadow:0 4px 15px rgba(108,159,255,.3)}
.sb-tt{font-size:15px;font-weight:700;line-height:1.2;background:var(--accent-g);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.sb-sub{font-size:10px;color:var(--text3);margin-top:2px}
.sb-nav{flex:1;overflow-y:auto;padding:10px 8px}
.ns{font-size:9px;color:var(--text3);text-transform:uppercase;letter-spacing:1.5px;padding:16px 12px 6px;font-weight:600}
.ni{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:var(--rs);cursor:pointer;color:var(--text2);font-size:13px;border:none;background:none;width:100%;transition:all .2s;position:relative;font-weight:500}
.ni:hover{background:var(--bg3);color:var(--text);transform:translateX(3px)}
.ni.ac{background:linear-gradient(135deg,rgba(108,159,255,.15),rgba(167,139,250,.1));color:var(--accent);font-weight:600;box-shadow:inset 3px 0 0 var(--accent)}
.ni .ic{font-size:17px;width:24px;text-align:center;flex-shrink:0}
.ni .bd{margin-left:auto;background:var(--red);color:#fff;font-size:9px;padding:2px 7px;border-radius:10px;font-weight:700;display:none;animation:badgePop .3s}
.sb-ft{padding:12px;border-top:1px solid var(--border);font-size:10px;color:var(--text3);text-align:center;line-height:1.5}
@keyframes badgePop{0%{transform:scale(0)}50%{transform:scale(1.2)}100%{transform:scale(1)}}

/* ── MAIN ── */
.main{margin-left:240px;flex:1;padding:28px 32px;max-width:calc(100vw - 240px);min-width:0;position:relative;z-index:10;animation:fadeIn .3s ease}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.page{display:none}
.page.on{display:block}
.ph{margin-bottom:24px}
.ph h1{font-size:24px;font-weight:800;letter-spacing:-.3px}
.ph p{color:var(--text2);font-size:12px;margin-top:4px}

/* ── STAT CARDS ── */
.sr{display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:14px;margin-bottom:24px}
.sc{background:var(--glass);backdrop-filter:var(--glass-blur);-webkit-backdrop-filter:var(--glass-blur);border:1px solid var(--glass-border);border-radius:var(--r);padding:18px;display:flex;align-items:center;gap:14px;transition:all .3s cubic-bezier(.4,0,.2,1);cursor:default;position:relative;overflow:hidden}
.sc:hover{transform:translateY(-2px);box-shadow:var(--shadow-lg);border-color:var(--border2)}
.si{width:44px;height:44px;border-radius:12px;display:flex;align-items:center;justify-content:center;font-size:20px;flex-shrink:0;transition:transform .2s}
.sc:hover .si{transform:scale(1.1)}
.si.bl{background:linear-gradient(135deg,rgba(108,159,255,.2),rgba(108,159,255,.05));color:var(--accent)}
.si.gn{background:linear-gradient(135deg,rgba(52,211,153,.2),rgba(52,211,153,.05));color:var(--green)}
.si.or{background:linear-gradient(135deg,rgba(251,191,36,.2),rgba(251,191,36,.05));color:var(--orange)}
.si.pk{background:linear-gradient(135deg,rgba(244,114,182,.2),rgba(244,114,182,.05));color:var(--pink)}
.si.rd{background:linear-gradient(135deg,rgba(248,113,113,.2),rgba(248,113,113,.05));color:var(--red)}
.si.pp{background:linear-gradient(135deg,rgba(167,139,250,.2),rgba(167,139,250,.05));color:var(--purple)}
.sv{font-size:22px;font-weight:800;letter-spacing:-.5px;line-height:1}
.sl{font-size:11px;color:var(--text3);margin-top:2px;font-weight:500}

/* ── PANEL CARDS ── */
.pc{background:var(--glass);backdrop-filter:var(--glass-blur);-webkit-backdrop-filter:var(--glass-blur);border:1px solid var(--glass-border);border-radius:var(--r);padding:20px;margin-bottom:16px;transition:all .3s cubic-bezier(.4,0,.2,1);position:relative;overflow:hidden}
.pc:hover{border-color:var(--border2)}
.pc h3{font-size:14px;margin-bottom:14px;display:flex;align-items:center;gap:8px;font-weight:700}
.dot{width:8px;height:8px;border-radius:50%;display:inline-block;transition:background .3s}
.dot.on{background:var(--green);box-shadow:0 0 8px rgba(52,211,153,.5)}
.dot.off{background:var(--text3)}

/* ── TABLE ── */
.tb{width:100%;border-collapse:collapse;font-size:12px}
.tb th{text-align:left;padding:10px 12px;color:var(--text3);font-weight:700;font-size:10px;text-transform:uppercase;letter-spacing:.8px;border-bottom:2px solid var(--border);background:rgba(30,41,59,.5)}
.tb td{padding:10px 12px;border-bottom:1px solid rgba(42,58,80,.3);max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;transition:background .15s}
.tb tr:hover td{background:rgba(108,159,255,.05)}
.tb .mono{font-family:"SF Mono","Fira Code","JetBrains Mono",monospace;font-size:11px;color:var(--text2)}

/* ── BUTTONS ── */
.btn{display:inline-flex;align-items:center;gap:6px;padding:8px 16px;border-radius:var(--rs);font-size:12px;font-weight:600;cursor:pointer;border:none;transition:all .2s cubic-bezier(.4,0,.2,1);white-space:nowrap;position:relative;overflow:hidden}
.btn::after{content:'';position:absolute;inset:0;background:rgba(255,255,255,0);transition:background .2s}
.btn:hover::after{background:rgba(255,255,255,.1)}
.btn:active{transform:scale(.97)}
.btn-pr{background:var(--accent-g);color:#fff;box-shadow:0 2px 10px rgba(108,159,255,.3)}
.btn-pr:hover{box-shadow:0 4px 20px rgba(108,159,255,.4);transform:translateY(-1px)}
.btn-suc{background:var(--green-g);color:#fff;box-shadow:0 2px 10px rgba(52,211,153,.3)}
.btn-suc:hover{box-shadow:0 4px 20px rgba(52,211,153,.4);transform:translateY(-1px)}
.btn-dan{background:linear-gradient(135deg,#f87171,#e05560);color:#fff;box-shadow:0 2px 10px rgba(248,113,113,.3)}
.btn-dan:hover{box-shadow:0 4px 20px rgba(248,113,113,.4);transform:translateY(-1px)}
.btn-out{background:transparent;border:1px solid var(--border);color:var(--text2)}
.btn-out:hover{border-color:var(--accent);color:var(--accent);background:rgba(108,159,255,.05)}
.btn-sm{padding:5px 12px;font-size:11px;border-radius:6px}
.btn-lg{padding:11px 24px;font-size:14px;border-radius:var(--rs2)}
.btn-grp{display:flex;gap:8px;flex-wrap:wrap;margin-top:12px}
.btn:disabled{opacity:.4;cursor:not-allowed;transform:none!important;box-shadow:none!important}
.mode-row{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin:6px 0 2px}
.mode-row label{font-size:13px;font-weight:700;color:var(--text2)}
.sel{background:var(--bg2);color:var(--text);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font-size:13px;font-family:inherit;cursor:pointer;outline:none}
.sel:focus{border-color:var(--accent)}
.mode-hint{font-size:11px;color:var(--text3)}

/* ── FORMS ── */
.fg{margin-bottom:14px}
.fg label{display:block;font-size:11px;font-weight:700;color:var(--text3);margin-bottom:4px;text-transform:uppercase;letter-spacing:.5px}
.fg input,.fg textarea,.fg select{width:100%;padding:9px 12px;background:var(--bg3);border:1px solid var(--border);border-radius:var(--rs);color:var(--text);font-size:13px;font-family:inherit;outline:none;transition:all .2s}
.fg input:focus,.fg textarea:focus,.fg select:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(108,159,255,.15);background:var(--bg4)}
.fg input:hover,.fg textarea:hover,.fg select:hover{border-color:var(--border2)}
.fg textarea{resize:vertical;min-height:80px;font-family:"SF Mono","Fira Code","JetBrains Mono",monospace;font-size:12px;line-height:1.5}
.fg select{cursor:pointer;appearance:none;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%238899b0' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 10px center}
.fr{display:grid;grid-template-columns:1fr 1fr;gap:14px}
@media(max-width:600px){.fr{grid-template-columns:1fr}}

/* ── TOGGLE SWITCH ── */
.toggle-sw{display:flex;align-items:center;gap:10px;cursor:pointer;user-select:none}
.toggle-sw input{display:none}
.toggle-track{width:40px;height:22px;background:var(--bg4);border-radius:11px;position:relative;transition:all .25s cubic-bezier(.4,0,.2,1);border:1px solid var(--border);flex-shrink:0}
.toggle-track::after{content:'';position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:var(--text3);transition:all .25s cubic-bezier(.68,-.55,.265,1.55);box-shadow:0 1px 3px rgba(0,0,0,.3)}
.toggle-sw input:checked+.toggle-track{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;box-shadow:0 0 16px rgba(108,159,255,.35)}
.toggle-sw input:checked+.toggle-track::after{left:20px;background:#fff;transform:scale(1.1)}
.toggle-sw .toggle-label{font-size:13px;color:var(--text2);font-weight:500}

/* ── TAGS ── */
.tg{display:inline-flex;align-items:center;gap:4px;padding:3px 10px;border-radius:20px;font-size:10px;font-weight:700;letter-spacing:.3px}
.tg-suc{background:rgba(52,211,153,.12);color:var(--green)}
.tg-war{background:rgba(251,191,36,.12);color:var(--orange)}
.tg-dan{background:rgba(248,113,113,.12);color:var(--red)}
.tg-inf{background:rgba(108,159,255,.12);color:var(--accent)}

/* ── LOG VIEWER ── */
.log-box{background:#060a12;border:1px solid var(--border);border-radius:var(--rs);padding:14px;max-height:360px;overflow-y:auto;font-family:"SF Mono","Fira Code","JetBrains Mono",monospace;font-size:11px;line-height:1.6;white-space:pre-wrap;word-break:break-all;color:#8fa8c8}
.log-box::-webkit-scrollbar-thumb{background:#1a2535}

/* ── JSON EDITOR ── */
.je{width:100%;min-height:400px;background:#060a12;border:1px solid var(--border);border-radius:var(--rs);color:var(--green);font-family:"SF Mono","Fira Code","JetBrains Mono",monospace;font-size:12px;padding:14px;resize:vertical;outline:none;line-height:1.6;transition:border-color .2s}
.je:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(108,159,255,.1)}

/* ── CONFIG QUICK EDIT ── */
.fs{border:1px solid var(--border);border-radius:var(--rs);padding:16px;margin-bottom:14px}
.fs legend{font-size:14px;font-weight:700;padding:0 8px;color:var(--accent)}

/* ── QR ── */
.qr-wrap{text-align:center;padding:24px}
.qr-wrap img{max-width:220px;border-radius:12px;border:4px solid #fff;box-shadow:var(--shadow-lg)}
.qr-wrap .qr-status{margin-top:12px;font-size:14px;font-weight:700}

/* ── TOAST ── */
.toast{position:fixed;top:20px;right:20px;z-index:9999;padding:12px 20px;border-radius:var(--rs2);font-size:13px;font-weight:600;opacity:0;transform:translateY(-16px) scale(.95);transition:all .3s cubic-bezier(.4,0,.2,1);pointer-events:none;max-width:320px;box-shadow:var(--shadow-lg);backdrop-filter:blur(12px)}
.toast.show{opacity:1;transform:translateY(0) scale(1)}
.toast.ok{background:rgba(52,211,153,.9);color:#fff}
.toast.err{background:rgba(248,113,113,.9);color:#fff}
.toast.inf{background:rgba(108,159,255,.9);color:#fff}

/* ── EMPTY STATE ── */
.emp{text-align:center;padding:40px 20px;color:var(--text3)}
.emp .ic{font-size:40px;margin-bottom:10px;display:block}
.emp p{font-size:13px}

/* ── MOBILE ── */
.mob-toggle{display:none;position:fixed;top:12px;left:12px;z-index:200;background:var(--glass);backdrop-filter:blur(12px);border:1px solid var(--glass-border);color:var(--text);width:40px;height:40px;border-radius:var(--rs);align-items:center;justify-content:center;cursor:pointer;font-size:18px;transition:all .2s}
.mob-toggle:hover{background:var(--bg3)}
.mob-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);backdrop-filter:blur(4px);z-index:99}
@media(max-width:768px){
.sidebar{transform:translateX(-100%)}
.sidebar.show{transform:translateX(0)}
.main{margin-left:0;max-width:100%;padding:16px 14px;padding-top:56px;padding-bottom:max(16px,env(safe-area-inset-bottom));position:relative;z-index:10}
.sr{grid-template-columns:repeat(2,1fr);gap:10px}
.sc{padding:14px;gap:10px;min-height:50px}
.si{width:36px;height:36px;font-size:17px}
.sv{font-size:17px}
.mob-toggle{display:flex}
.mob-overlay.show{display:block}
.ph h1{font-size:20px}
.tb{font-size:11px}
.tb td{max-width:120px;padding:7px 8px}
.pc{padding:14px}
.btn{padding:9px 18px;font-size:13px}
.btn-sm{padding:6px 12px}
.fg input,.fg textarea,.fg select{padding:10px 12px;font-size:13px}
.ni{padding:12px 14px;font-size:14px}
.log-box{max-height:220px;font-size:10px}
.je{min-height:260px}
.toast{left:14px;right:14px;max-width:none;top:auto;bottom:16px;transform:translateY(16px) scale(.95)}
.toast.show{transform:translateY(0) scale(1)}
}
@media(max-width:400px){
.sr{grid-template-columns:1fr}
.sc{padding:12px}
.main{padding:12px 10px;padding-top:56px;position:relative;z-index:10}
.ph h1{font-size:18px}
}

/* ── ANIMATIONS ── */
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
.pulse{animation:pulse 1.5s ease-in-out infinite}
@keyframes spin{from{transform:rotate(0deg)}to{transform:rotate(360deg)}}

/* ── MONITOR GRID ── */
.mon-grid{display:grid;grid-template-columns:320px 1fr;gap:20px;align-items:start}
@media(max-width:768px){.mon-grid{grid-template-columns:1fr}}

/* ── TOGGLE SWITCH ── */
.toggle-sw{display:inline-flex;align-items:center;cursor:pointer;user-select:none;gap:6px}
.toggle-sw input{display:none}
.toggle-track{position:relative;width:40px;height:22px;border-radius:11px;background:var(--bg3);border:1px solid var(--glass-border);transition:all .3s ease;flex-shrink:0}
.toggle-track::after{content:'';position:absolute;top:2px;left:2px;width:16px;height:16px;border-radius:50%;background:var(--text3);transition:all .3s cubic-bezier(.68,-.55,.265,1.55)}
.toggle-sw input:checked+.toggle-track{background:linear-gradient(135deg,var(--accent),var(--accent2));border-color:transparent;box-shadow:0 0 12px rgba(91,141,239,.4)}
.toggle-sw input:checked+.toggle-track::after{left:20px;background:#fff;transform:scale(1.1)}

/* ── PAGE ANIMATIONS ── */
@keyframes slideUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}

/* ── SCROLLBAR ── */
::-webkit-scrollbar{width:6px;height:6px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:var(--glass-border);border-radius:3px}
::-webkit-scrollbar-thumb:hover{background:var(--text3)}
.log-box::-webkit-scrollbar{width:4px}
.log-box::-webkit-scrollbar-thumb{background:var(--border);border-radius:2px}

/* ── SELECTION ── */
::selection{background:rgba(91,141,239,.3);color:#fff}

/* ── EXTRA REFINEMENTS ── */
.ph h1{color:var(--accent)}
.sc{transition:all .25s ease}
.sc:hover{transform:translateY(-2px);box-shadow:0 8px 24px rgba(0,0,0,.3)}
.pc{transition:border-color .3s ease,box-shadow .3s ease}
.pc:hover{border-color:rgba(91,141,239,.2)}
.log-box{background:rgba(6,10,16,.8);backdrop-filter:blur(4px)}

/* ── CHART GRID ── */
.chart-grid{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:20px}
.chart-card{background:var(--bg2);border:1px solid var(--border);border-radius:var(--r);padding:18px;transition:all .2s;overflow:hidden;position:relative}
.chart-card:hover{border-color:var(--accent);box-shadow:0 0 20px rgba(91,141,239,.08)}
.chart-card h4{font-size:13px;margin:0 0 12px;color:var(--text);font-weight:500}
.chart-card canvas{max-height:220px;width:100%!important;height:200px!important}
@media(max-width:768px){.chart-grid{grid-template-columns:1fr;gap:12px}}
@media(max-width:400px){.chart-card{padding:12px}.chart-card canvas{max-height:180px;height:160px!important}}
</style>
</head>
<body>
<div class="bg-layer" id="bgLayer"><div class="bg-default"></div></div>
<div class="overlay" id="overlay"></div>
<canvas id="ambientCanvas"></canvas>

<button class="mob-toggle" onclick="toggleSidebar()">☰</button>
<div class="mob-overlay" id="mobOverlay" onclick="toggleSidebar()"></div>

<!-- SIDEBAR -->
<aside class="sidebar" id="sidebar">
<div class="sb-hd">
<div class="sb-av">⚡</div><div><div class="sb-tt">{{ACCOUNT_HEADER}}</div><div class="sb-sub">B站 AI 管理系统</div></div>
</div>
<nav class="sb-nav">
<div class="ns">总览</div>
<button class="ni ac" data-pg="dash" onclick="nav('dash',this)"><span class="ic">📊</span>仪表盘</button>
<button class="ni" data-pg="ctrl" onclick="nav('ctrl',this)"><span class="ic">🎮</span>机器人控制<span class="bd" id="botBadge">●</span></button>
<button class="ni" data-pg="monitor" onclick="nav('monitor',this)"><span class="ic">📡</span>实时监听<span class="bd" id="monitorBadge">●</span></button>
<button class="ni" data-pg="login" onclick="nav('login',this)"><span class="ic">🔑</span>B站登录<span class="bd" id="loginBadge">●</span></button>
<div class="ns">系统配置</div>
<button class="ni" data-pg="conf" onclick="nav('conf',this)"><span class="ic">⚙️</span>配置编辑</button>
<button class="ni" data-pg="psna" onclick="nav('psna',this)"><span class="ic">🎭</span>人格管理</button>
<button class="ni" data-pg="mood" onclick="nav('mood',this)"><span class="ic">💡</span>心情管理</button>
<button class="ni" data-pg="behavior" onclick="nav('behavior',this)"><span class="ic">⚡</span>行为设置</button>
<button class="ni" data-pg="upfu" onclick="nav('upfu',this)"><span class="ic">👥</span>UP主关注</button>
<div class="ns">数据监控</div>
<button class="ni" data-pg="cmts" onclick="nav('cmts',this)"><span class="ic">💬</span>评论日志</button>
<button class="ni" data-pg="usrs" onclick="nav('usrs',this)"><span class="ic">👤</span>用户画像</button>
<button class="ni" data-pg="mem" onclick="nav('mem',this)"><span class="ic">🧠</span>记忆知识库</button>
<button class="ni" data-pg="diary" onclick="nav('diary',this)"><span class="ic">📖</span>日记进化</button>
<button class="ni" data-pg="acts" onclick="nav('acts',this)"><span class="ic">📋</span>操作日志</button>
<div class="ns">工具</div>
<button class="ni" data-pg="tutor" onclick="nav('tutor',this)"><span class="ic">🎓</span>知识辅导</button>
<button class="ni" data-pg="tools" onclick="nav('tools',this)"><span class="ic">🔧</span>功能中心</button>
<button class="ni" data-pg="sys" onclick="nav('sys',this)"><span class="ic">💾</span>系统管理</button>
<div class="ns">帮助</div>
<button class="ni" data-pg="about" onclick="nav('about',this)"><span class="ic">ℹ️</span>关于</button>
</nav>
<div class="sb-ft">已运行 <span id="uptime">--</span><div style="color:var(--red);font-size:9px;margin-top:4px">⚡ 仅供学习参考</div></div>
</aside>

<!-- MAIN -->
<main class="main">

<!-- DASHBOARD -->
<div class="page on" id="pg-dash">
<div class="ph"><h1>📊 系统仪表盘</h1><p>实时监控 · 数据可视化 · 运行状态</p></div>
<div class="sr" id="dashStats"></div>
<div class="chart-grid">
<div class="chart-card"><h4>📈 评论活跃度趋势</h4><canvas id="chartComments"></canvas></div>
<div class="chart-card"><h4>💡 心情/精力指数</h4><canvas id="chartMood"></canvas></div>
<div class="chart-card"><h4>📅 每日操作统计</h4><canvas id="chartActions"></canvas></div>
<div class="chart-card"><h4>🔍 视频处理速率</h4><canvas id="chartVideos"></canvas></div>
</div>
<div class="pc"><h3><span class="dot" id="botDot"></span>系统详情</h3><div id="botDetail"></div></div>
<div class="pc"><h3>📁 数据文件状态</h3><div id="fileGrid" class="file-grid"></div></div>
<div class="disclaimer">⚠ 免责声明：本项目仅供学习参考，若因使用本项目产生的任何后果，本人一律概不负责。</div>
</div>

<!-- MONITOR -->
<div class="page" id="pg-monitor">
<div class="ph"><h1>📡 实时监听</h1><p>不刷视频 · 专盯私信+评论 · 实时AI回复</p></div>

<!-- 状态卡片 -->
<div class="sr" id="monitorStats"></div>

<!-- 控制栏 -->
<div class="pc" style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px">
<div style="display:flex;align-items:center;gap:12px">
<div id="monitorStatus"></div>
<div id="monitorUptime" class="msg-inline"></div>
</div>
<div class="btn-grp" style="margin:0">
<button class="btn btn-suc btn-lg" id="btnMonitorStart" onclick="startMonitor()">▶ 启动监听</button>
<button class="btn btn-dan btn-lg" id="btnMonitorStop" style="display:none" onclick="stopMonitor()">⏹ 停止</button>
<button class="btn btn-out" onclick="refreshMonitor()">🔄 刷新</button>
</div>
</div>

<!-- 配置 + 日志 双栏 -->
<div class="mon-grid">
<!-- 左：配置 -->
<div>
<div class="pc">
<h3>⚙️ 监听配置</h3>
<div class="fg"><label>评论检查间隔 (秒)</label><input id="monCmtInterval" type="number" min="30" value="120"></div>
<div class="fg"><label>私信检查间隔 (秒)</label><input id="monMsgInterval" type="number" min="10" value="60"></div>
<div class="fg"><label>每次最大回复数</label><input id="monMaxReplies" type="number" min="1" max="20" value="5"></div>
<div class="fg"><label>自动回复</label>
<select id="monAutoReply"><option value="true">✅ 开启 — AI拟好直接发送</option><option value="false">📝 关闭 — 仅拟回复不发送</option></select>
</div>
<div style="display:flex;align-items:center;gap:10px;margin-top:14px">
<button class="btn btn-pr" onclick="saveMonitorConfig()">💾 保存配置</button>
<span id="monCfgMsg" class="msg-inline"></span>
</div>
</div>
<div class="pc">
<h3>💡 说明</h3>
<p class="form-hint" style="line-height:1.7">
独立于视频刷取的监听模式。<br>
启动后只盯私信和评论，有新消息立刻AI回复。<br>
不会刷视频、不消耗精力。<br>
<span style="color:var(--orange)">⚠ 与机器人主进程互斥，不能同时运行。</span>
</p>
</div>
</div>
<!-- 右：日志 -->
<div class="pc" style="min-height:420px;display:flex;flex-direction:column">
<h3 style="display:flex;align-items:center;justify-content:space-between">
<span>📡 实时日志</span>
<span id="monitorLogCount" class="msg-inline" style="font-weight:400"></span>
</h3>
<div class="log-box" id="monitorLog" style="flex:1;min-height:340px">等待启动...</div>
</div>
</div>
</div>

<!-- CONTROL -->
<div class="page" id="pg-ctrl">
<div class="ph"><h1>🎮 机器人控制</h1><p>启动/停止/重启</p></div>
<div class="pc">
<h3>🤖 运行状态</h3><div id="ctrlStatus" style="margin-bottom:12px"></div>
<div class="mode-row">
  <label for="botMode">启动模式：</label>
  <select id="botMode" class="sel">
    <option value="current">按已保存配置运行（默认）</option>
    <option value="smart">💡 智能省token（长时挂机/省钱）</option>
  </select>
  <span class="mode-hint">按已保存的配置运行</span>
</div>
<div class="btn-grp">
<button class="btn btn-suc btn-lg" id="btnStart" onclick="startBot()">▶ 启动机器人</button>
<button class="btn btn-dan btn-lg" id="btnStop" style="display:none" onclick="stopBot()">⏹ 停止</button>
<button class="btn btn-out" onclick="restartBot()">🔄 重启</button>
<button class="btn btn-out" onclick="clearLog()">🗑 清空日志</button>
</div>
</div>
<div class="pc"><h3>📡 实时输出</h3><div class="log-box" id="botLog">等待输出...</div></div>
<div class="disclaimer">⚠ 免责声明：本项目仅供学习参考，若因使用本项目产生的任何后果，本人一律概不负责。</div>
</div>

<!-- LOGIN -->
<div class="page" id="pg-login">
<div class="ph"><h1>🔑 B站登录</h1><p>扫码登录 / 登出 / 状态</p></div>
<div class="pc" id="loginPanel">
<h3>📱 扫码登录</h3>
<div id="loginStatus"></div>
<div id="qrArea" style="display:none">
<div class="qr-wrap"><img id="qrImg" src="" alt="QR码"><div class="qr-status" id="qrStatusText"></div></div>
</div>
<div class="btn-grp">
<button class="btn btn-suc btn-lg" id="btnQR" onclick="startQRLogin()">📷 生成登录二维码</button>
<button class="btn btn-dan" id="btnLogout" onclick="logoutBili()">🚪 退出登录</button>
<button class="btn btn-out" onclick="checkLogin()">🔍 检查状态</button>
</div>
<div id="cookieInfo" style="margin-top:12px;font-size:11px;color:var(--text2)"></div>
</div>
</div>

<!-- CONFIG -->
<div class="page" id="pg-conf">
<div class="ph"><h1>⚙️ 配置编辑</h1><p>用户数据目录 / config.json</p></div>
<!-- 可视化快捷配置 -->
<div class="pc" id="confQuickBox">
<h3>📋 快捷配置 <span style="font-size:11px;font-weight:400;color:var(--text2);margin-left:10px">
<button class="btn btn-sm btn-out" onclick="toggleConfMode()" style="font-size:10px;padding:2px 8px">📝 切换到 JSON 编辑器</button>
</span></h3>
<div id="confQuickContent"></div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveConfQuick()">💾 保存快捷配置</button><span id="confQuickMsg" class="msg-inline"></span></div>
</div>
<!-- 原始 JSON 编辑器（默认隐藏） -->
<div class="pc" id="confJsonBox" style="display:none">
<h3>📄 原始 JSON <span style="font-size:11px;font-weight:400;color:var(--text2);margin-left:10px">
<button class="btn btn-sm btn-out" onclick="toggleConfMode()" style="font-size:10px;padding:2px 8px">🔙 切换到快捷配置</button>
</span></h3>
<textarea class="je" id="confEd"></textarea>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveConf()">💾 保存</button><button class="btn btn-out" onclick="loadConf()">🔄 重新加载</button></div>
</div>
</div>

<!-- PERSONA -->
<div class="page" id="pg-psna">
<div class="ph"><h1>🎭 人格管理</h1><p>管理机器人对话人格</p></div>
<div id="psnaList"></div>
</div>

<!-- COMMENTS -->
<div class="page" id="pg-cmts">
<div class="ph"><h1>💬 评论日志</h1><p>最近评论互动</p></div>
<div class="pc"><div id="cmtTab"></div></div>
</div>

<!-- USERS -->
<div class="page" id="pg-usrs">
<div class="ph"><h1>👤 用户画像</h1><p>好感度与印象</p></div>
<div class="pc"><div id="usrTab"></div></div>
</div>

<!-- MEMORY -->
<div class="page" id="pg-mem">
<div class="ph"><h1>🧠 记忆 & 知识库</h1></div>
<div id="memBox"></div>
</div>

<!-- DIARY -->
<div class="page" id="pg-diary">
<div class="ph"><h1>📖 日记 & 进化</h1></div>
<div id="diaryBox"></div>
</div>

<!-- ACTIONS -->
<div class="page" id="pg-acts">
<div class="ph"><h1>📋 操作日志</h1></div>
<div class="pc"><div id="actTab"></div></div>
</div>

<!-- MOOD -->
<div class="page" id="pg-mood">
<div class="ph"><h1>💡 心情管理</h1><p>查看/切换机器人心情状态</p></div>
<div class="pc"><h3>当前状态</h3><div id="moodStatus"></div></div>
<div class="pc"><h3>⚡ 快速切换心情</h3>
<div class="btn-grp" id="moodQuickBtns"></div>
</div>
<div class="pc"><h3>⚙️ 心情设置</h3>
<div class="fg"><label>默认心情</label><input id="moodDefault" placeholder="平静"></div>
<div class="fr">
<div class="fg"><label><input type="checkbox" id="moodRandom" onchange="moodToggleRandom()"> 随机心情切换</label></div>
<div class="fg"><label>随机间隔(分钟)</label><input id="moodRandInt" type="number" min="1" max="120"></div>
</div>
<div class="fr">
<div class="fg"><label><input type="checkbox" id="moodCustom" onchange="moodToggleCustom()"> 自定义心情</label></div>
<div class="fg"><label>自定义心情文字</label><input id="moodCustomText"></div>
</div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveMood()">💾 保存设置</button></div>
</div>
</div>

<!-- BEHAVIOR -->
<div class="page" id="pg-behavior">
<div class="ph"><h1>⚡ 行为设置</h1><p>AI免责声明 · 精力管理 · 评论模式</p></div>
<div class="pc"><h3>🤖 AI免责声明</h3>
<p class="form-hint">所有评论/私信回复末尾会追加免责声明标签。关闭后不再添加，但建议保持开启以遵守平台规定。</p>
<div class="fr" style="align-items:center;margin-bottom:8px">
<label class="toggle-sw"><input type="checkbox" id="aiMarkerOn" onchange="toggleAiMarker()"><span class="toggle-track"></span><span style="margin-left:10px;font-size:13px">启用免责声明</span></label>
</div>
<div class="fg"><label>免责声明文字</label><input id="aiMarkerText" placeholder="（内容由AI生成并由AI回复）" maxlength="50" style="max-width:300px"></div>
<div class="btn-grp"><button class="btn btn-pr" id="btnSaveMarker" onclick="saveAiMarker()">💾 保存</button><span id="aiMarkerMsg" class="msg-inline"></span></div>
</div>
<div class="pc"><h3>⚡ 精力设置</h3>
<p class="form-hint">控制AI机器人精力恢复速度和行为间隔。</p>
<div class="energy-grid">
<div class="fg"><label>最大精力值</label><input id="engMaxEnergy" type="number" min="50" max="500" style="max-width:100px"></div>
<div class="fg"><label>每轮恢复(最小)</label><input id="engRecoverMin" type="number" min="1" max="50" style="max-width:100px"></div>
<div class="fg"><label>每轮恢复(最大)</label><input id="engRecoverMax" type="number" min="1" max="50" style="max-width:100px"></div>
<div class="fg"><label>恢复轮数(最小)</label><input id="engRoundsMin" type="number" min="1" max="20" style="max-width:100px"></div>
<div class="fg"><label>恢复轮数(最大)</label><input id="engRoundsMax" type="number" min="1" max="20" style="max-width:100px"></div>
<div class="fg"><label>轮间间隔(秒,最小)</label><input id="engRoundIntMin" type="number" min="10" max="600" style="max-width:100px"></div>
<div class="fg"><label>轮间间隔(秒,最大)</label><input id="engRoundIntMax" type="number" min="10" max="600" style="max-width:100px"></div>
<div class="fg"><label>视频间隔(秒,最小)</label><input id="engVideoIntMin" type="number" min="5" max="300" style="max-width:100px"></div>
<div class="fg"><label>视频间隔(秒,最大)</label><input id="engVideoIntMax" type="number" min="5" max="300" style="max-width:100px"></div>
</div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveEnergy()">💾 保存精力设置</button><span id="engMsg" class="msg-inline"></span></div>
</div>
<div class="pc"><h3>💬 评论模式</h3>
<div class="radio-group">
<label><input type="radio" name="cmtMode" value="real" onchange="saveCommentMode()"> 真实模式 (发送到B站)</label>
<label><input type="radio" name="cmtMode" value="simulate" onchange="saveCommentMode()"> 模拟模式 (仅记录日志)</label>
</div>
<span id="cmtModeMsg" class="msg-inline"></span>
</div>

	<div class="pc"><h3>🛡️ 关键词安全校验</h3>
	<p class="form-hint">开启后AI会过滤涉及敏感关键词的评论和回复。关闭后不再进行关键词检查（风险自负）。</p>
	<div class="fr" style="align-items:center;margin-bottom:10px">
	<label class="toggle-sw"><input type="checkbox" id="safetyEnabled" onchange="toggleSafety()"><span class="toggle-track"></span><span style="margin-left:10px;font-size:13px">启用关键词校验</span></label>
	</div>
	<div id="safetyKwSection" style="display:none">
	<p class="form-hint" style="margin-bottom:6px">当前屏蔽关键词（一行一个）：</p>
	<textarea id="safetyKeywords" class="kw-textarea"></textarea>
	<div class="btn-grp" style="margin-top:8px">
	<button class="btn btn-pr" onclick="saveSafetyKeywords()">💾 保存关键词</button>
	<button class="btn btn-out btn-sm" onclick="addSafetyKeyword()">+ 添加关键词</button>
	</div>
	<div class="fg" style="margin-top:8px"><label>快速添加关键词</label>
	<div style="display:flex;gap:6px"><input id="newSafetyKw" placeholder="输入新关键词" style="flex:1"><button class="btn btn-out btn-sm" onclick="addSafetyKeyword()">添加</button></div>
	</div>
	<span id="safetyMsg" class="msg-inline"></span>
	</div>
	</div>
</div>

<!-- UPFOLLOW -->
<div class="page" id="pg-upfu">
<div class="ph"><h1>👥 UP主关注列表</h1><p>AI已关注的UP主</p></div>
<div class="pc"><div id="upfuTab"></div></div>
</div>

<!-- TOOLS -->
<div class="page" id="pg-tools">
<div class="ph"><h1>🔧 功能中心</h1><p>手动操作 · 任务队列</p></div>
<div class="pc"><h3>🎬 手动发送弹幕</h3>
<div class="fr"><div class="fg"><label>BV号</label><input id="danmakuBvid" placeholder="BV1xx411c7mD"></div><div class="fg"><label>弹幕内容 (≤20字)</label><input id="danmakuText" maxlength="20" placeholder="第~"></div></div>
<button class="btn btn-pr" onclick="sendDanmaku()">📤 发送弹幕</button>
</div>
<div class="pc"><h3>📹 手动视频分析</h3>
<div class="fr">
<div class="fg"><label>BV号 / 视频链接</label><input id="analyzeBvid" placeholder="BV1xx411c7mD 或 完整链接" style="min-width:260px"></div>
<div class="fg"><label>模式</label><select id="analyzeAnchor"><option value="visual_note" selected>图文学习笔记+目录</option><option value="classic">经典分析(评分归档)</option></select></div>
</div>
<div class="fg"><label>自定义提示词 (可选，图文笔记模式)</label><input id="analyzePrompt" placeholder="默认：完整全过程讲解。可追加要求：更口语化、突出技术要点、输出表格..."></div>
<button class="btn btn-pr" onclick="analyzeVideo()">🔍 开始分析</button>
<div id="analyzeResult" style="display:none;margin-top:16px"></div>
</div>
<div class="pc"><h3>🤖 Agent 技能</h3>
<div class="fg"><label>目标描述（用自然语言描述你想让AI做什么）</label><input id="agentGoal" placeholder="例如：搜索"深度学习入门"并总结前3个视频"></div>
<button class="btn btn-pr" onclick="runAgent()">🚀 执行Agent</button>
</div>
<div class="pc"><h3>📚 知识库操作</h3>
<div class="btn-grp">
<button class="btn btn-pr" onclick="kbOrganize()">📂 一键整理知识库</button>
<button class="btn btn-out" onclick="kbRevisit()">📖 复习已学内容</button>
<button class="btn btn-out" onclick="rf_kbStats()">📊 查看统计</button>
</div>
<div id="kbStatBox" style="margin-top:12px;font-size:12px"></div>
</div>

<div class="pc"><h3>🎙️ ASR 语音识别设置</h3>
<p class="form-hint">语音识别引擎配置（FunASR / Whisper）。</p>
<div class="fr">
<div class="fg"><label>启用ASR</label><select id="asrEnabled"><option value="1">开启</option><option value="0">关闭</option></select></div>
<div class="fg"><label>识别引擎</label><select id="asrBackend"><option value="funasr">FunASR（推荐）</option><option value="whisper">Whisper</option></select></div>
<div class="fg"><label>语言</label><input id="asrLang" placeholder="zh" style="max-width:80px"></div>
<div class="fg"><label>说话人分离</label><select id="asrSep"><option value="1">开启</option><option value="0">关闭</option></select></div>
</div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveAsr()">💾 保存ASR设置</button><span id="asrMsg" class="msg-inline"></span></div>
</div>
<div class="pc"><h3>⭐ Highlights 归档设置</h3>
<p class="form-hint">高分视频自动备份到 highlights/ 目录。</p>
<div class="fr">
<div class="fg"><label>启用归档</label><select id="dryEnabled"><option value="1">开启</option><option value="0">关闭</option></select></div>
<div class="fg"><label>最低评分门槛</label><input id="dryMinScore" type="number" min="5" max="10" step="0.5" value="8.0" style="max-width:100px"></div>
<div class="fg"><label>归档文件夹名</label><input id="dryFolder" placeholder="highlights" style="max-width:200px"></div>
</div>
<div class="btn-grp"><button class="btn btn-pr" onclick="saveDry()">💾 保存归档设置</button><span id="dryMsg" class="msg-inline"></span></div>
</div>
</div>

<!-- TUTOR (v2.0.3) -->
<div class="page" id="pg-tutor">
<div class="ph"><h1>🎓 知识辅导</h1><p>选择知识文件 → AI讲解/问答/二次创作/生成HTML</p></div>

<div class="pc"><h3>📂 选择知识文件</h3>
<div style="display:flex;gap:8px;align-items:flex-start;flex-wrap:wrap">
<select id="tutorFileSelect" multiple size="8" class="tutor-select">
</select>
<div style="display:flex;flex-direction:column;gap:5px">
<button class="btn btn-pr btn-sm" onclick="tutorLoadFile()">📖 加载选中</button>
<button class="btn btn-out btn-sm" onclick="tutorSelectAll()">☑ 全选</button>
<button class="btn btn-out btn-sm" onclick="tutorSelectNone()">☐ 取消</button>
<button class="btn btn-out btn-sm" onclick="rf_tutor()" style="margin-top:4px">🔄 刷新</button>
</div>
</div>
<div id="tutorFileInfo" style="margin-top:8px;font-size:11px;color:var(--text2)"></div>
<div class="btn-grp" id="tutorFileActions" style="margin-top:6px;display:none">
<button class="btn btn-pr btn-sm" onclick="tutorLoadFile()">📖 加载选中</button>
<button class="btn btn-out btn-sm" onclick="tutorSelectAll()">☑ 全选</button>
</div>
</div>

<div class="pc" id="tutorContentBox" style="display:none">
<h3>📄 文件内容预览 <span class="expand-toggle" onclick="var p=document.getElementById('tutorContentPre');p.style.display=p.style.display==='none'?'block':'none'">[展开/折叠]</span></h3>
<pre id="tutorContentPre" class="preview-pre" style="display:none"></pre>
</div>

<div class="pc" id="tutorChatBox" style="display:none">
<h3>💬 AI 辅导对话</h3>
<div id="tutorChatLog" class="chat-log">
<div style="color:var(--text2);text-align:center;padding:20px">AI导师已就绪，开始提问吧！</div>
</div>
<div class="tutor-input-wrap">
<textarea id="tutorInput" class="tutor-textarea" placeholder="输入你的问题..." onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();tutorSend('chat')}"></textarea>
<div class="tutor-btn-col">
<button class="btn btn-pr btn-sm" onclick="tutorSend('chat')">📤 提问</button>
<button class="btn btn-out btn-sm" onclick="tutorSend('rewrite')">✍️ 改写</button>
<button class="btn btn-out btn-sm" onclick="tutorSend('html')">🎨 HTML</button>
</div>
</div>
<div style="display:flex;gap:8px;align-items:center;margin-top:6px">
<span style="font-size:11px;color:var(--text2)">HTML风格:</span>
<select id="tutorHtmlStyle" class="tutor-select" style="padding:4px 8px;font-size:11px">
<option value="dark">暗色科技风</option>
<option value="light">清新白底风</option>
<option value="modern">现代极简风</option>
</select>
<span id="tutorStatus" class="msg-inline"></span>
</div>
</div>

<div class="pc" id="tutorResultBox" style="display:none">
<h3>📝 操作结果</h3>
<div id="tutorResultContent" style="font-size:12px"></div>
<div class="btn-grp" id="tutorResultActions" style="display:none"></div>
</div>
</div>

<!-- SYSTEM -->

<div class="page" id="pg-sys">
<div class="ph"><h1>💾 系统管理</h1><p>备份 · 恢复 · 重置</p></div>
<div class="pc"><h3>📤 创建备份</h3><p class="form-hint" style="margin-bottom:10px">配置会自动脱敏；按需勾选记忆、知识库和生成产物。</p>
<div class="check-list" id="backupOptions"></div>
<button class="btn btn-pr" onclick="exportConfig()">📤 创建所选备份</button>
<div id="exportMsg" style="margin-top:8px;font-size:12px"></div>
</div>
<div class="pc"><h3>📥 导入配置</h3><p class="form-hint" style="margin-bottom:10px">从备份文件恢复</p>
<button class="btn btn-out" onclick="listBackups()">🔍 刷新备份列表</button>
<div id="backupList" style="margin:10px 0;font-size:12px"></div>
</div>

<!-- THEME & BACKGROUND SETTINGS -->
<div class="pc" id="themeSettings">
<h3>🎨 主题 & 背景设置</h3>
<p class="form-hint">选择面板主题风格和自定义背景</p>
<div class="fg"><label>主题风格</label>
<select id="themeSelect" onchange="switchTheme(this.value)">
<option value="aurora">🌌 极光 (默认)</option>
<option value="cyberpunk">🤖 赛博朋克</option>
<option value="sakura">🌸 樱花</option>
<option value="galaxy">🌌 星空</option>
</select>
</div>
<div class="fg"><label>背景图片 URL</label>
<input id="bgImage" placeholder="https://example.com/bg.jpg 或留空使用默认渐变">
<p class="form-hint" style="margin-top:4px;margin-bottom:0">支持 JPG/PNG/GIF，建议分辨率 1920×1080+</p>
</div>
<div class="fg"><label>背景视频 URL</label>
<input id="bgVideo" placeholder="https://example.com/bg.mp4 (优先于图片)">
<p class="form-hint" style="margin-top:4px;margin-bottom:0">支持 MP4/WebM，优先级高于背景图片</p>
</div>
<div class="fg"><label>背景透明度</label>
<input id="bgOpacity" type="range" min="0" max="100" value="35" oninput="document.getElementById('bgOpacityVal').textContent=this.value+'%'">
<span id="bgOpacityVal" style="font-size:11px;color:var(--text2);margin-left:8px">35%</span>
</div>
<div class="btn-grp">
<button class="btn btn-pr" onclick="saveThemeSettings()">💾 保存设置</button>
<button class="btn btn-out" onclick="resetThemeSettings()">🔄 恢复默认</button>
<span id="themeMsg" class="msg-inline"></span>
</div>
</div>

<div class="pc danger-zone">
<h3 style="color:var(--red)">⚠ 恢复出厂设置</h3>
<p style="font-size:11px;color:var(--text2)">完整清除私人数据、账号凭据、日志、知识库与所有导出产物。此操作不可逆。</p>
<button class="btn btn-dan" onclick="factoryReset()">🔥 恢复出厂设置</button>
</div>
</div>

<!-- ABOUT -->
<div class="page" id="pg-about">
<div class="ph"><h1>ℹ️ 关于系统</h1><p>版本信息 · 技术栈 · 联系方式</p></div>
<div class="pc" id="aboutBox"></div>
<div class="disclaimer">⚠ 免责声明：本项目仅供学习参考，若因使用本项目产生的任何后果，本人一律概不负责。</div>
</div>

</main>

<div class="toast" id="toast"></div>

<script>
// ── NAV ──
function nav(p,el){
document.querySelectorAll('.page').forEach(x=>x.classList.remove('on'));
document.querySelectorAll('.ni').forEach(x=>x.classList.remove('ac'));
document.getElementById('pg-'+p).classList.add('on');
if(el)el.classList.add('ac');
if(window['rf_'+p])window['rf_'+p]();
// 移动端关闭侧边栏
if(window.innerWidth<768)toggleSidebar(true);
}
function toggleSidebar(force){
var s=document.getElementById('sidebar'),o=document.getElementById('mobOverlay');
if(typeof force=='boolean'){s.classList.toggle('show',force);o.classList.toggle('show',force)}
else{s.classList.toggle('show');o.classList.toggle('show')}
}

// ── TOAST ──
function toast(m,t){t=t||'inf';var x=document.getElementById('toast');x.textContent=m;x.className='toast '+t+' show';setTimeout(function(){x.classList.remove('show')},2200)}

// ── API ──
async function api(m,u,b){var o={method:m,headers:{'Content-Type':'application/json'}};if(b)o.body=JSON.stringify(b);var r=await fetch(u,o);return r.json()}

// ── CHART HELPERS ──
var _charts={};
function _destroyC(k){if(_charts[k]){_charts[k].destroy();_charts[k]=null}}
function _makeLine(canvasId,labels,datasets){
if(typeof Chart==='undefined'){var el=document.getElementById(canvasId);if(el)el.parentElement.querySelector('h4').textContent+=' ⚠(CDN加载失败)';return}
_destroyC(canvasId);
var ctx=document.getElementById(canvasId);if(!ctx)return;
_charts[canvasId]=new Chart(ctx,{
type:'line',data:{labels:labels,datasets:datasets},
options:{responsive:true,maintainAspectRatio:false,animation:{duration:600},
plugins:{legend:{labels:{color:'#8b949e',font:{size:11},usePointStyle:true,padding:12}}},
scales:{x:{ticks:{color:'#8b949e',font:{size:10},maxTicksLimit:8},grid:{color:'rgba(38,48,64,.4)'}},y:{ticks:{color:'#8b949e',font:{size:10}},grid:{color:'rgba(38,48,64,.4)'},beginAtZero:true}}
}});
}

// ── DASH ──
async function rf_dash(){
try{
var d=await api('GET','/api/info');
var h='';
h+='<div class="sc"><div class="si bl">🤖</div><div><div class="sv">'+(d.bot_running?'运行中':'已停止')+'</div><div class="sl">机器人状态</div></div></div>';
h+='<div class="sc"><div class="si gn">🔑</div><div><div class="sv">'+(d.bili_logged_in?'已登录':'未登录')+'</div><div class="sl">B站认证</div></div></div>';
h+='<div class="sc"><div class="si or">🛡</div><div><div class="sv">'+(d.safety_enabled?'已开启':'已关闭')+'</div><div class="sl">安全校验</div></div></div>';
h+='<div class="sc"><div class="si pk">⏱</div><div><div class="sv" id="puptime">--</div><div class="sl">运行时长</div></div></div>';
h+='<div class="sc"><div class="si pp">📦</div><div><div class="sv">'+(d.data_files||0)+'</div><div class="sl">数据文件</div></div></div>';
h+='<div class="sc"><div class="si '+(d.comment_mode=='real'?'gn':'or')+'">💬</div><div><div class="sv">'+(d.comment_mode=='real'?'真实模式':'模拟模式')+'</div><div class="sl">评论模式</div></div></div>';
h+='<div class="sc" id="asrDashCard"><div class="si '+(d.asr_enabled?'gn':'rd')+'">🎙️</div><div><div class="sv">'+(d.asr_enabled?'开启':'关闭')+'</div><div class="sl">ASR语音识别</div></div></div>';
h+='<div class="sc"><div class="si '+(d.pm_enabled?'gn':'rd')+'">📩</div><div><div class="sv">'+(d.pm_enabled?'开启':'关闭')+'</div><div class="sl">私信功能</div></div></div>';
document.getElementById('dashStats').innerHTML=h;
document.getElementById('puptime').textContent=d.uptime;

var dot=document.getElementById('botDot');dot.className='dot '+(d.bot_running?'on':'off');
var bd='<table class="tb"><tr><th>项目</th><th>值</th><th>项目</th><th>值</th></tr>';
bd+='<tr><td>运行状态</td><td><span class="tg '+(d.bot_running?'tg-suc':'tg-war')+'">'+(d.bot_running?'● 运行中':'○ 已停止')+'</span></td><td>启动时间</td><td>'+(d.bot_start_time||'-')+'</td></tr>';
bd+='<tr><td>API状态</td><td><span class="tg '+(d.api_configured?'tg-suc':'tg-dan')+'">'+(d.api_configured?'已配置':'未配置')+'</span></td>';
if(d.mood)bd+='<td>心情 / 精力</td><td>'+(d.mood.mood||'-')+' / '+(d.mood.energy||'?')+'</td>';
else bd+='<td>心情</td><td>-</td>';
bd+='</tr>';
if(d.persona)bd+='<tr><td>当前人格</td><td>'+(d.persona.active||'-')+'</td>';
else bd+='<tr><td>当前人格</td><td>-</td>';
if(d.cost_total!=null)bd+='<td>累计费用</td><td>$'+Number(d.cost_total).toFixed(4)+'</td>';
else bd+='<td>累计费用</td><td>-</td>';
bd+='</tr>';
bd+='<tr><td>评论模式</td><td><span class="tg '+(d.comment_mode=='real'?'tg-suc':'tg-war')+'">'+(d.comment_mode=='real'?'真实模式':'模拟模式')+'</span></td>';
bd+='<td>安全校验</td><td><span class="tg '+(d.safety_enabled?'tg-suc':'tg-dan')+'">'+(d.safety_enabled?'● 已开启':'○ 已关闭')+'</span></td>';
bd+='</tr>';
bd+='<tr><td>AI模型</td><td>'+(d.model_brain||'-')+'</td>';
bd+='<td>私信功能</td><td><span class="tg '+(d.pm_enabled?'tg-suc':'tg-war')+'">'+(d.pm_enabled?'开启':'关闭')+'</span></td>';
bd+='</tr>';
bd+='</table>';
document.getElementById('botDetail').innerHTML=bd;

var fg='';
var flbs={'config.json':'配置','bilibili_cookies.json':'Cookie','comment_log.json':'评论日志','user_profiles.json':'用户画像','mood_state.json':'心情状态','personas.json':'人格数据','bot_diary.json':'日记','self_evolution.json':'进化记录','agent_skill_log.json':'Agent日志','bot_runtime_state.json':'运行时'};
for(var k in d.files||{}){
var f=d.files[k],lb=flbs[k]||k,cl=f.exists?'tg-suc':'tg-war';
fg+='<div><span class="tg '+cl+'">'+lb+'</span> '+(f.exists?f.size_fmt+' · '+f.mtime:'无')+'</div>';
}
document.getElementById('fileGrid').innerHTML=fg||'<div class="emp">无数据文件</div>';

// badges
document.getElementById('botBadge').style.display=d.bot_running?'':'none';
document.getElementById('botBadge').style.background=d.bot_running?'var(--green)':'';
document.getElementById('loginBadge').style.display=d.bili_logged_in?'':'none';

// Charts
try{
var ch=await api('GET','/api/charts');
if(ch.comments){var ds=[],cs=[];for(var i=0;i<ch.comments.length;i++){ds.push(ch.comments[i].date);cs.push(ch.comments[i].count)}_makeLine('chartComments',ds,[{label:'评论数',data:cs,borderColor:'#58a6ff',backgroundColor:'rgba(88,166,255,.1)',borderWidth:2,tension:.3,fill:true}]);}
if(ch.moods){var md=[],mv=[],me=[];for(var i=0;i<ch.moods.length;i++){md.push(ch.moods[i].date);mv.push(ch.moods[i].valence||50);me.push(ch.moods[i].energy||50)}_makeLine('chartMood',md,[{label:'情绪指数',data:mv,borderColor:'#db61a2',backgroundColor:'rgba(219,97,162,.08)',borderWidth:2,tension:.3,fill:true},{label:'精力指数',data:me,borderColor:'#3fb950',backgroundColor:'rgba(63,185,80,.08)',borderWidth:2,tension:.3,fill:true}]);}
if(ch.actions){var ad=[],ac=[];for(var i=0;i<ch.actions.length;i++){ad.push(ch.actions[i].date);ac.push(ch.actions[i].count)}_makeLine('chartActions',ad,[{label:'操作数',data:ac,borderColor:'#d2991d',backgroundColor:'rgba(210,153,29,.1)',borderWidth:2,tension:.3,fill:true}]);}
if(ch.videos){var vd=[],vc=[];for(var i=0;i<ch.videos.length;i++){vd.push(ch.videos[i].date);vc.push(ch.videos[i].count)}_makeLine('chartVideos',vd,[{label:'处理视频数',data:vc,borderColor:'#a371f7',backgroundColor:'rgba(163,113,247,.1)',borderWidth:2,tension:.3,fill:true}]);}
}catch(e){}
}catch(e){}
}

// ── CONTROL ──
var logPoll=null;
var userScrolledUp=false;
function rf_ctrl(){
upCtrlUI();
pollLog();
var lb=document.getElementById('botLog');
if(lb){
lb.addEventListener('scroll',function(){
var el=lb;
var atBottom=el.scrollHeight - el.scrollTop - el.clientHeight < 30;
userScrolledUp=!atBottom;
});
}
}
async function upCtrlUI(){
var d=await api('GET','/api/info');
document.getElementById('ctrlStatus').innerHTML=d.bot_running?'<span class="tg tg-suc pulse">● 运行中</span> 自 '+d.bot_start_time:'<span class="tg tg-war">○ 已停止</span>';
document.getElementById('btnStart').style.display=d.bot_running?'none':'';
document.getElementById('btnStop').style.display=d.bot_running?'':'none';
}
async function startBot(){
var sel=document.getElementById('botMode');
var mode=sel?sel.value:'current';
if(mode!=='smart'&&mode!=='current')mode='current';
var r=await api('POST','/api/bot/start',{mode:mode});
if(r.ok){
  var label=mode==='smart'?'智能省token':'当前';
  toast('已以「'+label+'」模式启动','ok');
  userScrolledUp=false;pollLog();rf_dash();
  var lb=document.getElementById('botLog');if(lb){lb.scrollTop=lb.scrollHeight;lb.scrollIntoView({behavior:'smooth',block:'nearest'});}
}else{
  toast(r.message||'启动失败','err');
}
upCtrlUI();
}
var _botModeSynced=false;
async function syncBotMode(){
if(_botModeSynced)return;_botModeSynced=true;
try{var c=await api('GET','/api/config');var m=(c&&c.system&&c.system.smart_token_mode)?'smart':'current';var sel=document.getElementById('botMode');if(sel)sel.value=m;}catch(e){}
}
async function stopBot(){
var r=await api('POST','/api/bot/stop');toast(r.message,r.ok?'ok':'err');upCtrlUI();if(r.ok)rf_dash()
}
async function restartBot(){
toast('正在重启机器人...','ok');
await stopBot();
setTimeout(startBot,1200);
}
async function clearLog(){await api('POST','/api/bot/clear');document.getElementById('botLog').textContent='日志已清空';userScrolledUp=false;pollLog()}
async function pollLog(){
if(logPoll)clearInterval(logPoll);
var tick=async function(){
try{
var r=await api('GET','/api/bot/output');
var el=document.getElementById('botLog');
var wasAtBottom=el&&(el.scrollHeight-el.scrollTop-el.clientHeight<30);
if(el){
el.textContent=r.output||'无输出';
if(!userScrolledUp||wasAtBottom)el.scrollTop=el.scrollHeight;
}
}catch(e){}
};
tick();
logPoll=setInterval(tick,2000);
}
function stopPoll(){if(logPoll){clearInterval(logPoll);logPoll=null}}

// ── MONITOR ──
var monitorLogPoll=null;
var monitorUserScrolledUp=false;
function rf_monitor(){
refreshMonitor();
pollMonitorLog();
var lb=document.getElementById('monitorLog');
if(lb){
lb.addEventListener('scroll',function(){
var el=lb;
var atBottom=el.scrollHeight - el.scrollTop - el.clientHeight < 30;
monitorUserScrolledUp=!atBottom;
});
}
}
async function refreshMonitor(){
try{
var r=await api('GET','/api/monitor/status');
document.getElementById('monitorStatus').innerHTML=r.running?'<span class="tg tg-suc pulse" style="font-size:13px;padding:5px 12px">● 监听中</span>':'<span class="tg tg-war" style="font-size:13px;padding:5px 12px">○ 已停止</span>';
document.getElementById('monitorUptime').textContent=r.running&&r.uptime?'已运行 '+r.uptime:'';
document.getElementById('btnMonitorStart').style.display=r.running?'none':'';
document.getElementById('btnMonitorStop').style.display=r.running?'':'none';
document.getElementById('monitorBadge').style.display=r.running?'':'none';
document.getElementById('monitorBadge').style.background=r.running?'var(--green)':'';
// 配置
if(r.config){
document.getElementById('monCmtInterval').value=r.config.comment_check_interval||120;
document.getElementById('monMsgInterval').value=r.config.private_msg_check_interval||60;
document.getElementById('monMaxReplies').value=r.config.max_replies_per_check||5;
document.getElementById('monAutoReply').value=r.config.auto_reply!==false?'true':'false';
}
// 统计卡片
var s=r.stats||{};
var h='';
h+='<div class="sc"><div class="si bl">💬</div><div><div class="sv">'+(s.comments_processed||0)+'</div><div class="sl">评论处理</div></div></div>';
h+='<div class="sc"><div class="si gn">📩</div><div><div class="sv">'+(s.messages_processed||0)+'</div><div class="sl">私信处理</div></div></div>';
h+='<div class="sc"><div class="si or">🔄</div><div><div class="sv">'+(s.total_replies||0)+'</div><div class="sl">总回复数</div></div></div>';
h+='<div class="sc"><div class="si pk">⏱</div><div><div class="sv">'+(r.uptime||'-')+'</div><div class="sl">运行时长</div></div></div>';
h+='<div class="sc"><div class="si '+(s.errors>0?'or':'gn')+'">⚡</div><div><div class="sv">'+(s.errors||0)+'</div><div class="sl">错误次数</div></div></div>';
document.getElementById('monitorStats').innerHTML=h;
// badges
document.getElementById('botBadge').style.display=!r.running?'none':'';
document.getElementById('loginBadge').style.display=r.running?'none':'';
}catch(e){}
}
async function startMonitor(){
var r=await api('POST','/api/monitor/start');
toast(r.message,r.ok?'ok':'err');
refreshMonitor();
if(r.ok){monitorUserScrolledUp=false;pollMonitorLog()}
}
async function stopMonitor(){
var r=await api('POST','/api/monitor/stop');
toast(r.message,r.ok?'ok':'err');
refreshMonitor();
}
async function saveMonitorConfig(){
var cfg={
comment_check_interval:parseInt(document.getElementById('monCmtInterval').value)||120,
private_msg_check_interval:parseInt(document.getElementById('monMsgInterval').value)||60,
max_replies_per_check:parseInt(document.getElementById('monMaxReplies').value)||5,
auto_reply:document.getElementById('monAutoReply').value==='true'
};
var r=await api('POST','/api/monitor/config',cfg);
document.getElementById('monCfgMsg').innerHTML=r.ok?'<span style="color:var(--green)">✓ 已保存</span>':'<span style="color:var(--red)">'+r.message+'</span>';
toast(r.message,r.ok?'ok':'err');
}
async function pollMonitorLog(){
if(monitorLogPoll)clearInterval(monitorLogPoll);
var tick=async function(){
try{
var r=await api('GET','/api/monitor/output');
var el=document.getElementById('monitorLog');
var wasAtBottom=el&&(el.scrollHeight-el.scrollTop-el.clientHeight<30);
if(el){
el.textContent=r.output||'等待启动...';
if(!monitorUserScrolledUp||wasAtBottom)el.scrollTop=el.scrollHeight;
var lines=(r.output||'').split('\n').filter(function(l){return l.trim()});
document.getElementById('monitorLogCount').textContent=lines.length+' 行';
}
}catch(e){}
};
tick();
monitorLogPoll=setInterval(tick,2000);
}

// ── LOGIN ──
var qrTimer=null;
function rf_login(){
checkLogin();
}
async function checkLogin(){
try{
var d=await api('GET','/api/info');
var ci=document.getElementById('cookieInfo');
if(d.bili_logged_in){
document.getElementById('loginStatus').innerHTML='<span class="tg tg-suc">✅ 已登录B站</span>';
ci.textContent='Cookie 文件: '+(d.cookie_file||'用户数据目录 / bilibili_cookies.json');
document.getElementById('btnQR').textContent='🔄 重新登录';
document.getElementById('btnLogout').style.display='';
document.getElementById('loginBadge').style.display='';
} else {
document.getElementById('loginStatus').innerHTML='<span class="tg tg-war">❌ 未登录</span>';
ci.innerHTML='尚未登录B站账号';
document.getElementById('btnQR').textContent='📷 生成登录二维码';
document.getElementById('btnLogout').style.display='none';
document.getElementById('loginBadge').style.display='none';
}
}catch(e){}
}
async function startQRLogin(){
document.getElementById('qrArea').style.display='block';
document.getElementById('qrStatusText').textContent='⏳ 正在生成二维码...';
document.getElementById('qrImg').src='';
var r=await api('POST','/api/bili/qr/start');
if(!r.ok){toast(r.message,'err');return}
document.getElementById('qrImg').src='data:image/png;base64,'+r.img;
document.getElementById('qrStatusText').textContent=r.message;
if(qrTimer)clearInterval(qrTimer);
qrTimer=setInterval(pollQR,2000);
}
async function pollQR(){
try{
var r=await api('GET','/api/bili/qr/status');
document.getElementById('qrStatusText').textContent=r.message;
if(r.status=='success'){
clearInterval(qrTimer);qrTimer=null;
toast('登录成功！UID: '+r.uid,'ok');
setTimeout(function(){document.getElementById('qrArea').style.display='none';checkLogin();rf_dash()},1500);
}else if(r.status=='timeout'||r.status=='error'){
clearInterval(qrTimer);qrTimer=null;
toast(r.message,'err');
document.getElementById('qrArea').style.display='none';
}
}catch(e){clearInterval(qrTimer);qrTimer=null}
}
async function logoutBili(){
if(!confirm('确定退出B站登录？'))return;
var r=await api('POST','/api/bili/logout');toast(r.message,r.ok?'ok':'err');checkLogin();rf_dash()
}

// ── CONFIG ──
var _confMode='quick',_confData=null;
function rf_conf(){loadConf()}
function toggleConfMode(){
_confMode=_confMode==='quick'?'json':'quick';
document.getElementById('confQuickBox').style.display=_confMode==='quick'?'':'none';
document.getElementById('confJsonBox').style.display=_confMode==='json'?'':'none';
if(_confMode==='json')loadConf();
else loadConfQuick();
}
async function loadConf(){try{var r=await api('GET','/api/config');_confData=r;document.getElementById('confEd').value=JSON.stringify(r,null,2)}catch(e){toast('加载失败','err')}}
async function saveConf(){try{var v=JSON.parse(document.getElementById('confEd').value);var r=await api('POST','/api/config',v);toast(r.message,r.ok?'ok':'err');_confData=v;if(_confMode=='quick')loadConfQuick()}catch(e){toast('JSON格式错误: '+e.message,'err')}}
async function applyPreset(){
var sel=document.getElementById('cqPreset');if(!sel)return;
var key=sel.value;if(!key)return;
try{var ps=await api('GET','/api/ai/presets');var p=(ps.presets&&ps.presets[key])||ps[key];if(!p)return;
document.getElementById('cqBaseUrl').value=p.base_url||'';
document.getElementById('cqModelBrain').value=p.chat||'';
document.getElementById('cqModelVision').value=p.vision||'';
toast('已填入预设: '+(p.name||key),'ok');
}catch(e){toast('读取预设失败: '+e.message,'err')}
}
async function loadConfQuick(){
if(!_confData){var r=await api('GET','/api/config');_confData=r}
var c=_confData;
var h='';
// API
h+='<fieldset class="fs"><legend>🔑 API 设置</legend>';
h+='<div class="fg"><label>厂商预设 (一键填入官方格式)</label><select id="cqPreset" onchange="applyPreset()"><option value="">— 自定义 / OpenAI 兼容 —</option></select></div>';
h+='<div class="fg"><label>API Key</label><input id="cqApiKey" value="'+(c.api?c.api.unified_api_key||'':'')+'" placeholder="sk-..."></div>';
h+='<div class="fg"><label>Base URL</label><input id="cqBaseUrl" value="'+(c.api?c.api.unified_base_url||'':'')+'" placeholder="https://api.openai.com/v1"></div>';
h+='<div class="fg"><label>模型(对话)</label><input id="cqModelBrain" value="'+(c.api?c.api.model_brain||'':'')+'" placeholder="gpt-4o"></div>';
h+='<div class="fg"><label>模型(视觉)</label><input id="cqModelVision" value="'+(c.api?c.api.model_vision||'':'')+'" placeholder="gpt-4o"></div>';
h+='</fieldset>';
// 交互
h+='<fieldset class="fs"><legend>🤝 交互设置</legend>';
h+='<div class="fg"><label>最大精力值</label><input id="cqMaxEnergy" type="number" value="'+((c.interaction?c.interaction.max_energy:0)||100)+'"></div>';
h+='<div class="fg"><label>评论检查间隔(秒)</label><input id="cqCmtInterval" type="number" value="'+((c.interaction?c.interaction.comment_check_interval:0)||300)+'"></div>';
h+='<div class="fg"><label>每次最大回复数</label><input id="cqMaxReplies" type="number" value="'+((c.interaction?c.interaction.max_replies_per_check:0)||3)+'"></div>';
h+='</fieldset>';
// 人格
h+='<fieldset class="fs"><legend>🎭 人格设置</legend>';
h+='<div class="fg"><label>活跃人格</label><input id="cqPersona" value="'+(c.persona?c.persona.active_persona||c.persona.prompt_name||'':'')+'" placeholder="默认人格"></div>';
h+='<div class="fg"><label>提示词名称</label><input id="cqPromptName" value="'+(c.persona?c.persona.prompt_name||'':'')+'" placeholder="AI小助手"></div>';
h+='</fieldset>';
// 视频
h+='<fieldset class="fs"><legend>🎬 视频设置</legend>';
h+='<div class="fg"><label>视频模式</label><select id="cqVideoMode"><option value="smart"'+(c.video&&c.video.mode=='smart'?' selected':'')+'>智能</option><option value="random"'+(c.video&&c.video.mode=='random'?' selected':'')+'>随机</option><option value="hot"'+(c.video&&c.video.mode=='hot'?' selected':'')+'>热门</option></select></div>';
h+='<div class="fg"><label>最大时长(秒)</label><input id="cqMaxDuration" type="number" value="'+((c.video?c.video.max_duration_seconds:0)||900)+'"></div>';
h+='<div class="fg"><label>图文笔记模式</label><select id="cqNoteMode"><option value="visual_note"'+(c.video&&c.video.frame_note_mode!=='classic'?' selected':'')+'>图文学习笔记+目录</option><option value="classic"'+(c.video&&c.video.frame_note_mode=='classic'?' selected':'')+'>经典仅理解</option></select></div>';
h+='<div class="fg"><label>候选视频数量</label><input id="cqCandidatePoolSize" type="number" min="5" max="100" value="'+((c.video?c.video.candidate_pool_size:0)||20)+'"></div>';
  h+='<div class="fr"><div class="fg"><label>图文抽帧间隔(秒)</label><input id="cqVisualNoteInterval" type="number" min="1" max="60" value="'+((c.video?c.video.visual_note_frame_interval:0)||6)+'"></div><div class="fg"><label>图文最多抽帧数</label><input id="cqVisualNoteMaxFrames" type="number" min="9" max="360" value="'+((c.video?c.video.visual_note_max_frames:0)||240)+'"></div><div class="fg"><label>网格列数</label><input id="cqVisualNoteCols" type="number" min="1" max="4" value="'+((c.video?c.video.visual_note_grid_cols:0)||3)+'"></div><div class="fg"><label>网格行数</label><input id="cqVisualNoteRows" type="number" min="1" max="4" value="'+((c.video?c.video.visual_note_grid_rows:0)||3)+'"></div></div>';
h+='<div class="fg"><label>自定义笔记提示词</label><textarea id="cqVideoPrompt" style="width:100%;min-height:50px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:12px;padding:8px;font-family:inherit;resize:vertical" placeholder="如：更口语化、以表格形式输出、突出技术要点...">'+(c.video&&c.video.custom_video_prompt?c.video.custom_video_prompt:'')+'</textarea></div>';
h+='</fieldset>';
// 行为
h+='<fieldset class="fs"><legend>⚡ 行为设置</legend>';
h+='<div class="fg"><label>评论模式</label><select id="cqCommentMode"><option value="real"'+(c.behavior&&c.behavior.comment_mode=='real'?' selected':'')+'>真实模式</option><option value="simulate"'+(c.behavior&&c.behavior.comment_mode=='simulate'?' selected':'')+'>模拟模式</option></select></div>';
h+='<div class="fg"><label>AI免责声明</label><input id="cqAiMarker" value="'+(c.behavior?c.behavior.ai_marker||'':'')+'" placeholder="（内容由AI生成并由AI回复）"></div>';
h+='</fieldset>';
// 安全
h+='<fieldset class="fs"><legend>🛡 安全设置</legend>';
h+='<div class="fg"><label>安全校验</label><select id="cqSafety"><option value="1"'+(c.reply_safety&&c.reply_safety.enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.reply_safety&&c.reply_safety.enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='<div class="fg"><label>屏蔽关键词(逗号分隔)</label><textarea id="cqBlockedKw" style="width:100%;min-height:60px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:12px;padding:8px;font-family:inherit;resize:vertical">'+((c.reply_safety&&c.reply_safety.blocked_keywords?c.reply_safety.blocked_keywords.join(', '):''))+'</textarea></div>';
h+='</fieldset>';
// 私信
h+='<fieldset class="fs"><legend>📩 私信设置</legend>';
h+='<div class="fg"><label>私信功能</label><select id="cqPmEnabled"><option value="1"'+(c.private_message&&c.private_message.enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.private_message&&c.private_message.enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='<div class="fg"><label>自动回复</label><select id="cqPmAuto"><option value="1"'+(c.private_message&&c.private_message.auto_reply!==false?' selected':'')+'>启用</option><option value="0"'+(c.private_message&&c.private_message.auto_reply===false?' selected':'')+'>禁用</option></select></div>';
h+='<div class="fg"><label>主动私信</label><select id="cqActiveChat"><option value="1"'+(c.active_chat&&c.active_chat.enabled?' selected':'')+'>启用</option><option value="0"'+(!c.active_chat||!c.active_chat.enabled?' selected':'')+'>关闭</option></select></div>';
h+='<div class="fg"><label>主动私信白名单 UID</label><textarea id="cqActiveChatWhitelist" placeholder="留空则不限制；填写后只主动私信这些 UID（逗号或换行分隔）" style="width:100%;min-height:54px;background:var(--bg3);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:12px;padding:8px;font-family:inherit;resize:vertical">'+((c.active_chat&&c.active_chat.whitelist_uids?c.active_chat.whitelist_uids.join(', '):''))+'</textarea></div>';
h+='</fieldset>';
// Agent
h+='<fieldset class="fs"><legend>🤖 Agent 设置</legend>';
h+='<div class="fg"><label>Agent</label><select id="cqAgent"><option value="1"'+(c.agent&&c.agent.enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.agent&&c.agent.enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='<div class="fg"><label>自动Agent</label><select id="cqAgentAuto"><option value="1"'+(c.agent&&c.agent.auto_enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.agent&&c.agent.auto_enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='</fieldset>';
// 视觉/ASR
h+='<fieldset class="fs"><legend>👁 视觉 & ASR</legend>';
h+='<div class="fg"><label>ASR语音识别</label><select id="cqAsr"><option value="1"'+(c.asr&&c.asr.enabled?' selected':'')+'>启用</option><option value="0"'+(c.asr&&!c.asr||!c.asr.enabled?' selected':'')+'>禁用</option></select></div>';
h+='<div class="fg"><label>多模态图片输入</label><select id="cqMultimodal"><option value="0"'+(!c.vision||c.vision.multimodal_enabled!==true?' selected':'')+'>关闭（仅识别文字）</option><option value="1"'+(c.vision&&c.vision.multimodal_enabled===true?' selected':'')+'>开启（封面、评论图、抽帧）</option></select><p class="form-hint" style="margin:6px 0 0">仅在当前 API 的视觉模型支持图片时开启；文本模型会拒绝图片请求。</p></div>';
h+='<div class="fg"><label>封面识图</label><select id="cqVision"><option value="1"'+(c.vision&&c.vision.cover_enabled!==false?' selected':'')+'>启用</option><option value="0"'+(c.vision&&c.vision.cover_enabled===false?' selected':'')+'>禁用</option></select></div>';
h+='</fieldset>';
document.getElementById('confQuickContent').innerHTML=h;
try{var _ps=await api('GET','/api/ai/presets');var _sel=document.getElementById('cqPreset');if(_sel&&_ps){var _pr=_ps.presets||_ps;for(var _k in _pr){var _o=document.createElement('option');_o.value=_k;_o.textContent=_pr[_k].name;_sel.appendChild(_o);}if(_ps.active_preset)_sel.value=_ps.active_preset;}}catch(e){}
}
async function saveConfQuick(){
try{
if(!_confData)_confData=await api('GET','/api/config');
var c=JSON.parse(JSON.stringify(_confData));
// API
c.api=c.api||{};
c.api.unified_api_key=document.getElementById('cqApiKey').value.trim();
c.api.unified_base_url=document.getElementById('cqBaseUrl').value.trim();
c.api.model_brain=document.getElementById('cqModelBrain').value.trim();
c.api.model_vision=document.getElementById('cqModelVision').value.trim();
var _psel=document.getElementById('cqPreset');if(_psel)c.active_preset=_psel.value;
// Interaction
c.interaction=c.interaction||{};
c.interaction.max_energy=parseInt(document.getElementById('cqMaxEnergy').value)||100;
c.interaction.comment_check_interval=parseInt(document.getElementById('cqCmtInterval').value)||300;
c.interaction.max_replies_per_check=parseInt(document.getElementById('cqMaxReplies').value)||3;
// Persona
c.persona=c.persona||{};
c.persona.active_persona=document.getElementById('cqPersona').value.trim()||'默认人格';
c.persona.prompt_name=document.getElementById('cqPromptName').value.trim()||'AI小助手';
// Video
c.video=c.video||{};
c.video.mode=document.getElementById('cqVideoMode').value;
c.video.max_duration_seconds=parseInt(document.getElementById('cqMaxDuration').value)||900;
c.video.frame_note_mode=document.getElementById('cqNoteMode').value;
c.video.candidate_pool_size=Math.min(100,Math.max(5,parseInt(document.getElementById('cqCandidatePoolSize').value)||20));
  c.video.visual_note_frame_interval=Math.min(60,Math.max(1,parseInt(document.getElementById('cqVisualNoteInterval').value)||6));
  c.video.visual_note_max_frames=Math.min(360,Math.max(9,parseInt(document.getElementById('cqVisualNoteMaxFrames').value)||240));
  c.video.visual_note_grid_cols=Math.min(4,Math.max(1,parseInt(document.getElementById('cqVisualNoteCols').value)||3));
  c.video.visual_note_grid_rows=Math.min(4,Math.max(1,parseInt(document.getElementById('cqVisualNoteRows').value)||3));
c.video.custom_video_prompt=(document.getElementById('cqVideoPrompt')||{}).value||'';
// Behavior
c.behavior=c.behavior||{};
c.behavior.comment_mode=document.getElementById('cqCommentMode').value;
c.behavior.ai_marker=document.getElementById('cqAiMarker').value.trim();
// Safety
c.reply_safety=c.reply_safety||{};
c.reply_safety.enabled=document.getElementById('cqSafety').value==='1';
var kwRaw=document.getElementById('cqBlockedKw').value;
c.reply_safety.blocked_keywords=kwRaw.split(/[,，\n]/).map(function(s){return s.trim()}).filter(function(s){return s.length>0});
// Private message
c.private_message=c.private_message||{};
c.private_message.enabled=document.getElementById('cqPmEnabled').value==='1';
c.private_message.auto_reply=document.getElementById('cqPmAuto').value==='1';
c.active_chat=c.active_chat||{};
c.active_chat.enabled=document.getElementById('cqActiveChat').value==='1';
var activeChatWhitelist=document.getElementById('cqActiveChatWhitelist').value;
c.active_chat.whitelist_uids=activeChatWhitelist.split(/[,，\n]/).map(function(s){return s.trim()}).filter(function(s){return /^\d+$/.test(s)}).filter(function(s,i,a){return a.indexOf(s)===i});
c.active_chat.whitelist_enabled=c.active_chat.whitelist_uids.length>0;
// Agent
c.agent=c.agent||{};
c.agent.enabled=document.getElementById('cqAgent').value==='1';
c.agent.auto_enabled=document.getElementById('cqAgentAuto').value==='1';
// ASR
c.asr=c.asr||{};
c.asr.enabled=document.getElementById('cqAsr').value==='1';
// Vision
c.vision=c.vision||{};
c.vision.multimodal_enabled=document.getElementById('cqMultimodal').value==='1';
c.vision.cover_enabled=document.getElementById('cqVision').value==='1';
var r=await api('POST','/api/config',c);
_confData=c;
document.getElementById('confQuickMsg').innerHTML=r.ok?'<span style="color:var(--green)">✅ '+r.message+'</span>':'<span style="color:var(--red)">❌ '+r.message+'</span>';
toast(r.message,r.ok?'ok':'err');
}catch(e){toast('保存失败: '+e.message,'err')}
}

// ── PERSONA ──
async function rf_psna(){
try{
var r=await api('GET','/api/personas');var h='',items=r.items||{},act=r.active||'';
for(var n in items){
var p=items[n],isA=n===act;
h+=`<div class="pc" data-persona="${esc(n)}"><h3>${isA?'<span class="tg tg-suc">● 活跃</span> ':''}${esc(n)}</h3><div style="font-size:11px;color:var(--text2)">风格：${esc(p.style||'-')} | 规则：${(p.rules||[]).length}条</div><div class="btn-grp">${isA?'':'<button class="btn btn-sm btn-pr" data-act-psna="${esc(n)}">启用</button>'}<button class="btn btn-sm btn-out" data-del-psna="${esc(n)}" ${Object.keys(items).length<2?'disabled':''}>删除</button></div></div>`;
}
h+=`<div class="pc"><h3>➕ 新建人设</h3><div class="fg"><label>名称</label><input id="npName" placeholder="如: 毒舌模式"></div><div class="fg"><label>系统Prompt</label><textarea id="npPrompt" placeholder="你是..."></textarea></div><div class="fg"><label>风格</label><input id="npStyle" placeholder="幽默、犀利"></div><button class="btn btn-pr" onclick="addPsna()">创建</button></div>`;
document.getElementById('psnaList').innerHTML=h;
// Event delegation for persona buttons
document.getElementById('psnaList').onclick=function(e){
var t=e.target;
if(t.dataset.actPsna){actPsna(t.dataset.actPsna);return}
if(t.dataset.delPsna){delPsna(t.dataset.delPsna);return}
};
}catch(e){}
}
async function addPsna(){
var n=document.getElementById('npName').value.trim(),p=document.getElementById('npPrompt').value.trim(),s=document.getElementById('npStyle').value.trim();
if(!n){toast('请输入名称','err');return}
var r=await api('POST','/api/personas',{name:n,system_prompt:p,style:s});toast(r.message,r.ok?'ok':'err');if(r.ok)rf_psna()
}
async function actPsna(n){var r=await api('POST','/api/personas/activate',{name:n});toast(r.message,r.ok?'ok':'err');if(r.ok)rf_psna()}
async function delPsna(n){if(!confirm('删除"'+n+'"？'))return;var r=await api('DELETE','/api/personas/'+encodeURIComponent(n));toast(r.message,r.ok?'ok':'err');if(r.ok)rf_psna()}

// ── COMMENTS ──
async function rf_cmts(){
try{
var r=await api('GET','/api/comments?limit=50'),its=r.items||[];
if(!its.length){document.getElementById('cmtTab').innerHTML='<div class="emp"><div class="ic">💬</div>暂无评论记录</div>';return}
var h='<table class="tb"><tr><th>时间</th><th>类型</th><th>内容</th><th>来源</th><th>状态</th></tr>';
for(var i=0;i<its.length;i++){var c=its[i];h+=`<tr><td>${c.time||'-'}</td><td><span class="tg tg-inf">${c.type||'-'}</span></td><td title="${esc(c.content||'')}">${(c.content||'').substring(0,50)}</td><td>${c.source||'-'}</td><td>${c.executed?'<span class="tg tg-suc">已执行</span>':'<span class="tg tg-war">草稿</span>'}</td></tr>`}
h+='</table>';document.getElementById('cmtTab').innerHTML=h;
}catch(e){}
}

// ── USERS ──
async function rf_usrs(){
try{
var r=await api('GET','/api/users'),u=r.users||{},ks=Object.keys(u);
if(!ks.length){document.getElementById('usrTab').innerHTML='<div class="emp"><div class="ic">👤</div>暂无用户画像</div>';return}
var h='<table class="tb"><tr><th>用户</th><th>好感度</th><th>关系</th><th>最近印象</th><th>更新时间</th></tr>';
for(var k in u){var p=u[k],a=parseInt(p.affinity)||0,cl=a>=80?'tg-suc':a>=45?'tg-inf':a<=-40?'tg-dan':'tg-war';
h+=`<tr><td>${p.name||k}</td><td><span class="tg ${cl}">${a}</span></td><td>${rel(a)}</td><td>${(p.notes||[]).slice(-2).join('；').substring(0,35)||'-'}</td><td>${p.updated_at||'-'}</td></tr>`}
h+='</table>';document.getElementById('usrTab').innerHTML=h;
}catch(e){}
}
function rel(a){var s=parseInt(a)||0;return s>=80?'挚友':s>=45?'熟人':s>=10?'有点印象':s<=-40?'需谨慎':'普通'}

// ── MEMORY ──
async function rf_mem(){
try{
var r=await api('GET','/api/memory'),h='';
if(r.diary&&r.diary.entries&&r.diary.entries.length){
h+='<div class="pc"><h3>📖 日记 ('+r.diary.entries.length+'条)</h3>';
var es=r.diary.entries.slice(-15).reverse();
for(var i=0;i<es.length;i++){var d=es[i];h+=`<div style="padding:8px;margin:4px 0;background:var(--bg3);border-radius:6px;font-size:11px"><strong>${d.time||''} ${d.mood||''}</strong><div style="color:var(--text2)">${(d.content||'').substring(0,180)}</div></div>`}
h+='</div>'}
if(r.evolution&&r.evolution.events&&r.evolution.events.length){
h+='<div class="pc"><h3>🧬 进化事件 ('+r.evolution.events.length+'条)</h3>';
var evs=r.evolution.events.slice(-15).reverse();
for(var i=0;i<evs.length;i++){var e=evs[i];h+=`<div style="font-size:11px;color:var(--text2);margin:2px 0">${e.time||''} [${e.type||''}] ${(e.detail||'').substring(0,120)}</div>`}
h+='</div>'}
document.getElementById('memBox').innerHTML=h||'<div class="emp"><div class="ic">🧠</div>暂无记忆数据</div>';
}catch(e){}
}

// ── DIARY ──
async function rf_diary(){
try{
var r=await api('GET','/api/diary'),h='';
if(r.diary&&r.diary.entries&&r.diary.entries.length){
h+='<div class="pc"><h3>📖 日记</h3>';
var es=r.diary.entries.slice(-20).reverse();
for(var i=0;i<es.length;i++){var d=es[i];h+=`<div style="border-bottom:1px solid var(--border);padding:8px 0"><div style="font-size:10px;color:var(--accent)">${d.time||''} · ${d.mood||''} · 精力${d.energy||'?'}</div><div style="font-size:11px;line-height:1.4">${(d.content||'').substring(0,200)}</div></div>`}
h+='</div>'}
if(r.evolution&&r.evolution.events&&r.evolution.events.length){
h+='<div class="pc"><h3>🧬 进化</h3><table class="tb"><tr><th>时间</th><th>类型</th><th>详情</th></tr>';
var evs=r.evolution.events.slice(-20).reverse();
for(var i=0;i<evs.length;i++){var e=evs[i];h+=`<tr><td>${e.time||'-'}</td><td>${e.type||'-'}</td><td style="max-width:260px">${(e.detail||'').substring(0,120)}</td></tr>`}
h+='</table></div>'}
document.getElementById('diaryBox').innerHTML=h||'<div class="emp"><div class="ic">📖</div>暂无数据</div>';
}catch(e){}
}

// ── ACTIONS ──
async function rf_acts(){
try{
var r=await api('GET','/api/actions?limit=40'),its=r.items||[];
if(!its.length){document.getElementById('actTab').innerHTML='<div class="emp"><div class="ic">📋</div>暂无操作日志</div>';return}
var h='<table class="tb"><tr><th>时间</th><th>操作</th><th>详情</th><th>状态</th></tr>';
for(var i=0;i<its.length;i++){var a=its[i];h+=`<tr><td>${a.time||'-'}</td><td>${a.action||'-'}</td><td title="${esc(JSON.stringify(a.payload||{}))}">${JSON.stringify(a.payload||{}).substring(0,60)}</td><td>${a.executed?'<span class="tg tg-suc">已执行</span>':'<span class="tg tg-war">草稿</span>'}</td></tr>`}
h+='</table>';document.getElementById('actTab').innerHTML=h;
}catch(e){}
}

// ── ABOUT ──
async function rf_about(){
try{
var d=await api('GET','/api/info');
function aboutCard(label,value,mono){
return '<div class="info-card"><div class="il">'+label+'</div><div class="iv'+(mono?' style=\"font-family:monospace;font-size:12px\'"':'')+'">'+value+'</div></div>';
}
document.getElementById('aboutBox').innerHTML='<div class="info-grid">'+
aboutCard('系统版本',d.version||'-')+
aboutCard('面板运行时长',d.uptime)+
aboutCard('Python 版本',d.python_version||'-')+
aboutCard('运行平台',d.platform||'-')+
aboutCard('工作目录',d.cwd||'-',true)+
aboutCard('机器人状态',d.bot_running?'● 运行中':'○ 已停止')+
'</div>';
}catch(e){}
}

// ── UTIL ──
function esc(s){return(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}

// ── AUTO REFRESH ──
var autoTmr=null;
function auto(){
if(autoTmr)return;
autoTmr=setInterval(async function(){
if(document.hidden)return;
var ap=document.querySelector('.page.on');if(!ap)return;
var id=ap.id.replace('pg-','');if(window['rf_'+id])window['rf_'+id]();
try{var d=await api('GET','/api/info');document.getElementById('uptime').textContent=d.uptime}catch(e){}
},8000);
}

// ── MOOD ──
var moodPresets=["开心","平静","好奇","兴奋","沉思","疲惫","慵懒","元气满满"];
function rf_mood(){fetchMood();
var h="";for(var i=0;i<moodPresets.length;i++){h+="<button class=\"btn btn-out btn-sm\" onclick=\"quickMood('"+moodPresets[i]+"')\">"+moodPresets[i]+"</button> "}
document.getElementById("moodQuickBtns").innerHTML=h;}
async function fetchMood(){
try{var r=await api("GET","/api/mood/status");
document.getElementById("moodStatus").innerHTML="<div style=\"font-size:14px\">当前心情: <strong style=\"color:var(--accent);font-size:18px\">"+(r.current_mood||"-")+"</strong> | 精力: <strong style=\"color:var(--green)\">"+(r.energy||"?")+"</strong></div>";
document.getElementById("moodDefault").value=r.default_mood||"";document.getElementById("moodRandom").checked=r.random_enabled;
document.getElementById("moodRandInt").value=r.random_interval||5;document.getElementById("moodCustom").checked=r.custom_enabled;
document.getElementById("moodCustomText").value=r.custom_mood||"";}catch(e){}}
async function quickMood(m){var r=await api("POST","/api/mood/set",{current_mood:m});toast(r.message,r.ok?"ok":"err");if(r.ok)fetchMood()}
async function saveMood(){
var b={default_mood:document.getElementById("moodDefault").value,random_enabled:document.getElementById("moodRandom").checked,
random_interval_minutes:parseInt(document.getElementById("moodRandInt").value)||5,
custom_enabled:document.getElementById("moodCustom").checked,custom_mood:document.getElementById("moodCustomText").value};
var r=await api("POST","/api/mood/set",b);toast(r.message,r.ok?"ok":"err");if(r.ok)fetchMood()}
function moodToggleRandom(){document.getElementById("moodRandInt").disabled=!document.getElementById("moodRandom").checked}
function moodToggleCustom(){document.getElementById("moodCustomText").disabled=!document.getElementById("moodCustom").checked}

// ── BEHAVIOR ──
var _aiMarkerConfirmed=false;
function rf_behavior(){fetchBehavior();fetchSafety()}
async function fetchBehavior(){
try{
var r=await api("GET","/api/behavior/get");
document.getElementById("aiMarkerText").value=r.ai_marker||"（内容由AI生成并由AI回复）";
var on=r.ai_marker&&r.ai_marker.length>0;
document.getElementById("aiMarkerOn").checked=on;
// energy
var e=r.energy||{};
document.getElementById("engMaxEnergy").value=e.max_energy||100;
document.getElementById("engRecoverMin").value=e.energy_recovery_min||5;
document.getElementById("engRecoverMax").value=e.energy_recovery_max||10;
document.getElementById("engRoundsMin").value=e.rounds_min||3;
document.getElementById("engRoundsMax").value=e.rounds_max||10;
document.getElementById("engRoundIntMin").value=e.round_interval_min||60;
document.getElementById("engRoundIntMax").value=e.round_interval_max||180;
document.getElementById("engVideoIntMin").value=e.video_interval_min||1;
document.getElementById("engVideoIntMax").value=e.video_interval_max||5;
// comment mode
var cm=r.comment_mode||"real";
var radios=document.getElementsByName("cmtMode");
for(var i=0;i<radios.length;i++){if(radios[i].value===cm)radios[i].checked=true}
}catch(e){}
}
async function toggleAiMarker(){
var cb=document.getElementById("aiMarkerOn");
if(!cb.checked){
if(confirm("⚠️ 确定要关闭AI免责声明吗？\n\n关闭后，所有评论和私信回复将不再标注AI身份。\n这可能导致平台审核风险。\n\n再次点击设置中的开关可以重新开启。")){
_aiMarkerConfirmed=true;
}else{
cb.checked=true;
return;
}
}
var r=await api("POST","/api/behavior/ai-marker/toggle",{enabled:cb.checked});
document.getElementById("aiMarkerText").value=r.marker||"";
document.getElementById("aiMarkerMsg").textContent=r.message||"";
toast(r.message,r.ok?"ok":"err");
}
async function saveAiMarker(){
var txt=document.getElementById("aiMarkerText").value.trim();
var r=await api("POST","/api/behavior/save",{ai_marker:txt});
document.getElementById("aiMarkerMsg").textContent=r.message||"";
toast(r.message,r.ok?"ok":"err");
}
async function saveEnergy(){
var b={
max_energy:parseInt(document.getElementById("engMaxEnergy").value)||100,
energy_recovery_min:parseInt(document.getElementById("engRecoverMin").value)||5,
energy_recovery_max:parseInt(document.getElementById("engRecoverMax").value)||10,
rounds_min:parseInt(document.getElementById("engRoundsMin").value)||3,
rounds_max:parseInt(document.getElementById("engRoundsMax").value)||10,
round_interval_min:parseInt(document.getElementById("engRoundIntMin").value)||60,
round_interval_max:parseInt(document.getElementById("engRoundIntMax").value)||180,
video_interval_min:parseInt(document.getElementById("engVideoIntMin").value)||1,
video_interval_max:parseInt(document.getElementById("engVideoIntMax").value)||5
};
var r=await api("POST","/api/behavior/save",{energy:b});
document.getElementById("engMsg").textContent=r.message||"";
toast(r.message,r.ok?"ok":"err");
}
async function saveCommentMode(){
var cm=document.querySelector('input[name="cmtMode"]:checked');
if(!cm)return;
var r=await api("POST","/api/behavior/save",{comment_mode:cm.value});
document.getElementById("cmtModeMsg").textContent=r.message||"";
toast(r.message,r.ok?"ok":"err");
}

	// ── SAFETY KEYWORDS ──
	var _safetyLoaded=false;
	async function fetchSafety(){
	try{
	var r=await api("GET","/api/behavior/safety");
	document.getElementById("safetyEnabled").checked=r.enabled||false;
	var kws=r.keywords||[];
	document.getElementById("safetyKeywords").value=kws.join("\n");
	document.getElementById("safetyKwSection").style.display=r.enabled?"":"none";
	_safetyLoaded=true;
	}catch(e){}
	}
	async function toggleSafety(){
	if(!_safetyLoaded){await fetchSafety();}
	var cb=document.getElementById("safetyEnabled");
	if(!cb.checked){
	if(!confirm("⚠ 确定要关闭关键词安全校验吗？\n\n关闭后AI将不再过滤任何评论和回复。\n这可能导致账号风险。\n\n你可以随时在设置中重新开启。")){
	cb.checked=true;
	return;
	}
	}
	var r=await api("POST","/api/behavior/safety/toggle",{enabled:cb.checked});
	document.getElementById("safetyKwSection").style.display=cb.checked?"":"none";
	document.getElementById("safetyMsg").textContent=r.message||"";
	toast(r.message,r.ok?"ok":"err");
	}
	async function saveSafetyKeywords(){
	var txt=document.getElementById("safetyKeywords").value.trim();
	var kws=txt.split(/[\n,]/).map(function(s){return s.trim()}).filter(function(s){return s.length>0});
	var r=await api("POST","/api/behavior/safety/save",{keywords:kws});
	document.getElementById("safetyMsg").textContent=r.message||"";
	toast(r.message,r.ok?"ok":"err");
	}
	async function addSafetyKeyword(){
	var inp=document.getElementById("newSafetyKw");
	var kw=inp.value.trim();
	if(!kw){toast("请输入关键词","err");return}
	var ta=document.getElementById("safetyKeywords");
	var kws=ta.value.split("\n").map(function(s){return s.trim()}).filter(function(s){return s.length>0});
	if(kws.indexOf(kw)>=0){toast("关键词已存在","err");inp.value="";return}
	kws.push(kw);
	ta.value=kws.join("\n");
	inp.value="";
	await saveSafetyKeywords();
	}

// ── UPFOLLOW ──
async function rf_upfu(){
try{var r=await api("GET","/api/up-follow/list");var its=r.items||[];
if(!its.length){document.getElementById("upfuTab").innerHTML="<div class=\"emp\"><div class=\"ic\">👥</div>暂无已关注的UP主</div>";return}
its.sort(function(a,b){return (b.avg_score||0)-(a.avg_score||0)});
var h="<table class=\"tb\"><tr><th>#</th><th>UP主</th><th>UID</th><th>评分</th><th>印象次数</th><th>关注时间</th></tr>";
for(var i=0;i<its.length;i++){var u=its[i];h+="<tr><td>"+(i+1)+"</td><td>"+(u.favorited?"⭐ ":"")+u.name+"</td><td class=\"mono\">"+u.uid+"</td><td>"+(u.avg_score||"-")+"</td><td>"+(u.impressions||0)+"</td><td>"+(u.followed_at||"-")+"</td></tr>"}
h+="</table>";document.getElementById("upfuTab").innerHTML=h}catch(e){}}

// ── TOOLS ──
function rf_tools(){rf_kbStats();loadAsrHighlight()}
async function sendDanmaku(){
var b=document.getElementById("danmakuBvid").value.trim(),t=document.getElementById("danmakuText").value.trim();
if(!b||!t){toast("请填写BV号和弹幕内容","err");return}
if(t.length>20){toast("弹幕不能超过20字","err");return}
var r=await api("POST","/api/action/send-danmaku",{bvid:b,text:t});toast(r.message,r.ok?"ok":"err")}
async function analyzeVideo(){
var b=document.getElementById("analyzeBvid").value.trim();
if(!b){toast("请输入BV号","err");return}
 var mode=(document.getElementById("analyzeAnchor")||{}).value||"visual_note";
 if(mode==="visual_note"){
var prompt=(document.getElementById("analyzePrompt")||{}).value||"";
 var r=await api("POST","/api/action/visual-note",{bvid:b,custom_prompt:prompt});
toast(r.message,"ok");
 if(r.ok){pollVisualNoteResult(r.bvid)}
}else{
var r=await api("POST","/api/action/analyze-video",{bvid:b});toast(r.message,r.ok?"ok":"err")
}}
var _biliPollTimer=null;
async function pollVisualNoteResult(bvid){
var box=document.getElementById("analyzeResult");box.style.display="block";
box.innerHTML='<div style="text-align:center;padding:20px;color:var(--text2)">⏳ AI正在生成图文笔记，请稍候...</div>';
var count=0;
_biliPollTimer=setInterval(async function(){
try{var r=await api("GET","/api/action/visual-note/status/"+bvid);
if(r.ok){
clearInterval(_biliPollTimer);
_renderVisualNoteResult(r,box);
}else if(r.error){
clearInterval(_biliPollTimer);
box.innerHTML='<div style="color:var(--red);padding:12px">❌ '+r.error+'</div>';
}
count++;if(count>120){clearInterval(_biliPollTimer);box.innerHTML+='<div style="color:var(--yellow)">⏰ 超时，请稍后刷新</div>';}
}catch(e){}
},3000)}
function _renderVisualNoteResult(r,box){
var md=r.markdown||"";
// 提取 TOC
var toc='';var lines=md.split('\n');
for(var i=0;i<lines.length;i++){
var m=lines[i].match(/^## (.+)$/);
if(m){var aid=m[1].toLowerCase().replace(/[^\w\u4e00-\u9fff]+/g,'-');toc+='<li><a href="#'+aid+'" onclick="document.getElementById(\''+aid+'\').scrollIntoView({behavior:\'smooth\'})">'+m[1]+'</a></li>';}
}
// 加入锚点
for(var i=0;i<lines.length;i++){
var m=lines[i].match(/^## (.+)$/);
if(m){var aid=m[1].toLowerCase().replace(/[^\w\u4e00-\u9fff]+/g,'-');lines[i]='<h2 id="'+aid+'" style="border-bottom:1px solid var(--border);padding-bottom:4px;margin-top:24px">'+m[1]+'</h2>';continue}
// 简单 markdown 渲染
if(lines[i].match(/^!\[/)){lines[i]='<div style="text-align:center;margin:12px 0">'+lines[i]+'</div>';continue}
if(lines[i].match(/^\*\*.*\*\*$/)){lines[i]='<p><strong>'+lines[i].replace(/^\*\*|\*\*$/g,'')+'</strong></p>';continue}
if(lines[i].trim())lines[i]='<p>'+lines[i]+'</p>';
else lines[i]='<br>';
}
var body=lines.join('\n');
// 渲染图片 (base64)
body=body.replace(/!\[([^\]]*)\]\(data:image\/jpeg;base64,([^)]+)\)/g,'<img src="data:image/jpeg;base64,$2" alt="$1" style="max-width:100%;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.3)">');
var title=r.title||r.bvid||'';
var html='';
if(toc){
html+='<div style="display:flex;gap:16px;align-items:flex-start"><div style="width:220px;flex-shrink:0;position:sticky;top:12px;background:var(--bg2);border:1px solid var(--border);border-radius:8px;padding:12px"><h4 style="margin:0 0 8px 0;font-size:14px">📑 目录</h4><ul style="list-style:none;padding:0;margin:0;font-size:12px;line-height:1.8">'+toc+'</ul></div>';
html+='<div style="flex:1;min-width:0;overflow-wrap:break-word"><h3 style="margin:0 0 12px 0">'+title+'</h3>'+body+'</div></div>';
}else{
html+='<h3>'+title+'</h3>'+body;
}
box.innerHTML=html;
// 将 markdown 图片替换为实际 img 标签
var imgs=box.querySelectorAll('p');
imgs.forEach(function(p){var t=p.textContent;if(t.match(/^!\[/)){var m2=t.match(/!\[([^\]]*)\]\(([^)]+)\)/);if(m2){p.innerHTML='<img src="'+m2[2]+'" alt="'+m2[1]+'" style="max-width:100%;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.3)">'}}});
}
async function runAgent(){
var g=document.getElementById("agentGoal").value.trim();
if(!g){toast("请输入目标描述","err");return}
var r=await api("POST","/api/action/agent-skill",{goal:g});toast(r.message,r.ok?"ok":"err")}
async function kbOrganize(){
if(!confirm("将对知识库进行AI自动分类整理，继续？"))return;
var r=await api("POST","/api/action/kb-organize");toast(r.message,"ok")}
async function kbRevisit(){
if(!confirm("将从已学内容中随机挑选进行复习，继续？"))return;
var r=await api("POST","/api/action/kb-revisit");toast(r.message,"ok")}
async function rf_kbStats(){
try{var r=await api("GET","/api/kb/stats");var h="<strong>"+r.total_files+"</strong> 篇知识 · 分类: ";
var cs=Object.keys(r.categories||{}).sort();for(var i=0;i<cs.length;i++){h+=cs[i]+" ("+r.categories[cs[i]]+") "}
document.getElementById("kbStatBox").innerHTML=h||"暂无知识库数据"}catch(e){}}
// ── ASR & Highlights ──
async function saveAsr(){var c=await api("GET","/api/config");if(!c)return;
c.asr=c.asr||{};c.asr.enabled=document.getElementById("asrEnabled").value=="1";
c.asr.backend=document.getElementById("asrBackend").value;
c.asr.language=document.getElementById("asrLang").value;
c.asr.speaker_separation=document.getElementById("asrSep").value=="1";
var r=await api("POST","/api/config",c);
document.getElementById("asrMsg").innerHTML=r.ok?'<span style="color:var(--green)">已保存</span>':'<span style="color:var(--red)">'+r.message+'</span>'}
async function saveDry(){var c=await api("GET","/api/config");if(!c)return;
c.dry_goods=c.dry_goods||{};c.dry_goods.enabled=document.getElementById("dryEnabled").value=="1";
c.dry_goods.min_score=parseFloat(document.getElementById("dryMinScore").value)||8.0;
c.dry_goods.folder_name=document.getElementById("dryFolder").value||"highlights";
var r=await api("POST","/api/config",c);
document.getElementById("dryMsg").innerHTML=r.ok?'<span style="color:var(--green)">已保存</span>':'<span style="color:var(--red)">'+r.message+'</span>'}
async function loadAsrHighlight(){var c=await api("GET","/api/config");if(!c)return;
if(c.asr){document.getElementById("asrEnabled").value=c.asr.enabled?"1":"0";
document.getElementById("asrBackend").value=c.asr.backend||"funasr";
document.getElementById("asrLang").value=c.asr.language||"zh";
document.getElementById("asrSep").value=c.asr.speaker_separation!==false?"1":"0"}
if(c.dry_goods){document.getElementById("dryEnabled").value=c.dry_goods.enabled?"1":"0";
document.getElementById("dryMinScore").value=c.dry_goods.min_score||8.0;
document.getElementById("dryFolder").value=c.dry_goods.folder_name||"highlights"}}


// ── SYSTEM ──
function rf_sys(){listBackups();loadBackupOptions()}
async function loadBackupOptions(){try{var r=await api("GET","/api/backup/options"),g=r.groups||[];var h="";for(var i=0;i<g.length;i++){var x=g[i];h+='<label class="check-row"><input type="checkbox" value="'+esc(x.id)+'" '+(x.default?'checked':'')+'><span><b>'+esc(x.label)+'</b><small>'+esc(x.description)+' · '+esc(x.size)+'</small></span></label>'}document.getElementById("backupOptions").innerHTML=h}catch(e){}}
async function exportConfig(){
var boxes=document.querySelectorAll("#backupOptions input:checked"),groups=[];for(var i=0;i<boxes.length;i++)groups.push(boxes[i].value);var r=await api("POST","/api/export",{groups:groups});document.getElementById("exportMsg").innerHTML=r.ok?
"<span class=\"tg tg-suc\">"+r.message+"</span>":"<span class=\"tg tg-dan\">"+r.message+"</span>"}
async function listBackups(){
try{var r=await api("GET","/api/import");var fs=r.files||[];
if(!fs.length){document.getElementById("backupList").innerHTML="<div class=\"emp\">暂无备份文件</div>";return}
var h="<table class=\"tb\"><tr><th>文件名</th><th>时间</th><th>大小</th><th>操作</th></tr>";
for(var i=0;i<fs.length;i++){var f=fs[i];h+="<tr><td class=\"mono\">"+f.name+"</td><td>"+f.mtime+"</td><td>"+f.size+"</td><td><button class=\"btn btn-sm btn-pr\" onclick=\"importConfig('"+f.name+"')\">恢复</button></td></tr>"}
h+="</table>";document.getElementById("backupList").innerHTML=h}catch(e){}}
async function importConfig(fn){
if(!confirm("确定从 "+fn+" 恢复所有配置？当前配置将被覆盖！"))return;
var r=await api("POST","/api/import/apply",{filename:fn});toast(r.message,r.ok?"ok":"err");if(r.ok)rf_dash()}
async function factoryReset(){
if(!confirm("确定恢复出厂设置？此操作不可逆！\n将删除所有配置、登录信息、数据文件！"))return;
// 🔒 服务端两步确认
var req=await api("POST","/api/factory-reset/request");
if(!req.ok){toast(req.message,"err");return}
var token=prompt("⚠ 最后确认：输入确认令牌以执行\n\n令牌: "+req.token+"\n（直接复制粘贴上面的令牌）");
if(!token||token!==req.token){toast("令牌不匹配，已取消","err");return}
var r=await api("POST","/api/factory-reset",{confirm_token:token});toast(r.message,r.ok?"ok":"err");if(r.ok){rf_dash();listBackups()}}

// ── TUTOR (v2.0.3) ──
var _tutorHistory=[],_tutorRelPaths=[];
function rf_tutor(){
var sel=document.getElementById("tutorFileSelect");
fetch("/api/kb/list-files").then(function(r){return r.json()}).then(function(d){
if(!d.ok){toast(d.message,"err");return}
sel.innerHTML='';
for(var i=0;i<d.files.length;i++){
var f=d.files[i],up=f.up_name?" @"+f.up_name:"";
sel.innerHTML+='<option value="'+esc(f.rel_path)+'">['+f.category_path+'] '+esc(f.title)+up+' ('+f.size_kb+'KB)</option>';
}
}).catch(function(e){toast("加载文件列表失败","err")});
}
function tutorSelectAll(){
var sel=document.getElementById("tutorFileSelect");
for(var i=0;i<sel.options.length;i++)sel.options[i].selected=true;
}
function tutorSelectNone(){
var sel=document.getElementById("tutorFileSelect");
for(var i=0;i<sel.options.length;i++)sel.options[i].selected=false;
}
function _tutorGetSelected(){
var sel=document.getElementById("tutorFileSelect");
var out=[];
for(var i=0;i<sel.options.length;i++){
if(sel.options[i].selected)out.push(sel.options[i].value);
}
return out;
}
async function tutorLoadFile(){
var rps=_tutorGetSelected();
if(rps.length===0){toast("请至少选择一个知识文件","err");return}
_tutorRelPaths=rps;_tutorHistory=[];
document.getElementById("tutorChatLog").innerHTML='<div style="color:var(--text2);text-align:center;padding:20px">AI导师已就绪'+(rps.length>1?'（'+rps.length+'个文件）':'')+'，开始提问吧！</div>';
try{
var r=await api("POST","/api/kb/read-file",{rel_paths:rps});
if(!r.ok){toast(r.message,"err");return}
document.getElementById("tutorFileInfo").innerHTML='<span class="tg tg-suc">已加载 '+rps.length+' 个文件</span> ('+r.total_size+' 字符)';
document.getElementById("tutorContentPre").textContent=r.content||"(多文件内容已合并)";
document.getElementById("tutorContentBox").style.display="";
document.getElementById("tutorChatBox").style.display="";
document.getElementById("tutorResultBox").style.display="none";
}catch(e){toast("加载失败: "+e.message,"err")}
}
async function tutorSend(mode){
if(_tutorRelPaths.length===0){toast("请先加载文件","err");return}
var inp=document.getElementById("tutorInput");
var msg=inp.value.trim();
if(mode!="rewrite"&&mode!="html"&&!msg){toast("请输入问题","err");return}
if(mode=="rewrite"){
if(_tutorRelPaths.length>1){
if(!msg){toast("多文件改写请输入改写要求","err");return}
}else{msg=msg||"请优化结构、补充缺失知识点、修正不准确表述。"}
}
if(mode=="html")msg=msg||"请生成知识讲解网页。";

var log=document.getElementById("tutorChatLog");
if(mode=="chat"){
log.innerHTML+='<div class="chat-bubble user"><span style="color:var(--accent);font-weight:600">💬 你:</span> '+esc(msg)+'</div>';
inp.value="";
}
var stat=document.getElementById("tutorStatus");
stat.textContent="⏳ AI思考中...";

try{
var r=await api("POST","/api/kb/tutor-chat",{
rel_paths:_tutorRelPaths, message:msg,
history:_tutorHistory, mode:mode,
style:document.getElementById("tutorHtmlStyle").value
});
if(!r.ok){stat.textContent="";toast(r.message,"err");log.innerHTML+='<div class="chat-bubble" style="color:var(--red);border-left-color:var(--red)">❌ '+esc(r.message)+'</div>';return}
stat.textContent="";

if(mode=="chat"){
_tutorHistory.push({role:"user",content:msg},{role:"assistant",content:r.reply});
if(_tutorHistory.length>20)_tutorHistory=_tutorHistory.slice(-20);
log.innerHTML+='<div class="chat-bubble ai"><span style="color:var(--accent2);font-weight:600">🎓 导师:</span> '+esc(r.reply).replace(/\n/g,"<br>")+'</div>';
log.scrollTop=log.scrollHeight;
}else if(mode=="rewrite"){
var rb=document.getElementById("tutorResultBox");
var rc=document.getElementById("tutorResultContent");
rc.innerHTML='<div style="background:rgba(76,175,124,.08);border:1px solid rgba(76,175,124,.25);border-radius:6px;padding:10px;margin-bottom:10px"><strong>修改说明:</strong> '+esc(r.summary)+'</div><pre class="preview-pre" style="max-height:300px">'+esc(r.new_content||"")+'</pre>';
rb.style.display="";
var ra=document.getElementById("tutorResultActions");
ra.style.display="";
ra.innerHTML='<button class="btn btn-suc" onclick="tutorSaveRewrite()">💾 保存改写（覆盖原文件）</button>';
window._tutorRewriteContent=r.new_content||"";
}else if(mode=="html"){
var rb=document.getElementById("tutorResultBox");
var rc=document.getElementById("tutorResultContent");
rc.innerHTML='<div style="background:rgba(91,141,239,.08);border:1px solid rgba(91,141,239,.25);border-radius:6px;padding:10px;margin-bottom:10px"><strong>HTML已生成</strong></div><pre style="background:var(--bg3);border:1px solid var(--border);border-radius:6px;padding:10px;max-height:200px;overflow:auto;font-size:10px;white-space:pre-wrap">'+esc((r.html||"").substring(0,2000))+'...</pre>';
rb.style.display="";
var ra=document.getElementById("tutorResultActions");
ra.style.display="";
ra.innerHTML='<button class="btn btn-pr" onclick="tutorSaveHtml()">💾 保存HTML文件</button> <button class="btn btn-out" onclick="tutorPreviewHtml()">👁 预览HTML</button>';
window._tutorHtmlContent=r.html||"";
}
}catch(e){stat.textContent="";toast("请求失败: "+e.message,"err")}
}
async function tutorSaveRewrite(){
if(!window._tutorRewriteContent||_tutorRelPaths.length===0){toast("没有可保存的内容","err");return}
try{
var r=await api("POST","/api/kb/tutor-save",{rel_path:_tutorRelPaths[0],content:window._tutorRewriteContent});
toast(r.message,r.ok?"ok":"err");
}catch(e){toast("保存失败","err")}
}
async function tutorSaveHtml(){
if(!window._tutorHtmlContent){toast("没有可保存的HTML","err");return}
try{
var title=_tutorRelPaths.length>1?"multi_"+_tutorRelPaths.length+"files":(_tutorRelPaths[0]||"knowledge").split("/").pop().replace(".md","");
var r=await api("POST","/api/kb/tutor-html-save",{html:window._tutorHtmlContent,title:title});
toast(r.message,r.ok?"ok":"err");
if(r.ok&&r.path){document.getElementById("tutorResultContent").innerHTML+='<div style="margin-top:8px;font-size:11px;color:var(--green)">文件: '+esc(r.path)+'</div>'}
}catch(e){toast("保存失败","err")}
}
function tutorPreviewHtml(){
if(!window._tutorHtmlContent){toast("没有可预览的HTML","err");return}
var w=window.open("","_blank");
if(w){w.document.write(window._tutorHtmlContent);w.document.close()}
else{toast("请允许弹窗以预览HTML","err")}
}

// ── THEME SYSTEM ──
function switchTheme(t){
document.body.classList.add('theme-transition');
document.documentElement.setAttribute('data-theme',t);
localStorage.setItem('xiongda_theme',t);
setTimeout(()=>document.body.classList.remove('theme-transition'),600);
}
function applyTheme(){
var t;try{t=localStorage.getItem('xiongda_theme')}catch(e){t='aurora'};t=t||'aurora';
document.documentElement.setAttribute('data-theme',t);
var sel=document.getElementById('themeSelect');
if(sel)sel.value=t;
}
function applyBg(){
var cfg;try{cfg=JSON.parse(localStorage.getItem('xiongda_bg')||'{}')}catch(e){cfg={}};
var layer=document.getElementById('bgLayer');
if(!layer)return;
layer.innerHTML='';
var hasVideo=cfg.video&&cfg.video.trim();
var hasImage=cfg.image&&cfg.image.trim();
var opacity=(cfg.opacity!=null?cfg.opacity:35)/100;
if(hasVideo){
var v=document.createElement('video');
v.src=cfg.video;v.autoplay=true;v.loop=true;v.muted=true;v.playsInline=true;
v.style.cssText='width:100%;height:100%;object-fit:cover;opacity:'+opacity;
v.onerror=function(){layer.innerHTML='<div class="bg-default"></div>';};
layer.appendChild(v);
}else if(hasImage){
var img=document.createElement('img');
img.src=cfg.image;img.alt='';
img.style.cssText='width:100%;height:100%;object-fit:cover;opacity:'+opacity;
img.onerror=function(){layer.innerHTML='<div class="bg-default"></div>';};
layer.appendChild(img);
}else{
layer.innerHTML='<div class="bg-default"></div>';
}
var opEl=document.getElementById('bgOpacity');
var opVal=document.getElementById('bgOpacityVal');
if(opEl)opEl.value=(cfg.opacity!=null?cfg.opacity:35);
if(opVal)opVal.textContent=(cfg.opacity!=null?cfg.opacity:35)+'%';
}
function saveThemeSettings(){
var cfg={
image:document.getElementById('bgImage').value.trim(),
video:document.getElementById('bgVideo').value.trim(),
opacity:parseInt(document.getElementById('bgOpacity').value)||35
};
localStorage.setItem('xiongda_bg',JSON.stringify(cfg));
applyTheme();applyBg();
var msg=document.getElementById('themeMsg');
if(msg){msg.textContent='✅ 已保存';msg.style.color='var(--green)';setTimeout(()=>msg.textContent='',2000);}
}
function resetThemeSettings(){
localStorage.removeItem('xiongda_bg');
document.getElementById('bgImage').value='';
document.getElementById('bgVideo').value='';
document.getElementById('bgOpacity').value=35;
document.getElementById('bgOpacityVal').textContent='35%';
switchTheme('aurora');
applyBg();
var msg=document.getElementById('themeMsg');
if(msg){msg.textContent='✅ 已恢复默认';msg.style.color='var(--green)';setTimeout(()=>msg.textContent='',2000);}
}

// ── INIT ──
applyTheme();applyBg();
rf_dash();auto();syncBotMode();
(async function(){try{var d=await api('GET','/api/info');document.getElementById('uptime').textContent=d.uptime}catch(e){}})();
</script>
</body>
</html>'''

# ═══════════════════════════════════════════
#  API 路由
# ═══════════════════════════════════════════
@app.route('/')
def index():
    response = Response(_load_html(), mimetype='text/html')
    # The panel is a single HTML document with inline JavaScript. Serving a
    # cached copy can leave old click handlers active after an update.
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route('/api/onboarding', methods=['GET', 'POST'])
def api_onboarding():
    """Persist onboarding state so a known user is not treated as new per browser."""
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.setdefault('web', {})
    if request.method == 'GET':
        state = str(web_cfg.get('onboarding_state') or 'legacy')
        return jsonify(ok=True, state=state, auto_show=(state == 'pending'))

    body = request.get_json(force=True, silent=True) or {}
    state = str(body.get('state') or '').strip().lower()
    if state not in {'completed', 'skipped'}:
        return jsonify(ok=False, message='Invalid onboarding state'), 400
    web_cfg['onboarding_state'] = state
    if not write_json(CONFIG_FILE, config):
        return jsonify(ok=False, message='Failed to save onboarding state'), 500
    return jsonify(ok=True, state=state, auto_show=False)


# 项目图标（网页左上角 logo / favicon）—— 从仓库根目录的 image.png 提供
_ICON_FILE = BASE_DIR / "app-icons" / "7de15f3bb6e5ac30291e48bc3f15e23f.png"


@app.route('/assets/js/<path:filename>')
def assets_js(filename):
    """Serve bundled front-end assets (Chart.js / lucide) with local fallback."""
    safe = Path(filename).name
    asset_file = BASE_DIR / "assets" / "js" / safe
    if asset_file.exists() and safe.endswith((".js", ".css")):
        mimetype = "application/javascript" if safe.endswith(".js") else "text/css"
        return Response(asset_file.read_bytes(), mimetype=mimetype)
    return Response(status=404)


@app.route('/app-icon')
def app_icon():
    if _ICON_FILE.exists():
        response = Response(_ICON_FILE.read_bytes(), mimetype='image/png')
        response.headers['Cache-Control'] = 'no-store, max-age=0'
        return response
    return Response(status=404)

@app.route('/ppt')
def ppt_panel():
    """PPT生成面板页面"""
    ppt_html = BASE_DIR / "ppt_panel.html"
    if ppt_html.exists():
        return ppt_html.read_text(encoding='utf-8')
    return "<h1>PPT面板文件不存在</h1>", 404

def _has_valid_bili_cookies():
    """Check the minimum credential set required by the Bilibili client."""
    if not COOKIE_FILE.exists():
        return False
    try:
        c = read_json(COOKIE_FILE)
        sessdata = str((c or {}).get('SESSDATA') or '').strip()
        bili_jct = str((c or {}).get('bili_jct') or '').strip()
        uid = str((c or {}).get('DedeUserID') or '').strip()
        return len(sessdata) >= 10 and len(bili_jct) >= 8 and uid.isdigit()
    except Exception:
        return False


def _clear_bili_profile_cache() -> None:
    _bili_profile_cache.update(expires_at=0.0, profile=None)


def _bili_account_profile() -> dict | None:
    """Fetch only public account presentation data; cookies never leave this process."""
    now = time.time()
    if _bili_profile_cache.get("expires_at", 0.0) > now:
        return _bili_profile_cache.get("profile")
    if not _has_valid_bili_cookies():
        _clear_bili_profile_cache()
        return None
    try:
        cookies = read_json(COOKIE_FILE, {}) or {}
        cookie_header = "; ".join(
            f"{name}={value}" for name, value in cookies.items()
            if name in {"SESSDATA", "bili_jct", "DedeUserID", "buvid3"} and str(value).strip()
        )
        req = Request(
            "https://api.bilibili.com/x/web-interface/nav",
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
                "Referer": "https://www.bilibili.com/",
                "Cookie": cookie_header,
            },
        )
        with urlopen(req, timeout=8) as response:
            payload = json.loads(response.read().decode("utf-8", errors="replace"))
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        if int(payload.get("code", -1)) != 0 or not isinstance(data, dict):
            raise ValueError("Bilibili profile response is invalid")
        profile = {
            "uid": str(data.get("mid") or cookies.get("DedeUserID") or "")[:32],
            "name": str(data.get("uname") or "")[:80],
            "face": str(data.get("face") or "")[:1000],
        }
        _bili_profile_cache.update(expires_at=now + 600, profile=profile)
        return profile
    except Exception:
        _bili_profile_cache.update(expires_at=now + 60, profile=None)
        return None

# ── 信息 ──
@app.route('/api/info')
def api_info():
    running = _refresh_bot_state()
    lock_state = bot_lock_status(clean_stale=False)
    config = read_json(CONFIG_FILE)
    mood = read_json(DATA_DIR / "mood_state.json") or read_json(DATA_DIR / "web_mood.json")
    persona = read_json(DATA_DIR / "web_personas.json") or read_json(DATA_DIR / "personas.json")
    # fallback: 从 config.json 的 persona 段获取活跃人格
    if not persona or not persona.get('active'):
        cfg_persona = config.get('persona', {})
        active_name = cfg_persona.get('active_persona', '') or cfg_persona.get('prompt_name', '')
        if active_name:
            persona = dict(active=active_name, items={active_name: dict(name=active_name)})
    costs = read_json(DATA_DIR / "web_costs.json")
    api_cfg = config.get('api', {}) if isinstance(config, dict) else {}
    raw_project_info = config.get('project_info', {}) if isinstance(config, dict) else {}
    project_info = {
        key: str(raw_project_info.get(key, '') or '').strip()[:500]
        for key in ('name', 'summary', 'homepage', 'repository', 'license', 'contact', 'qq_group_url')
    } if isinstance(raw_project_info, dict) else {}
    api_key = api_cfg.get('unified_api_key', '') or os.getenv('BILI_AI_API_KEY', '')
    base_url = api_cfg.get('unified_base_url', '') or os.getenv('BILI_AI_BASE_URL', '')
    model_brain_cfg = api_cfg.get('model_brain', '') or api_cfg.get('model', '') or os.getenv('BILI_AI_MODEL_BRAIN', '')
    files = {}
    for name in ['config.json', 'bilibili_cookies.json', 'comment_log.json', 'private_message_log.json',
                 'user_profiles.json', 'mood_state.json', 'personas.json', 'bot_diary.json',
                 'self_evolution.json', 'agent_skill_log.json', 'bot_runtime_state.json']:
        files[name] = file_stat(DATA_DIR / name)

    upt = datetime.now() - panel_start
    us = f"{upt.days}d{upt.seconds//3600}h{(upt.seconds%3600)//60}m" if upt.days>0 else f"{upt.seconds//3600}h{(upt.seconds%3600)//60}m{upt.seconds%60}s"

    comment_mode = config.get('behavior', {}).get('comment_mode', 'real')
    ai_marker = config.get('behavior', {}).get('ai_marker', '')
    safety_enabled = config.get('reply_safety', {}).get('enabled', False)
    # These preview features are intentionally not exposed in public builds.
    diary_enabled = False
    evolution_enabled = False
    agent_enabled = config.get('agent', {}).get('enabled', False)
    pm_enabled = config.get('private_message', {}).get('enabled', False)
    notification_mode = config.get('standby', {}).get('notification_mode', True) if config.get('standby') else True
    model_brain = model_brain_cfg

    # 尝试读取待机状态
    standby_running_info = standby_running
    try:
        from brain.standby import load_stats
        standby_stats = load_stats()
    except Exception:
        standby_stats = {}
    return jsonify(dict(
        bot_running=running,
        bot_start_time=bot_start_time.strftime('%Y-%m-%d %H:%M:%S') if bot_start_time else None,
        bot_pid=bot_process.pid if running and bot_process else None,
        bot_exit_code=bot_last_exit_code,
        bot_error=bot_last_error,
        bot_lock_pid=lock_state["pid"],
        bot_lock_active=lock_state["locked"],
        bot_lock_stale=lock_state["stale"],
        uptime=us,
        uptime_seconds=max(0, int(upt.total_seconds())),
        version=APP_VERSION,
        project_info=project_info,
        api_configured=bool(api_key and base_url and model_brain),

        bili_logged_in=_has_valid_bili_cookies(),
        bili_profile=_bili_account_profile(),
        cookie_file=str(COOKIE_FILE),
        config_file=str(CONFIG_FILE),
        user_data_dir=str(USER_DATA_DIR),
        config_sections=len(config),
        data_files=sum(1 for f in files.values() if f['exists']),
        mood=dict(mood=mood.get('mood','?'), energy=mood.get('energy','?')) if mood else None,
        persona=dict(active=persona.get('active','')) if persona else None,
        cost_total=costs.get('total',0) if costs else 0,
        files=files,
        comment_mode=comment_mode,
        ai_marker=ai_marker,
        safety_enabled=safety_enabled,
        diary_enabled=diary_enabled,
        evolution_enabled=evolution_enabled,
        agent_enabled=agent_enabled,
        pm_enabled=pm_enabled,
        notification_mode=notification_mode,
        standby_running=standby_running_info,
        standby_stats=standby_stats,
        model_brain=model_brain,
        python_version=sys.version.split()[0],
        platform=sys.platform,
        cwd=str(BASE_DIR),
        asr_enabled=config.get('asr', {}).get('enabled', False),
        asr_backend=config.get('asr', {}).get('backend', 'funasr'),
    ))

# ── 配置 ──
@app.route('/api/config', methods=['GET','POST'])
def api_config():
    if request.method=='GET':
        from core.config import load_config
        return jsonify(load_config())
    try:
        data = request.get_json(force=True)
        if not isinstance(data, dict):
            return jsonify(dict(ok=False, message='配置必须是 JSON 对象')), 400
        # Save through the config layer: it keeps protected terms encrypted on
        # disk and refreshes the configured knowledge-base directory.
        from core.config import load_config, save_config
        current = load_config()
        # 防 '[已隐藏]' 占位符通过保存写回真实配置（有现有值保留，无则删字段）
        from utils.storage import strip_hidden_placeholders
        data = strip_hidden_placeholders(data, current)
        current.update(data)
        ok = save_config(current)
        if ok:
            import core.config as core_config
            core_config.config.clear()
            core_config.config.update(load_config())
        return jsonify(dict(ok=ok, message='配置已保存' if ok else '保存失败'))
    except Exception as e:
        return jsonify(dict(ok=False, message=redact_sensitive_text(str(e)))), 400


@app.route('/api/owner-share/status')
def api_owner_share_status():
    """Web and CLI use config.json plus this delivery-state file."""
    try:
        from services.owner_share import OwnerShareService
        return jsonify(OwnerShareService().status())
    except Exception as e:
        return jsonify(ok=False, message=redact_sensitive_text(str(e))), 500


@app.route('/api/owner-share/test', methods=['POST'])
def api_owner_share_test():
    """Inspect one video, then send an owner-only share through the normal review path."""
    body = request.get_json(silent=True) or {}
    source = str(body.get('video') or body.get('bvid') or '').strip()
    match = re.search(r'(BV[0-9A-Za-z]{10})', source, re.I)
    if not match:
        return jsonify(ok=False, message='请输入有效的 BV 号或 B 站视频链接'), 400
    bvid = match.group(1)
    from core.config import load_config
    owner_uid = str(load_config().get('owner_share', {}).get('owner_bili_uid') or '').strip()
    if not owner_uid.isdigit() or int(owner_uid) <= 0:
        return jsonify(ok=False, message='请先在主人分享配置中填写主人 B 站 UID'), 400
    try:
        from api.client import BiliClient
        client = BiliClient()
        client._load_credential()
        if not client.credential:
            return jsonify(ok=False, message='B 站尚未登录，无法发送测试私信'), 400
        from brain.private_msg import PrivateMessageManager
        account_uid = int(getattr(client.credential, 'dedeuserid', 0) or 0)
        manager = PrivateMessageManager(client.credential, account_uid)
        from services.owner_share import compose_test_share_message
        from services.utils import BiliToolbox

        log_line(f'[OWNER_SHARE] Test share started: reading video materials for {bvid}')
        evidence = _run_coro(BiliToolbox(client.credential, account_uid).video_details(bvid))
        if not isinstance(evidence, dict):
            return jsonify(ok=False, message='视频资料读取失败，未发送测试分享'), 502
        title = re.sub(r'\s+', ' ', str(evidence.get('title') or '').strip())[:160]
        if not title:
            return jsonify(ok=False, message='未读取到视频标题，已取消发送'), 422
        try:
            note, materials, note_source = _run_coro(compose_test_share_message(evidence))
        except ValueError as exc:
            return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 422
        message = f'{note}\n《{title}》\nhttps://www.bilibili.com/video/{bvid}' if note else f'《{title}》\nhttps://www.bilibili.com/video/{bvid}'
        log_line(f"[OWNER_SHARE] Test video inspected: {bvid} | read {', '.join(materials)}")
        log_line(f"[OWNER_SHARE] Test share note prepared via {'AI' if note_source == 'ai' else 'link only (AI unavailable or unsafe output)'}: {bvid}")
        result = _run_coro(manager.send_reply(
            int(owner_uid), message,
            audit_payload={
                'owner_share': True, 'owner_share_bvid': bvid, 'owner_share_test': True,
                'owner_share_title': title,
                'owner_share_inspected': True, 'owner_share_materials': materials,
                'owner_share_note_source': note_source,
            },
        ))
        if isinstance(result, dict) and result.get('queued'):
            log_line(f'[OWNER_SHARE] Test share queued for review: {bvid}')
            return jsonify(ok=True, queued=True, bvid=bvid, title=title, materials=materials, note_source=note_source,
                           message='已读取视频资料，测试分享已进入行为审核队列')
        if isinstance(result, dict) and result.get('sent') is False:
            reason = redact_sensitive_text(str(result.get('message') or result.get('code') or '平台未接受私信'))
            log_line(f'[OWNER_SHARE] Test share rejected by platform: {reason}')
            return jsonify(ok=False, bvid=bvid, message=reason), 502
        log_line(f'[OWNER_SHARE] Test share accepted by Bilibili: {bvid}')
        return jsonify(ok=True, sent=True, bvid=bvid, title=title, materials=materials, note_source=note_source,
                       message='已读取视频资料，测试分享已由 B 站接受')
    except Exception as exc:
        message = redact_sensitive_text(str(exc))
        log_line(f'[OWNER_SHARE] Test share failed: {message}')
        return jsonify(ok=False, message=message), 500


@app.route('/api/interests-legacy', methods=['GET', 'POST'])
def api_interests():
    """Web and CLI share the same interests.json file."""
    try:
        from services.utils import InterestManager
        manager = InterestManager()
        if request.method == 'GET':
            return jsonify(ok=True, interests=manager.get_interests(), count=len(manager.get_interests()))
        body = request.get_json(force=True) or {}
        values = body.get('interests', [])
        if not isinstance(values, list):
            return jsonify(ok=False, message='兴趣列表格式不正确'), 400
        clean = []
        for value in values:
            term = str(value).strip().lower()
            if term and term not in clean:
                clean.append(term[:80])
        manager.interests = clean[:100]
        if not manager._save_interests():
            return jsonify(ok=False, message='兴趣列表保存失败'), 500
        log_line(f"[INTEREST] 已保存 {len(manager.interests)} 个兴趣关键词")
        return jsonify(ok=True, message=f'已保存 {len(manager.interests)} 个兴趣关键词',
                       interests=manager.interests, count=len(manager.interests))
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400

# ── 模型列表 ──
_interest_engine_lock = threading.RLock()
_INTEREST_WEIGHTS = {'high', 'medium', 'low'}
_INTEREST_MODES = {'simple', 'smart', 'ai_only', 'watch_all'}


def _load_interest_engine():
    """Load the same per-user interest engine file used by the CLI."""
    from services.interest_engine import InterestEngine
    return InterestEngine(str(Path(DATA_DIR) / 'interest_engine.json'))


def _reset_interest_engine_cache() -> None:
    """Make subsequent in-process engine lookups read the saved settings."""
    from services.interest_engine import reset_engine
    reset_engine()


def _clean_interest_term(value, label='关键词') -> str:
    term = str(value or '').strip().lower()
    if not term:
        raise ValueError(f'{label}不能为空')
    if len(term) > 80:
        raise ValueError(f'{label}不能超过 80 个字符')
    return term


def _interest_engine_payload(engine) -> dict:
    settings = engine.settings
    scoring = settings.get('scoring') if isinstance(settings.get('scoring'), dict) else {}
    entries = []
    for raw in engine.interests_list:
        if isinstance(raw, dict):
            keyword = str(raw.get('keyword') or '').strip()
            if not keyword:
                continue
            entries.append({
                'keyword': keyword,
                'weight': raw.get('weight') if raw.get('weight') in _INTEREST_WEIGHTS else 'medium',
                'synonyms': [str(item).strip()[:80] for item in raw.get('synonyms', []) if str(item).strip()][:20],
                'auto_suggested': bool(raw.get('auto_suggested', False)),
            })
        elif str(raw).strip():
            entries.append({'keyword': str(raw).strip(), 'weight': 'medium', 'synonyms': [], 'auto_suggested': False})
    entries.sort(key=lambda item: ({'high': 0, 'medium': 1, 'low': 2}[item['weight']], item['keyword']))
    return {
        'ok': True,
        'interests': entries,
        'negative_keywords': [str(item).strip()[:80] for item in engine.negative_keywords if str(item).strip()][:200],
        'settings': {
            'proxy_mode': settings.get('proxy_mode') if settings.get('proxy_mode') in _INTEREST_MODES else 'smart',
            'serendipity_rate': max(0, min(0.5, float(settings.get('serendipity_rate', 0.0) or 0))),
            'auto_sync_psycho': bool(settings.get('auto_sync_psycho', True)),
            'use_synonyms': bool(settings.get('use_synonyms', True)),
            'ai_suggest': bool(settings.get('ai_suggest', True)),
            'ai_suggest_interval': max(1, min(200, int(settings.get('ai_suggest_interval', 20) or 20))),
            'scoring_enabled': bool(scoring.get('enabled', True)),
            'dynamic_threshold': bool(scoring.get('dynamic_threshold', True)),
            'threshold_base': max(0, min(10, float(scoring.get('threshold_base', 6) or 6))),
        },
        'stats': engine.get_stats(),
        'storage_path': str(Path(engine.config_file)),
    }


@app.route('/api/interests', methods=['GET', 'POST'])
def api_interests_compat():
    """Legacy keyword-list API, now stored in the CLI v2 engine file."""
    try:
        with _interest_engine_lock:
            engine = _load_interest_engine()
            if request.method == 'GET':
                keywords = engine.get_keywords()
                return jsonify(ok=True, interests=keywords, count=len(keywords))
            body = request.get_json(force=True) or {}
            values = body.get('interests', [])
            if not isinstance(values, list):
                return jsonify(ok=False, message='兴趣列表格式不正确'), 400
            clean = []
            for value in values:
                term = _clean_interest_term(value)
                if term not in clean:
                    clean.append(term)
            # This legacy endpoint only receives plain strings. Preserve the
            # structured metadata already held by the v2 engine, especially
            # ``auto_suggested``; otherwise a routine compatibility save
            # turns every AI suggestion into a manual interest.
            existing = {
                str(item.get('keyword', '')).strip().lower(): item
                for item in engine.interests_list
                if isinstance(item, dict) and str(item.get('keyword', '')).strip()
            }
            engine.config['interests'] = [
                dict(existing[term]) if term in existing else {
                    'keyword': term, 'weight': 'medium', 'synonyms': [], 'auto_suggested': False,
                }
                for term in clean[:100]
            ]
            if not engine.save():
                return jsonify(ok=False, message='兴趣列表保存失败'), 500
            _reset_interest_engine_cache()
        log_line(f'[INTEREST] 已保存 {len(clean)} 个兴趣关键词')
        return jsonify(ok=True, message=f'已保存 {len(clean)} 个兴趣关键词', interests=clean, count=len(clean))
    except (TypeError, ValueError) as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 500


@app.route('/api/interest-engine', methods=['GET', 'POST'])
def api_interest_engine():
    """Structured v2 interest settings shared with the command-line menu."""
    try:
        with _interest_engine_lock:
            engine = _load_interest_engine()
            if request.method == 'GET':
                return jsonify(_interest_engine_payload(engine))
            body = request.get_json(force=True) or {}
            if not isinstance(body, dict):
                return jsonify(ok=False, message='请求格式不正确'), 400
            settings = engine.config.setdefault('settings', {})
            if 'proxy_mode' in body:
                mode = str(body['proxy_mode']).strip()
                if mode not in _INTEREST_MODES:
                    return jsonify(ok=False, message='未知的筛选策略'), 400
                settings['proxy_mode'] = mode
            if 'serendipity_rate' in body:
                rate = float(body['serendipity_rate'])
                if not 0 <= rate <= 0.5:
                    return jsonify(ok=False, message='探索比例必须在 0% 到 50% 之间'), 400
                settings['serendipity_rate'] = rate
            for key in ('auto_sync_psycho', 'use_synonyms', 'ai_suggest'):
                if key in body:
                    settings[key] = bool(body[key])
            if 'ai_suggest_interval' in body:
                settings['ai_suggest_interval'] = max(1, min(200, int(body['ai_suggest_interval'])))
            scoring = settings.setdefault('scoring', {})
            if 'scoring_enabled' in body:
                scoring['enabled'] = bool(body['scoring_enabled'])
            if 'dynamic_threshold' in body:
                scoring['dynamic_threshold'] = bool(body['dynamic_threshold'])
            if 'threshold_base' in body:
                threshold = float(body['threshold_base'])
                if not 0 <= threshold <= 10:
                    return jsonify(ok=False, message='评分阈值必须在 0 到 10 之间'), 400
                scoring['threshold_base'] = threshold
            if not engine.save():
                return jsonify(ok=False, message='兴趣设置保存失败'), 500
            _reset_interest_engine_cache()
        log_line('[INTEREST] 兴趣筛选策略已更新')
        return jsonify(message='兴趣筛选策略已保存', **_interest_engine_payload(_load_interest_engine()))
    except (TypeError, ValueError) as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 500


@app.route('/api/interest-engine/interests', methods=['POST'])
def api_interest_engine_upsert():
    try:
        body = request.get_json(force=True) or {}
        keyword = _clean_interest_term(body.get('keyword'))
        weight = str(body.get('weight', 'medium')).strip().lower()
        if weight not in _INTEREST_WEIGHTS:
            return jsonify(ok=False, message='兴趣权重无效'), 400
        synonyms_raw = body.get('synonyms', [])
        if isinstance(synonyms_raw, str):
            synonyms_raw = re.split(r'[,，\n]', synonyms_raw)
        if not isinstance(synonyms_raw, list):
            return jsonify(ok=False, message='同义词格式不正确'), 400
        synonyms = []
        for value in synonyms_raw:
            item = str(value).strip().lower()
            if item and item != keyword and item not in synonyms:
                synonyms.append(item[:80])
        with _interest_engine_lock:
            engine = _load_interest_engine()
            found = next((item for item in engine.interests_list if isinstance(item, dict) and str(item.get('keyword', '')).lower() == keyword), None)
            if found is None:
                engine.config.setdefault('interests', []).append({
                    'keyword': keyword, 'weight': weight, 'synonyms': synonyms[:20],
                    'auto_suggested': bool(body.get('auto_suggested', False)),
                })
                message = f'已添加兴趣：{keyword}'
            else:
                found['weight'] = weight
                found['synonyms'] = synonyms[:20]
                if 'auto_suggested' in body:
                    found['auto_suggested'] = bool(body.get('auto_suggested'))
                message = f'已更新兴趣：{keyword}'
            if not engine.save():
                return jsonify(ok=False, message='兴趣保存失败'), 500
            _reset_interest_engine_cache()
        log_line(f'[INTEREST] {message}')
        return jsonify(message=message, **_interest_engine_payload(_load_interest_engine()))
    except (TypeError, ValueError) as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 500


@app.route('/api/interest-engine/interests/<path:keyword>', methods=['DELETE'])
def api_interest_engine_remove(keyword):
    try:
        term = _clean_interest_term(keyword)
        with _interest_engine_lock:
            engine = _load_interest_engine()
            if not engine.remove_interest(term):
                return jsonify(ok=False, message='未找到该兴趣关键词'), 404
            _reset_interest_engine_cache()
        log_line(f'[INTEREST] 已移除兴趣：{term}')
        return jsonify(message=f'已移除兴趣：{term}', **_interest_engine_payload(_load_interest_engine()))
    except (TypeError, ValueError) as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 500


@app.route('/api/interest-engine/exclusions', methods=['POST'])
def api_interest_engine_add_exclusion():
    try:
        term = _clean_interest_term((request.get_json(force=True) or {}).get('keyword'), '避雷词')
        with _interest_engine_lock:
            engine = _load_interest_engine()
            if not engine.add_negative(term):
                return jsonify(ok=False, message='避雷词已存在'), 409
            _reset_interest_engine_cache()
        log_line(f'[INTEREST] 已添加避雷词：{term}')
        return jsonify(message=f'已添加避雷词：{term}', **_interest_engine_payload(_load_interest_engine()))
    except (TypeError, ValueError) as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 500


@app.route('/api/interest-engine/exclusions/<path:keyword>', methods=['DELETE'])
def api_interest_engine_remove_exclusion(keyword):
    try:
        term = _clean_interest_term(keyword, '避雷词')
        with _interest_engine_lock:
            engine = _load_interest_engine()
            if not engine.remove_negative(term):
                return jsonify(ok=False, message='未找到该避雷词'), 404
            _reset_interest_engine_cache()
        log_line(f'[INTEREST] 已移除避雷词：{term}')
        return jsonify(message=f'已移除避雷词：{term}', **_interest_engine_payload(_load_interest_engine()))
    except (TypeError, ValueError) as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 500


@app.route('/api/ai/presets')
def api_ai_presets():
    try:
        from core.config import PROVIDER_PRESETS
    except Exception:
        PROVIDER_PRESETS = {}
    active = ""
    try:
        from core.config import load_config
        config_data = load_config()
        api_config = config_data.get("api", {}) if isinstance(config_data, dict) else {}
        active = api_config.get("active_preset") or config_data.get("active_preset", "")
    except Exception:
        pass
    return jsonify(dict(presets=PROVIDER_PRESETS, active_preset=active))

# ── 模型列表 ──
@app.route('/api/models/list')
def api_models_list():
    """从配置的 API 端点获取可用模型列表"""
    config = read_json(CONFIG_FILE)
    api_key = (request.args.get('api_key') or '').strip() or config.get('api', {}).get('unified_api_key', '') or os.getenv('BILI_AI_API_KEY', '')
    base_url = (request.args.get('base_url') or '').strip() or config.get('api', {}).get('unified_base_url', '') or os.getenv('BILI_AI_BASE_URL', '')
    if not api_key or not base_url:

        return jsonify(dict(ok=False, message='请先配置 API Key 和 Base URL', models=[]))
    
    import urllib.request, ssl
    url = base_url.rstrip('/') + '/models'
    try:
        req = urllib.request.Request(url, headers={
            'Authorization': f'Bearer {api_key}',
            'User-Agent': 'bilibili_learning_bot/3.0',
        })
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read())
        raw_models = data.get('data', data if isinstance(data, list) else [])
        models = []
        for m in raw_models:
            mid = m.get('id', '') if isinstance(m, dict) else str(m)
            if mid and 'embed' not in mid.lower() and 'moderation' not in mid.lower() and 'dall-e' not in mid.lower() and 'tts' not in mid.lower() and 'whisper' not in mid.lower():
                models.append(dict(
                    id=mid,
                    owned_by=m.get('owned_by', '') if isinstance(m, dict) else '',
                ))
        models.sort(key=lambda x: x['id'])
        return jsonify(dict(ok=True, models=models, count=len(models)))
    except Exception as e:
        return jsonify(dict(ok=False, message=f'获取模型列表失败: {str(e)}', models=[], error=str(e)))

# ── 机器人控制 ──
@app.route('/api/bot/start', methods=['POST'])
def api_bot_start():
    try:
        data = request.get_json(force=True, silent=True) or {}
    except Exception:
        data = {}
    mode = data.get("mode", "current")
    if mode not in ("smart", "current"):
        mode = "current"
    ok, msg = start_bot_process(mode=mode)
    return jsonify(dict(ok=ok, message=msg, mode=mode))


@app.route('/api/bot/browse-flow', methods=['GET', 'POST'])
def api_bot_browse_flow():
    """Persist the recommendation selection strategy shared by Web and CLI."""
    from core.config import load_config, save_config

    config_data = load_config()
    video = config_data.setdefault("video", {})
    if request.method == 'GET':
        return jsonify(dict(
            ok=True,
            browse_mode=video.get("browse_mode", "candidate_review"),
            candidate_pool_size=max(5, min(100, int(video.get("candidate_pool_size", 20) or 20))),
        ))

    body = request.get_json(force=True, silent=True) or {}
    browse_mode = str(body.get("browse_mode") or "").strip()
    if browse_mode not in ("direct", "candidate_review"):
        return jsonify(ok=False, message="无效的推荐流选择方式"), 400
    video["browse_mode"] = browse_mode
    try:
        requested_pool_size = int(body.get("candidate_pool_size", video.get("candidate_pool_size", 20)) or 20)
    except (TypeError, ValueError):
        requested_pool_size = 20
    video["candidate_pool_size"] = max(5, min(100, requested_pool_size))
    ok = save_config(config_data)
    if ok:
        import core.config as core_config
        core_config.config.clear()
        core_config.config.update(load_config())
        label = f"{video['candidate_pool_size']} 条候选由 AI 筛选" if browse_mode == "candidate_review" else "推荐流随机选择"
        log_line(f"[CONFIG] 正常刷视频流已切换：{label}")
    return jsonify(
        ok=ok,
        browse_mode=video["browse_mode"],
        candidate_pool_size=video["candidate_pool_size"],
        message="推荐流设置已保存" if ok else "保存失败",
    )


@app.route('/api/bot/session-limits', methods=['GET', 'POST'])
def api_bot_session_limits():
    """Read or update the shared timed/count-limited browsing session."""
    from core.config import load_config, save_config

    config_data = load_config()
    session_cfg = config_data.setdefault("session", {})

    def _payload(ok=True, message=""):
        return dict(
            ok=ok,
            message=message,
            max_videos=max(0, int(session_cfg.get("max_videos", 0) or 0)),
            max_learned_videos=max(0, int(session_cfg.get("max_learned_videos", 0) or 0)),
            max_duration_minutes=max(0, int(session_cfg.get("max_duration_minutes", 0) or 0)),
            completion_action=(
                session_cfg.get("completion_action")
                if session_cfg.get("completion_action") in {"stop", "monitor"}
                else "stop"
            ),
        )

    if request.method == 'GET':
        return jsonify(_payload())

    body = request.get_json(force=True, silent=True) or {}
    try:
        session_cfg["max_videos"] = max(0, min(100000, int(body.get("max_videos", 0) or 0)))
        session_cfg["max_learned_videos"] = max(
            0, min(100000, int(body.get("max_learned_videos", 0) or 0)))
        session_cfg["max_duration_minutes"] = max(
            0, min(525600, int(body.get("max_duration_minutes", 0) or 0)))
    except (TypeError, ValueError):
        return jsonify(ok=False, message="运行限制必须填写非负整数"), 400
    action = str(body.get("completion_action") or "stop").strip().lower()
    if action not in {"stop", "monitor"}:
        return jsonify(ok=False, message="无效的完成动作"), 400
    session_cfg["completion_action"] = action
    ok = save_config(config_data)
    if ok:
        import core.config as core_config
        core_config.config.clear()
        core_config.config.update(load_config())
        label = "启动实时监听" if action == "monitor" else "停止机器人"
        log_line(f"[CONFIG] 会话限制已保存，完成后{label}")
    return jsonify(_payload(ok=ok, message="运行限制已保存" if ok else "保存失败"))

@app.route('/api/bot/stop', methods=['POST'])
def api_bot_stop():
    ok, msg = stop_bot_process()
    return jsonify(dict(ok=ok, message=msg))

@app.route('/api/bot/output')
def api_bot_output():
    try:
        limit = max(1, min(int(request.args.get('limit') or 80), 5000))
    except (TypeError, ValueError):
        limit = 80
    running = _refresh_bot_state()
    with bot_output_lock:
        lines = _read_runtime_log(BOT_RUNTIME_LOG_FILE, bot_output_lines, limit=limit)
    return jsonify(dict(output='\n'.join(lines) if lines else '等待输出...', running=running,
                        exit_code=bot_last_exit_code))

@app.route('/api/bot/restart', methods=['POST'])
def api_bot_restart():
    started = time.perf_counter()
    body = request.get_json(force=True, silent=True) or {}
    mode = body.get('mode', 'current')
    if mode not in ('smart', 'current'):
        mode = 'current'
    ok, stop_message = stop_bot_process()
    if not ok:
        return jsonify(ok=False, message=stop_message)
    ok, start_message = start_bot_process(mode)
    return jsonify(ok=ok, message=start_message, mode=mode,
                   elapsed=round(time.perf_counter() - started, 3))

@app.route('/api/bot/clear', methods=['POST'])
def api_bot_clear():
    global bot_output_lines
    with bot_output_lock:
        bot_output_lines.clear()
    try:
        BOT_RUNTIME_LOG_FILE.write_text('', encoding='utf-8')
    except OSError:
        pass
    return jsonify(dict(ok=True, message='日志已清空'))


@app.route('/api/logs')
def api_logs():
    """Serve complete persisted logs for the dedicated web log viewer."""
    source = (request.args.get('source') or 'all').strip().lower()
    try:
        limit = max(1, min(int(request.args.get('limit') or 1200), 5000))
    except (TypeError, ValueError):
        limit = 1200
    entries = []
    if source in {'all', 'bot'}:
        with bot_output_lock:
            entries.extend(('bot', line) for line in _read_runtime_log(BOT_RUNTIME_LOG_FILE, bot_output_lines, limit))
    if source in {'all', 'monitor'}:
        with monitor_output_lock:
            entries.extend(('monitor', line) for line in _read_runtime_log(MONITOR_RUNTIME_LOG_FILE, monitor_output_lines, limit))
    if source in {'all', 'reviews'}:
        from services.like_review import ActionReviewInbox
        for entry in reversed(ActionReviewInbox(DATA_DIR).audit(limit)):
            detail = entry.get('error') or ''
            if not detail and entry.get('execution'):
                detail = _review_execution_display(entry.get('action_type', ''), entry.get('execution'))
            entries.append(('review', f"[{entry.get('time', '')}] [REVIEW] {entry.get('event', '')}: {entry.get('action_label') or entry.get('action_type')} | {entry.get('title', '')}" + (f" | {detail}" if detail else '')))
    entries = [
        item for _, item in sorted(
            enumerate(entries),
            key=lambda indexed: _runtime_log_sort_key(indexed[1][1], indexed[0]),
        )
    ]
    return jsonify(ok=True, source=source, lines=[{'source': kind, 'text': redact_sensitive_text(text)} for kind, text in entries[-limit:]])

# ── 实时监听 ──
monitor_process = None
monitor_running = False
monitor_output_lines = collections.deque(maxlen=500)
monitor_output_lock = threading.Lock()
monitor_started_at = None
_ANSI_ESCAPE_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")


def _external_monitor_details():
    """Find a monitor process left alive by an earlier web-panel restart."""
    status = bot_lock_status(clean_stale=False)
    pid = status.get('pid') if status.get('locked') else None
    if not pid:
        return None
    if monitor_process is not None and monitor_process.poll() is None and monitor_process.pid == pid:
        return None
    try:
        import psutil
        process = psutil.Process(int(pid))
        command = ' '.join(process.cmdline()).lower()
        if 'brain.monitor' not in command and '--monitor' not in command:
            return None
        return {'pid': int(pid), 'started_at': datetime.fromtimestamp(process.create_time())}
    except Exception:
        return None

def _monitor_reader(pipe, prefix=""):
    """读取监听进程输出"""
    try:
        for line in iter(pipe.readline, ""):
            if not line: break
            # Monitor output is intentionally colourful in a terminal. The web
            # log is plain text, so strip only terminal escape sequences.
            text = _ANSI_ESCAPE_RE.sub("", line).rstrip()
            if text:
                rendered = _timestamp_runtime_line(prefix + text)
                with monitor_output_lock:
                    monitor_output_lines.append(rendered)
                _append_runtime_log(MONITOR_RUNTIME_LOG_FILE, rendered)
    except OSError:
        pass
    finally:
        try: pipe.close()
        except OSError: pass

def _start_monitor_process():
    """Start the monitor for both the API button and session handoff."""
    global monitor_process, monitor_running, monitor_started_at
    external = _external_monitor_details()
    if monitor_running or external:
        return False, '监听已在运行'
    if _refresh_bot_state():
        return False, '机器人主进程运行中，请先停止'
    if not _has_valid_bili_cookies():
        return False, 'B站尚未完成登录，请先扫码登录后再启动监听'

    frozen_runtime = bool(getattr(sys, "frozen", False))
    monitor_script = BASE_DIR / "brain" / "monitor.py"
    if not frozen_runtime and not monitor_script.exists():
        return False, f'找不到 {monitor_script}'

    log_line("📡 正在启动实时监听...")
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"

        monitor_command = [sys.executable, "--monitor"] if frozen_runtime else [sys.executable, "-m", "brain.monitor"]
        monitor_process = subprocess.Popen(
            monitor_command,
            cwd=str(BASE_DIR),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_background_process_flags(),
        )
        monitor_running = True
        monitor_started_at = datetime.now()
        threading.Thread(target=_monitor_reader, args=(monitor_process.stdout, ""), daemon=True).start()
        log_line("✅ 实时监听已启动")
        return True, '实时监听已启动'
    except Exception as e:
        log_line(f"❌ 启动监听失败: {e}")
        return False, str(e)


@app.route('/api/monitor/start', methods=['POST'])
def api_monitor_start():
    ok, message = _start_monitor_process()
    return jsonify(dict(ok=ok, message=message))

@app.route('/api/monitor/stop', methods=['POST'])
def api_monitor_stop():
    global monitor_process, monitor_running, monitor_started_at
    external = _external_monitor_details()
    if not monitor_running and not external:
        return jsonify(dict(ok=False, message='监听未在运行'))
    try:
        if monitor_process:
            log_line("⏹ 正在停止监听...")
            try:
                if monitor_process.stdin and not monitor_process.stdin.closed:
                    monitor_process.stdin.write("0\n")
                    monitor_process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            time.sleep(0.5)
            monitor_process.terminate()
            try: monitor_process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                monitor_process.kill()
            monitor_process = None
        elif external:
            import psutil
            process = psutil.Process(external['pid'])
            process.terminate()
            try:
                process.wait(timeout=8)
            except psutil.TimeoutExpired:
                process.kill()
    except Exception as e:
        log_line(f"停止监听异常: {e}")
    monitor_running = False
    monitor_started_at = None
    log_line("✅ 实时监听已停止")
    return jsonify(dict(ok=True, message='已停止'))

@app.route('/api/monitor/status')
def api_monitor_status():
    from brain.monitor import load_monitor_config, is_monitor_running
    cfg = load_monitor_config()
    # 从日志中读取统计
    stats = {"comments_processed": 0, "messages_processed": 0, "total_replies": 0, "errors": 0}
    stats_file = DATA_DIR / "monitor_stats.json"
    if stats_file.exists():
        try:
            with open(stats_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                stats = data.get("stats", stats)
        except Exception:
            pass
    global monitor_running, monitor_started_at
    if monitor_process is not None and monitor_process.poll() is not None:
        monitor_running = False
        monitor_started_at = None
    external = _external_monitor_details()
    active = monitor_running or external is not None
    started_at = monitor_started_at if monitor_running else (external or {}).get('started_at')
    elapsed_seconds = max(0, int((datetime.now() - started_at).total_seconds())) if active and started_at else 0
    hours, remainder = divmod(elapsed_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    uptime = f"{hours}h {minutes}m {seconds}s" if active else "-"
    return jsonify(dict(
        running=active,
        paused=bool(active and not cfg.get('enabled', True)),
        start_time=started_at.isoformat() if started_at else None,
        external_pid=(external or {}).get('pid'),
        config=cfg,
        stats=stats,
        uptime=uptime,
        uptime_seconds=elapsed_seconds,
    ))

@app.route('/api/monitor/config', methods=['POST'])
def api_monitor_config():
    from brain.monitor import save_monitor_config, load_monitor_config
    cfg = load_monitor_config()
    data = request.get_json(silent=True) or {}
    # 更新配置
    for key in ['comment_check_interval', 'private_msg_check_interval', 'auto_reply', 'max_replies_per_check', 'enabled',
                'at_mentions_enabled', 'video_question_enabled', 'custom_system_prompt', 'text_emoticons']:
        if key in data:
            cfg[key] = data[key]
    for key in ('comment_check_interval', 'private_msg_check_interval'):
        try:
            cfg[key] = max(5, int(cfg.get(key, 5)))
        except (TypeError, ValueError):
            cfg[key] = 5
    try:
        cfg['max_replies_per_check'] = max(1, min(20, int(cfg.get('max_replies_per_check', 5))))
    except (TypeError, ValueError):
        cfg['max_replies_per_check'] = 5
    cfg['custom_system_prompt'] = str(cfg.get('custom_system_prompt') or '')[:2000]
    cfg['text_emoticons'] = [str(value).strip()[:40] for value in cfg.get('text_emoticons', []) if str(value).strip()][:80]
    if save_monitor_config(cfg):
        return jsonify(dict(ok=True, message='监听配置已保存', config=cfg))
    return jsonify(dict(ok=False, message='保存失败'))


@app.route('/api/monitor/pause', methods=['POST'])
def api_monitor_pause():
    """Pause or continue the live monitor without terminating its process."""
    from brain.monitor import save_monitor_config, load_monitor_config
    cfg = load_monitor_config()
    data = request.get_json(silent=True) or {}
    paused = bool(data.get('paused')) if 'paused' in data else bool(cfg.get('enabled', True))
    cfg['enabled'] = not paused
    if not save_monitor_config(cfg):
        return jsonify(ok=False, message='暂停状态保存失败'), 500
    message = '实时监听已暂停，不会轮询或发送消息' if paused else '实时监听已继续'
    log_line(f"[MONITOR] {message}")
    return jsonify(ok=True, paused=paused, message=message, config=cfg)

@app.route('/api/monitor/output')
def api_monitor_output():
    try:
        limit = max(1, min(int(request.args.get('limit') or 80), 5000))
    except (TypeError, ValueError):
        limit = 80
    with monitor_output_lock:
        lines = _read_runtime_log(MONITOR_RUNTIME_LOG_FILE, monitor_output_lines, limit=limit)
    return jsonify(dict(output='\n'.join(lines) if lines else '等待输出...'))


@app.route('/api/monitor/clear', methods=['POST'])
def api_monitor_clear():
    with monitor_output_lock:
        monitor_output_lines.clear()
    try:
        MONITOR_RUNTIME_LOG_FILE.write_text('', encoding='utf-8')
    except OSError:
        pass
    return jsonify(ok=True, message='监听日志已清空')

# ── 待机模式（Standby） ──
standby_process: subprocess.Popen | None = None
standby_running = False
standby_output_lines: list = []
standby_output_lock = threading.Lock()

def _standby_reader(stream, tag=""):
    global standby_output_lines
    for line in iter(stream.readline, ''):
        if not line:
            break
        with standby_output_lock:
            standby_output_lines.append(line.rstrip('\n'))
            if len(standby_output_lines) > 500:
                standby_output_lines = standby_output_lines[-200:]

@app.route('/api/standby/start', methods=['POST'])
def api_standby_start():
    global standby_process, standby_running, standby_output_lines
    if standby_running:
        return jsonify(dict(ok=False, message='待机模式已在运行'))
    if bot_running:
        return jsonify(dict(ok=False, message='主Bot运行中，请先停止'))

    frozen_runtime = bool(getattr(sys, "frozen", False))
    standby_script = BASE_DIR / "brain" / "standby.py"
    if not frozen_runtime and not standby_script.exists():
        return jsonify(dict(ok=False, message=f'找不到 {standby_script}'))

    # 先保存最新配置
    data = request.get_json(silent=True) or {}
    if data:
        from brain.standby import save_standby_config, load_standby_config
        cfg = load_standby_config()
        for key in ['auto_reply', 'at_trigger_enabled', 'at_trigger_keywords',
                     'comment_check_interval', 'max_replies_per_check', 'reply_cooldown_seconds',
                     'ppt_auto_generate', 'ppt_theme', 'video_trigger_enabled', 'custom_prompt',
                     'asr_enabled', 'asr_backend', 'vision_enabled', 'comment_mode',
                     'comment_fetch_enabled', 'summary_style', 'summary_max_length',
                     'monitor_own_videos_only', 'enabled']:
            if key in data:
                cfg[key] = data[key]
        save_standby_config(cfg)

    log_line("[SB] 正在启动待机模式...")
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        standby_output_lines = []

        standby_command = [sys.executable, "--standby"] if frozen_runtime else [sys.executable, str(standby_script)]
        standby_process = subprocess.Popen(
            standby_command,
            cwd=str(BASE_DIR),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            env=env, text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=_background_process_flags(),
        )
        standby_running = True
        threading.Thread(target=_standby_reader, args=(standby_process.stdout, ""), daemon=True).start()
        log_line("[OK] 待机模式已启动")
        return jsonify(dict(ok=True, message='待机模式已启动'))
    except Exception as e:
        log_line(f"[ERR] 启动待机失败: {e}")
        return jsonify(dict(ok=False, message=str(e)))

@app.route('/api/standby/stop', methods=['POST'])
def api_standby_stop():
    global standby_process, standby_running
    if not standby_running:
        return jsonify(dict(ok=False, message='待机模式未在运行'))
    try:
        if standby_process:
            log_line("[SB] 正在停止待机...")
            try:
                if standby_process.stdin and not standby_process.stdin.closed:
                    standby_process.stdin.write("0\n")
                    standby_process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                pass
            time.sleep(0.5)
            standby_process.terminate()
            try: standby_process.wait(timeout=8)
            except subprocess.TimeoutExpired: standby_process.kill()
            standby_process = None
    except Exception as e:
        log_line(f"[ERR] 停止待机异常: {e}")
    standby_running = False
    log_line("[OK] 待机模式已停止")
    return jsonify(dict(ok=True, message='已停止'))

@app.route('/api/standby/status')
def api_standby_status():
    from brain.standby import load_standby_config, load_stats
    cfg = load_standby_config()
    st = load_stats()
    return jsonify(dict(running=standby_running, config=cfg, stats=st))

@app.route('/api/standby/config', methods=['POST'])
def api_standby_config():
    from brain.standby import save_standby_config, load_standby_config
    cfg = load_standby_config()
    data = request.get_json(silent=True) or {}
    # 所有可配置字段
    for key in ['auto_reply', 'at_trigger_enabled', 'at_trigger_keywords',
                 'comment_check_interval', 'max_replies_per_check', 'reply_cooldown_seconds',
                 'ppt_auto_generate', 'ppt_theme', 'video_trigger_enabled', 'custom_prompt',
                 'asr_enabled', 'asr_backend', 'vision_enabled', 'comment_mode',
                 'comment_fetch_enabled', 'summary_style', 'summary_max_length',
                 'monitor_own_videos_only', 'notification_mode', 'enabled']:
        if key in data:
            cfg[key] = data[key]
    # 确保新字段有默认值
    cfg.setdefault("asr_enabled", False)
    cfg.setdefault("vision_enabled", True)
    cfg.setdefault("comment_fetch_enabled", True)
    cfg.setdefault("summary_style", "structured")
    cfg.setdefault("summary_max_length", 500)
    cfg.setdefault("monitor_own_videos_only", False)
    cfg.setdefault("notification_mode", True)
    if save_standby_config(cfg):
        return jsonify(dict(ok=True, message='待机配置已保存', config=cfg))
    return jsonify(dict(ok=False, message='保存失败'))

@app.route('/api/standby/output')
def api_standby_output():
    with standby_output_lock:
        lines = list(standby_output_lines)[-80:]
    return jsonify(dict(output='\n'.join(lines) if lines else '等待输出...'))

# ── PPT生成面板 API ──
@app.route('/api/ppt/generate', methods=['POST'])
def api_ppt_generate():
    """异步生成PPT风格HTML"""
    data = request.get_json(silent=True) or {}
    bvid = data.get('bvid', '').strip()
    themes = data.get('themes', ['claude_slides'])
    mode = data.get('mode', 'ppt')  # 'ppt' or 'default'
    custom_prompt = data.get('custom_prompt', '')

    if not bvid:
        return jsonify(dict(ok=False, message='请提供BV号'))

    if isinstance(themes, str):
        themes = [themes]

    def _do_generate():
        api_key = ""
        base_url = ""
        model = "qwen/qwen3.5-122b-a10b"
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                api_cfg = cfg.get('api', {})
                api_key = api_cfg.get('unified_api_key', '') or os.getenv('BILI_AI_API_KEY', '')
                base_url = api_cfg.get('unified_base_url', '') or os.getenv('BILI_AI_BASE_URL', '')
                model = api_cfg.get('model_name', model)
            except Exception:
                pass

        if not api_key or not base_url:
            log_line("[PPT] API未配置，无法生成")
            return

        cookies = None
        if COOKIE_FILE.exists():
            try:
                with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                    cookies = json.load(f)
            except Exception:
                pass

        async def run():
            from services.video_to_ppt import generate_ppt_from_bvid
            for theme in themes:
                try:
                    result = await generate_ppt_from_bvid(
                        bvid, api_key, base_url, model,
                        cookies_obj=cookies, theme=theme,
                        open_browser=False
                    )
                    if result['success']:
                        log_line(f"[PPT] {theme} 主题已生成: {result['html_path']}")
                    else:
                        log_line(f"[PPT] {theme} 主题失败: {result.get('error','')}")
                except Exception as e:
                    log_line(f"[PPT] {theme} 异常: {e}")

        if os.name == 'nt':
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        asyncio.run(run())

    threading.Thread(target=_do_generate, daemon=True).start()
    return jsonify(dict(ok=True, message=f'正在生成 {len(themes)} 个主题的PPT...'))

@app.route('/api/ppt/list')
def api_ppt_list():
    """列出已生成的HTML文件"""
    export_dir = HTML_EXPORTS_DIR
    files = []
    if export_dir.exists():
        for f in sorted(export_dir.glob("*.html"), key=lambda x: x.stat().st_mtime, reverse=True)[:20]:
            files.append({
                'name': f.name,
                'size': f.stat().st_size,
                'time': datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                'path': str(f),
            })
    return jsonify(dict(files=files))

@app.route('/api/ppt/themes')
def api_ppt_themes():
    """返回可用主题列表"""
    from services.video_to_ppt import THEMES
    return jsonify(dict(themes=[
        {'id': k, 'name': v['name'], 'preview_colors': [v['primary'], v['accent'], v['bg_start']]}
        for k, v in THEMES.items()
    ]))

# ── B站登录 ──
@app.route('/api/bili/qr/start', methods=['POST'])
def api_bili_qr_start():
    global qr_state
    body = request.get_json(silent=True) or {}
    force = bool(body.get('force'))
    with qr_state_lock:
        active = qr_state.get('active', False)
        current = dict(qr_state)
        if active and not force:
            image = current.get('img_b64', '')
            if image:
                return jsonify(dict(
                    ok=True,
                    reused=True,
                    img=image,
                    message=current.get('message') or '登录二维码仍有效，请继续扫码',
                    status=current.get('status', 'waiting_scan'),
                ))
            return jsonify(dict(ok=False, message='二维码正在生成，请稍候再试', status=current.get('status', 'generating'))), 409
        session_id = _new_qr_session_locked()
    threading.Thread(target=do_qr_login, args=(session_id,), daemon=True).start()
    # wait for QR code to actually be generated (up to 10s)
    for _ in range(20):
        time.sleep(0.5)
        with qr_state_lock:
            current = dict(qr_state)
        if current.get('session_id') != session_id:
            return jsonify(dict(ok=False, img='', message='二维码已被新的登录请求替换，请重新生成', status='replaced')), 409
        if current.get('img_b64') or current.get('status') in ('waiting_scan', 'error', 'timeout'):
            break
    with qr_state_lock:
        current = dict(qr_state)
    image = current.get('img_b64', '')
    status = current.get('status', '')
    message = current.get('message', '')
    if not image:
        if status not in ('error', 'timeout'):
            message = message or '二维码生成超时，请稍后重试'
        return jsonify(dict(ok=False, img='', message=message, status=status)), 503
    return jsonify(dict(ok=True, img=image, message=message, status=status))


@app.route('/api/bili/qr/image')
def api_bili_qr_image():
    """Serve the current QR as PNG so browsers do not need to render a data URL."""
    image = qr_state.get('img_b64', '')
    if not image:
        return jsonify(dict(ok=False, message='当前没有可用的登录二维码')), 404
    try:
        png = base64.b64decode(image, validate=True)
    except (ValueError, TypeError):
        return jsonify(dict(ok=False, message='登录二维码数据无效')), 500
    response = Response(png, mimetype='image/png')
    response.headers['Cache-Control'] = 'no-store, max-age=0'
    return response

@app.route('/api/bili/qr/status')
def api_bili_qr_status():
    return jsonify(dict(
        status=qr_state.get('status', 'idle'),
        message=qr_state.get('message', ''),
        uid=qr_state.get('uid', ''),
        active=qr_state.get('active', False),
        has_image=bool(qr_state.get('img_b64')),
    ))

@app.route('/api/bili/logout', methods=['POST'])
def api_bili_logout():
    try:
        if COOKIE_FILE.exists():
            COOKIE_FILE.unlink()
        _clear_bili_profile_cache()
        log_line("B站登录信息已清除")
        return jsonify(dict(ok=True, message='已退出登录'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

# ── 人格管理 ──
def _sync_runtime_personas(data: dict) -> None:
    """Persist the Web persona envelope in the format used by the bot runtime."""
    items = data.get("items", {}) if isinstance(data, dict) else {}
    items = items if isinstance(items, dict) else {}
    active = str(data.get("active") or next(iter(items), "默认人格"))
    if active not in items and items:
        active = next(iter(items))
    write_json(DATA_DIR / "personas.json", {
        "active_persona": active,
        "personas": items,
    })


def _load_persona_envelope() -> dict:
    """Load the Web persona envelope, migrating the runtime format when needed."""
    web_path = DATA_DIR / "web_personas.json"
    web_data = read_json(web_path, {})
    web_items = web_data.get("items", {}) if isinstance(web_data, dict) else {}
    if isinstance(web_items, dict) and web_items:
        items = {
            str(key): dict(value) if isinstance(value, dict) else {"name": str(key)}
            for key, value in web_items.items()
        }
        active = str(web_data.get("active") or next(iter(items)))
        if active not in items:
            active = next(iter(items))
        data = {"active": active, "items": items}
        if data != web_data:
            write_json(web_path, data)
        return data

    runtime_data = read_json(DATA_DIR / "personas.json", {})
    runtime_items = runtime_data.get("personas", {}) if isinstance(runtime_data, dict) else {}
    if isinstance(runtime_items, dict) and runtime_items:
        items = {
            str(key): dict(value) if isinstance(value, dict) else {"name": str(key)}
            for key, value in runtime_items.items()
        }
        active = str(runtime_data.get("active_persona") or next(iter(items)))
        if active not in items:
            active = next(iter(items))
        data = {"active": active, "items": items}
    elif isinstance(runtime_data, dict) and runtime_data.get("name"):
        name = str(runtime_data["name"])
        data = {"active": name, "items": {name: dict(runtime_data)}}
    else:
        config = read_json(CONFIG_FILE, {})
        cfg_persona = config.get("persona", {}) if isinstance(config, dict) else {}
        active = str(
            cfg_persona.get("active_persona", "")
            or cfg_persona.get("prompt_name", "")
            or "默认人格"
        )
        data = {
            "active": active,
            "items": {
                active: {
                    "name": cfg_persona.get("prompt_name", "") or "AI小助手",
                    "system_prompt": "",
                    "style": "友好、专业",
                    "owner_prompt": "",
                    "rules": [],
                }
            },
        }

    # The runtime only knows personas.json, while the editor knows the Web
    # envelope. Persist both sides before any route mutates an item.
    write_json(web_path, data)
    _sync_runtime_personas(data)
    return data


def _resolve_persona_key(items: dict, requested_name: str) -> str | None:
    """Resolve an exact key first, then support legacy display-name routes."""
    if requested_name in items:
        return requested_name
    for key, item in items.items():
        if isinstance(item, dict) and str(item.get("name") or "").strip() == requested_name:
            return key
    return None


@app.route('/api/personas', methods=['GET','POST'])
def api_personas():
    data = _load_persona_envelope()

    if request.method=='GET':
        return jsonify(data)
    try:
        body = request.get_json(force=True)
        name = (body.get('name') or '').strip()
        if not name: return jsonify(dict(ok=False, message='名称不能为空')), 400
        data.setdefault('items', {})[name] = dict(
            name=name, system_prompt=body.get('system_prompt', ''),
            style=body.get('style',''), owner_prompt=body.get('owner_prompt',''),
            rules=body.get('rules',[]))
        write_json(DATA_DIR / "web_personas.json", data)
        _sync_runtime_personas(data)
        return jsonify(dict(ok=True, message=f'人设"{name}"已创建'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/personas/activate', methods=['POST'])
def api_personas_activate():
    data = _load_persona_envelope()
    try:
        body = request.get_json(force=True)
        name = (body.get('name') or '').strip()
        if name not in data.get('items', {}):
            return jsonify(dict(ok=False, message='人设不存在')), 404
        data['active'] = name
        write_json(DATA_DIR / "web_personas.json", data)
        _sync_runtime_personas(data)
        config = read_json(CONFIG_FILE, {})
        config.setdefault('persona', {})['active_persona'] = name
        config['persona']['prompt_name'] = data['items'][name].get('name', name)
        write_json(CONFIG_FILE, config)
        return jsonify(dict(ok=True, message=f'已切换为"{name}"'))

    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/personas/<name>', methods=['GET', 'PUT', 'DELETE'])
def api_personas_delete(name):
    data = _load_persona_envelope()
    items = data.get('items', {})
    key = _resolve_persona_key(items, name)
    if key is None:
        return jsonify(dict(ok=False, message='不存在')), 404
    if request.method == 'GET':
        return jsonify(dict(ok=True, item=items[key], key=key, active=data.get('active') == key))
    if request.method == 'PUT':
        body = request.get_json(force=True, silent=True) or {}
        new_name = (body.get('name') or key).strip()
        if not new_name:
            return jsonify(dict(ok=False, message='名称不能为空')), 400
        if new_name != key and new_name in items:
            return jsonify(dict(ok=False, message='该名称已存在')), 409
        item = dict(items[key])
        item.update(name=new_name, system_prompt=body.get('system_prompt', ''),
                    style=body.get('style', ''), owner_prompt=body.get('owner_prompt', ''),
                    rules=body.get('rules', []))
        del items[key]
        items[new_name] = item
        if data.get('active') == key:
            data['active'] = new_name
            config = read_json(CONFIG_FILE, {})
            config.setdefault('persona', {})['active_persona'] = new_name
            config['persona']['prompt_name'] = item.get('name', new_name)
            write_json(CONFIG_FILE, config)
        write_json(DATA_DIR / "web_personas.json", data)
        _sync_runtime_personas(data)
        return jsonify(dict(ok=True, message=f'人设"{new_name}"已保存', key=new_name, item=item))
    if len(data.get('items', {})) <= 1:
        return jsonify(dict(ok=False, message='至少保留一个人设')), 400
    del items[key]
    if data.get('active') == key:
        data['active'] = next(iter(items))
    write_json(DATA_DIR / "web_personas.json", data)
    _sync_runtime_personas(data)
    return jsonify(dict(ok=True, message=f'已删除"{name}"'))

# ── 评论日志 ──
@app.route('/api/comments')
def api_comments():
    limit = max(1, min(request.args.get('limit', 100, type=int), 500))
    period = str(request.args.get('period', '7d')).lower()
    kind = str(request.args.get('kind', 'all')).lower()
    query = str(request.args.get('q', '')).strip().lower()[:160]
    data = read_json(DATA_DIR / "comment_log.json", dict(items=[]))
    rows = []
    for collection_name in ('items', 'history'):
        collection = data.get(collection_name, []) if isinstance(data, dict) else []
        if isinstance(collection, list):
            rows.extend(item for item in collection if isinstance(item, dict))
    conversations = data.get('conversations', {}) if isinstance(data, dict) else {}
    if isinstance(conversations, dict):
        for thread_key, thread in conversations.items():
            if not isinstance(thread, dict):
                continue
            for turn in thread.get('turns', []):
                if isinstance(turn, dict):
                    rows.append({
                        'timestamp': turn.get('time', ''),
                        'action': 'reply' if turn.get('role') == 'assistant' else 'incoming',
                        'content': turn.get('content', ''), 'source': thread_key,
                        'target_user': thread_key.rsplit(':', 1)[-1], 'executed': True,
                    })
    now = datetime.now()
    days = {'today': 0, '7d': 7, '15d': 15, '30d': 30}.get(period)
    result = []
    seen = set()
    for it in rows:
        timestamp = str(it.get('time', it.get('timestamp', it.get('created_at', ''))))
        try:
            occurred = datetime.fromisoformat(timestamp.replace('Z', '+00:00')).replace(tzinfo=None)
        except (TypeError, ValueError):
            occurred = None
        if days is not None and occurred:
            if days == 0 and occurred.date() != now.date():
                continue
            if days and occurred < now - timedelta(days=days):
                continue
        action = str(it.get('type', it.get('action', 'comment')))
        category = 'blocked' if 'blocked' in action else ('reply' if action in {'reply', 'comment_reply'} else ('incoming' if action in {'incoming', 'receive'} else 'other'))
        content = str(it.get('content', it.get('text', it.get('incoming', ''))))
        source = str(it.get('source', it.get('target_user', '')))
        haystack = f'{content} {source} {action}'.lower()
        if kind != 'all' and category != kind:
            continue
        if query and query not in haystack:
            continue
        row_key = (timestamp, action, content, source)
        if row_key in seen:
            continue
        seen.add(row_key)
        result.append(dict(time=timestamp, type=action, category=category, content=content,
                           source=source, executed=it.get('executed', True),
                           reason=it.get('reason', ''), target_user=it.get('target_user', '')))
    result.sort(key=lambda item: item['time'], reverse=True)
    return jsonify(dict(items=result[:limit], total=len(result), period=period, kind=kind))


@app.route('/api/comments/clear', methods=['POST'])
def api_comments_clear():
    """Clear only the comment-log rows represented by the current UI filters."""
    body = request.get_json(silent=True) or {}
    if body.get("confirmed") is not True:
        return jsonify(ok=False, message="请先确认清空评论日志"), 400
    period = str(body.get("period") or "all").lower()
    kind = str(body.get("kind") or "all").lower()
    query = str(body.get("q") or "").strip().lower()[:160]
    now = datetime.now()
    days = {"today": 0, "7d": 7, "15d": 15, "30d": 30}.get(period)

    def matches(raw: dict, action: str, content: str, source: str, timestamp: str) -> bool:
        try:
            occurred = datetime.fromisoformat(timestamp.replace("Z", "+00:00")).replace(tzinfo=None)
        except (TypeError, ValueError):
            occurred = None
        if days is not None and occurred:
            if days == 0 and occurred.date() != now.date():
                return False
            if days and occurred < now - timedelta(days=days):
                return False
        category = "blocked" if "blocked" in action else ("reply" if action in {"reply", "comment_reply"} else ("incoming" if action in {"incoming", "receive"} else "other"))
        if kind != "all" and category != kind:
            return False
        return not query or query in f"{content} {source} {action}".lower()

    path = Path(DATA_DIR) / "comment_log.json"
    data = read_json(path, {"items": []})
    data = data if isinstance(data, dict) else {"items": []}
    removed = 0
    for collection_name in ("items", "history"):
        rows = data.get(collection_name, [])
        if not isinstance(rows, list):
            continue
        kept = []
        for row in rows:
            if not isinstance(row, dict):
                kept.append(row)
                continue
            timestamp = str(row.get("time", row.get("timestamp", row.get("created_at", ""))))
            action = str(row.get("type", row.get("action", "comment")))
            content = str(row.get("content", row.get("text", row.get("incoming", ""))))
            source = str(row.get("source", row.get("target_user", "")))
            if matches(row, action, content, source, timestamp):
                removed += 1
            else:
                kept.append(row)
        data[collection_name] = kept

    conversations = data.get("conversations")
    if isinstance(conversations, dict):
        for thread_key, thread in list(conversations.items()):
            if not isinstance(thread, dict):
                continue
            turns = thread.get("turns", [])
            if not isinstance(turns, list):
                continue
            kept_turns = []
            for turn in turns:
                if not isinstance(turn, dict):
                    kept_turns.append(turn)
                    continue
                action = "reply" if turn.get("role") == "assistant" else "incoming"
                timestamp = str(turn.get("time", ""))
                content = str(turn.get("content", ""))
                if matches(turn, action, content, thread_key, timestamp):
                    removed += 1
                else:
                    kept_turns.append(turn)
            if kept_turns:
                thread["turns"] = kept_turns
            else:
                conversations.pop(thread_key, None)
    write_json(path, data)
    log_line(f"[COMMENTS] 已清空评论日志 {removed} 条 (period={period}, kind={kind})")
    return jsonify(ok=True, removed=removed, message=f"已清空 {removed} 条评论日志")

# ── 用户画像 ──
def _profile_store_users(data) -> dict:
    """Read both the bot's flat profile file and the historical web wrapper."""
    if not isinstance(data, dict):
        return {}
    wrapped = data.get("users")
    return wrapped if isinstance(wrapped, dict) else data


def _normalized_profiles() -> dict:
    merged = {}
    for source in (
        _profile_store_users(read_json(DATA_DIR / "user_profiles.json", {})),
        _profile_store_users(read_json(DATA_DIR / "web_user_profiles.json", {})),
    ):
        for uid, raw in source.items():
            if isinstance(raw, dict):
                merged[str(uid)] = {**merged.get(str(uid), {}), **raw}
    users = {}
    for uid, raw in merged.items():
        profile = dict(raw)
        try:
            affinity = float(profile.get("affinity", 0))
        except (TypeError, ValueError):
            affinity = 0.0
        score = round(affinity * 100) if -1.0 <= affinity <= 1.0 else round(affinity)
        notes = profile.get("notes", [])
        if not isinstance(notes, list):
            notes = [str(notes)] if notes else []
        if profile.get("impression"):
            notes.append(str(profile["impression"]))
        tags = profile.get("tags", [])
        if not isinstance(tags, list):
            tags = [str(tags)] if tags else []
        users[uid] = {
            **profile,
            "uid": uid,
            "affinity": affinity,
            "affinity_score": max(-100, min(100, score)),
            "interaction_count": int(profile.get("interactions", profile.get("interaction_count", profile.get("comment_count", 0))) or 0),
            "last_interaction": profile.get("last_seen", profile.get("last_interaction", profile.get("updated_at", ""))),
            "notes": notes[-30:],
            "tags": [str(tag).strip()[:32] for tag in tags if str(tag).strip()][:20],
        }
    return users


@app.route('/api/users')
def api_users():
    users = _normalized_profiles()
    return jsonify(dict(
        ok=True,
        users=users,
        summary={
            "total": len(users),
            "interactions": sum(user["interaction_count"] for user in users.values()),
            "positive": sum(1 for user in users.values() if user["affinity_score"] >= 10),
            "caution": sum(1 for user in users.values() if user["affinity_score"] <= -40),
        },
    ))


@app.route('/api/users/update', methods=['POST'])
def api_users_update():
    """Edit local profile notes/tags without triggering any Bilibili action."""
    try:
        body = request.get_json(force=True) or {}
        uid = str(body.get("uid") or "").strip()
        if not uid:
            return jsonify(ok=False, message="缺少用户 UID"), 400
        name = str(body.get("name") or "").strip()[:80]
        tags = body.get("tags", [])
        if not isinstance(tags, list):
            tags = str(tags).split(",")
        tags = [str(tag).strip()[:32] for tag in tags if str(tag).strip()][:20]
        notes = body.get("notes", [])
        if not isinstance(notes, list):
            notes = [str(notes)]
        notes = [str(note).strip()[:300] for note in notes if str(note).strip()][-30:]
        path = DATA_DIR / "user_profiles.json"
        data = read_json(path, {})
        store = _profile_store_users(data)
        profile = dict(store.get(uid) or {})
        profile.update({"name": name or profile.get("name", uid), "tags": tags, "notes": notes,
                        "updated_at": datetime.now().isoformat(timespec="seconds")})
        store[uid] = profile
        if isinstance(data.get("users"), dict):
            data["users"] = store
        else:
            data = store
        write_json(path, data)
        log_line(f"[PROFILE] 已更新用户画像: {uid}")
        return jsonify(ok=True, message="用户画像已保存", user=_normalized_profiles().get(uid, profile))
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400

# ── 记忆 ──
def _web_diary_payload(data):
    """Expose a stable web shape while accepting historical diary files."""
    data = data if isinstance(data, dict) else {}
    entries = data.get('entries')
    if not isinstance(entries, list):
        entries = data.get('diaries', [])
    normalized = []
    for index, entry in enumerate(entries if isinstance(entries, list) else []):
        if not isinstance(entry, dict):
            continue
        item = dict(entry)
        # Historical entries did not have an id. Keep the API editable without
        # changing their content until the user explicitly updates one.
        item.setdefault('id', f"legacy-{index}-{item.get('time', '')}")
        normalized.append(item)
    return dict(entries=normalized)


def _web_evolution_payload(data):
    data = data if isinstance(data, dict) else {}
    events = data.get('events')
    if not isinstance(events, list):
        events = data.get('items', [])
    return dict(events=[entry for entry in events if isinstance(entry, dict)])


@app.route('/api/memory')
def api_memory():
    kb_dir = active_knowledge_base_dir()
    kb_total = 0
    kb_categories = {}
    if kb_dir.exists():
        for root, dirs, files in os.walk(kb_dir):
            rel = os.path.relpath(root, kb_dir)
            cat = rel.replace(os.sep, '/') if rel != '.' else '根目录'
            count = len([f for f in files if f.endswith('.md')])
            if count:
                kb_categories[cat] = count
                kb_total += count
    return jsonify(dict(
        diary=_web_diary_payload(read_json(DATA_DIR / "bot_diary.json", {})),
        evolution=_web_evolution_payload(read_json(DATA_DIR / "self_evolution.json", {})),
        knowledge=dict(exists=kb_dir.exists(), total_files=kb_total, categories=kb_categories),
    ))


@app.route('/api/watch-history')
def api_watch_history():
    """Return the bot's local viewing records, one compact card per video."""
    try:
        offset = max(0, int(request.args.get("offset", 0)))
        limit = max(1, min(500, int(request.args.get("limit", 36))))
    except (TypeError, ValueError):
        offset, limit = 0, 36
    query = str(request.args.get("q", "") or "").strip().casefold()
    filter_name = str(request.args.get("filter", "all") or "all").strip()
    all_cards = _watch_history_cards()
    cards = list(all_cards)
    if query:
        cards = [card for card in cards if query in " ".join((
            str(card.get("title") or ""), str(card.get("up") or ""),
            str(card.get("bvid") or ""), str(card.get("category") or ""),
        )).casefold()]
    if filter_name == "selected":
        cards = [card for card in cards if (
            "通过" in str(card.get("result") or "")
            and not any(word in str(card.get("result") or "") for word in ("跳过", "不匹配", "拦截"))
        )]
    elif filter_name == "archived":
        cards = [card for card in cards if card.get("archived")]
    elif filter_name == "skipped":
        cards = [card for card in cards if "跳过" in str(card.get("result") or "") or "不匹配" in str(card.get("result") or "")]
    elif filter_name == "matched":
        cards = [card for card in cards if card.get("interest_reason") and not any(word in str(card.get("result") or "") for word in ("跳过", "不匹配", "拦截"))]
    elif filter_name == "candidate":
        cards = [card for card in cards if "候选" in str(card.get("source") or "") or "筛选" in str(card.get("source") or "")]
    elif filter_name == "interaction":
        cards = [card for card in cards if card.get("actions") and any(action != "已浏览" for action in card.get("actions", []))]
    return jsonify(dict(
        ok=True,
        total=len(cards),
        offset=offset,
        limit=limit,
        items=cards[offset:offset + limit],
        counts={
            "all": len(all_cards),
            "selected": sum(1 for card in all_cards if "通过" in str(card.get("result") or "") and not any(word in str(card.get("result") or "") for word in ("跳过", "不匹配", "拦截"))),
            "archived": sum(1 for card in all_cards if card.get("archived")),
            "skipped": sum(1 for card in all_cards if "跳过" in str(card.get("result") or "") or "不匹配" in str(card.get("result") or "")),
            "matched": sum(1 for card in all_cards if card.get("interest_reason") and not any(word in str(card.get("result") or "") for word in ("跳过", "不匹配", "拦截"))),
            "candidate": sum(1 for card in all_cards if "候选" in str(card.get("source") or "") or "筛选" in str(card.get("source") or "")),
            "interaction": sum(1 for card in all_cards if card.get("actions") and any(action != "已浏览" for action in card.get("actions", []))),
        },
    ))



@app.route('/api/watch-history/remove', methods=['POST'])
def api_watch_history_remove():
    """Remove one locally stored viewing-memory record without touching Bilibili."""
    body = request.get_json(silent=True) or {}
    if body.get('confirmed') is not True:
        return jsonify(ok=False, message='请先确认删除本地视频记忆'), 400
    bvid = _safe_watch_bvid(body.get('bvid'))
    if not bvid:
        return jsonify(ok=False, message='无效的视频 BV 号'), 400
    path = Path(DATA_DIR) / 'history_videos.json'
    source = read_json(path, {})
    entries = source.get('videos', []) if isinstance(source, dict) else []
    kept = [item for item in entries if not isinstance(item, dict) or _safe_watch_bvid(item.get('bvid')) != bvid]
    removed = len(entries) - len(kept)
    if not removed:
        return jsonify(ok=False, message='本地视频记忆不存在'), 404
    source['videos'] = kept
    write_json(path, source)
    metadata_path = _watch_history_metadata_path()
    metadata = read_json(metadata_path, {})
    if isinstance(metadata, dict) and bvid in metadata:
        metadata.pop(bvid, None)
        write_json(metadata_path, metadata)
    log_line(f'[HISTORY] 已删除本地视频记忆: {bvid} ({removed} 条记录)')
    return jsonify(ok=True, removed=removed, message='已删除本地视频记忆')


@app.route('/api/watch-history/enrich', methods=['POST'])
def api_watch_history_enrich():
    """Cache public cover/duration metadata for visible cards on explicit request."""
    body = request.get_json(silent=True) or {}
    requested = body.get("bvids", [])
    if not isinstance(requested, list):
        requested = []
    bvids = []
    for value in requested:
        bvid = _safe_watch_bvid(value)
        if bvid and bvid not in bvids:
            bvids.append(bvid)
        if len(bvids) >= 12:
            break
    if not bvids:
        return jsonify(ok=False, message="没有可补全的视频记录"), 400

    cache = read_json(_watch_history_metadata_path(), {})
    cache = cache if isinstance(cache, dict) else {}
    fetched = 0
    failed = 0
    with ThreadPoolExecutor(max_workers=3, thread_name_prefix="history-meta") as pool:
        futures = {pool.submit(_fetch_watch_history_metadata, bvid): bvid for bvid in bvids}
        for future in as_completed(futures):
            bvid = futures[future]
            try:
                detail = future.result()
            except Exception:
                detail = {}
            if detail:
                cache[bvid] = detail
                fetched += 1
            else:
                failed += 1
    if fetched:
        write_json(_watch_history_metadata_path(), cache)
    log_line(f"[HISTORY] 补全观看历史资料: 成功 {fetched} 条，失败 {failed} 条")
    return jsonify(ok=True, fetched=fetched, failed=failed, items=_watch_history_cards())


def _activity_from_runtime_logs(lines: list[str]) -> dict:
    """Best-effort status for bots started before the activity-state upgrade."""
    text = "\n".join(lines[-12:])
    checks = (
        ("短暂休息", "短暂休息中", "正在等待下一轮处理"),
        ("启动冷却", "启动冷却中", "正在等待进入主循环"),
        ("正在刷新推荐流", "刷新推荐流", "正在获取下一批候选视频"),
        ("正在检查是否有新私信", "检查私信", "正在检查私信消息"),
        ("正在检查评论区", "检查评论", "正在检查评论互动"),
        ("正在读取弹幕", "读取弹幕", "正在读取视频上下文"),
        ("开始研究视频内容", "读取字幕", "正在读取字幕内容"),
        ("信息整合", "AI 判断中", "正在整合视频信息"),
    )
    for needle, label, detail in checks:
        if needle in text:
            return {"label": label, "detail": detail, "inferred": True}
    return {"label": "等待下一步", "detail": "机器人运行中，等待下一条真实工作日志", "inferred": True}


def _video_observation_payload() -> dict:
    """Combine the bot's explicit current-video state with local cached metadata."""
    runtime = read_json(Path(DATA_DIR) / "bot_runtime_state.json", {})
    runtime = runtime if isinstance(runtime, dict) else {}
    observation = runtime.get("video_observation", {})
    observation = dict(observation) if isinstance(observation, dict) else {}
    bvid = _safe_watch_bvid(observation.get("bvid"))
    card = next((item for item in _watch_history_cards() if item.get("bvid") == bvid), {}) if bvid else {}
    metadata = read_json(_watch_history_metadata_path(), {})
    detail = metadata.get(bvid, {}) if isinstance(metadata, dict) and isinstance(metadata.get(bvid), dict) else {}
    if bvid:
        observation["bvid"] = bvid
    observation["title"] = str(observation.get("title") or card.get("title") or bvid or "")
    observation["up"] = str(observation.get("up") or card.get("up") or "")
    observation["cover"] = str(observation.get("cover") or card.get("cover") or detail.get("pic") or "")
    raw_duration = observation.get("duration") or detail.get("duration") or 0
    observation["duration"] = _watch_history_duration_label(raw_duration)
    observation["category"] = str(observation.get("category") or card.get("category") or detail.get("category") or "")
    observation["description"] = str(observation.get("description") or detail.get("description") or "")[:500]
    observation["url"] = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
    for key in ("view_count", "like_count", "coin_count", "favorite_count"):
        observation[key] = int(observation.get(key) or detail.get(key) or card.get(key) or 0)
    observation["score"] = observation.get("score", card.get("score", 0))
    recent_cards = _watch_history_cards()
    observation["recent"] = [item for item in recent_cards if item.get("bvid") != bvid][:8]
    observation["running"] = _refresh_bot_state()
    logs = _read_runtime_log(BOT_RUNTIME_LOG_FILE, bot_output_lines, limit=140)
    observation["logs"] = logs[-32:]
    activity = runtime.get("activity", {})
    if not observation["running"]:
        observation["activity"] = {"label": "机器人已停止", "detail": "正在展示最后一次处理的视频和日志", "inferred": False}
    else:
        observation["activity"] = dict(activity) if isinstance(activity, dict) and activity.get("label") else _activity_from_runtime_logs(logs)
    return observation


@app.route('/api/observe')
def api_video_observe():
    config = read_json(CONFIG_FILE, {})
    ui = config.get("ui") if isinstance(config.get("ui"), dict) else {}
    return jsonify(ok=True, observation=_video_observation_payload(),
                   user_awareness=bool(ui.get("observation_user_awareness", False)))


@app.route('/api/observe/settings', methods=['POST'])
def api_video_observe_settings():
    body = request.get_json(silent=True) or {}
    config = read_json(CONFIG_FILE, {})
    config.setdefault("ui", {})["observation_user_awareness"] = body.get("user_awareness") is True
    write_json(CONFIG_FILE, config)
    return jsonify(ok=True, user_awareness=config["ui"]["observation_user_awareness"])


@app.route('/api/observe/force-judge', methods=['POST'])
def api_video_observe_force_judge():
    """Run a manual, non-persistent AI opinion for the current target only."""
    observation = _video_observation_payload()
    if not observation.get("bvid"):
        return jsonify(ok=False, message="机器人当前没有可判断的视频"), 409
    config = read_json(CONFIG_FILE, {})
    awareness = bool((config.get("ui") or {}).get("observation_user_awareness", False))
    awareness_note = "用户正在观察这个视频，请把这个偏好作为弱信号。" if awareness else "这是手动请求，不代表用户偏好，不要写入长期记忆。"
    prompt = (
        "只基于以下视频基础资料给出暂时性的观看价值判断。不要执行 B 站操作、不要写入记忆或知识库，"
        "也不要假装已经看完视频。请给出 0-10 分、理由和需要继续核实的信息。\n\n"
        f"{awareness_note}\n"
        f"标题: {observation.get('title', '')}\nUP主: {observation.get('up', '')}\n"
        f"分区: {observation.get('category', '')}\n简介: {observation.get('description', '')}\n"
        f"播放: {observation.get('view_count', 0)} 点赞: {observation.get('like_count', 0)}"
    )
    try:
        from services._services_ai import call_ai
        answer = _run_coro(call_ai([
            {"role": "system", "content": "你是谨慎的视频评估助手，回答简洁且不编造观看事实。"},
            {"role": "user", "content": prompt},
        ], temperature=0.2, max_tokens=500, verbose=False)).strip()
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 502
    if not answer:
        return jsonify(ok=False, message="AI 没有返回可用判断"), 502
    log_line(f"[OBSERVE] 已完成手动判断: {observation.get('bvid')}")
    return jsonify(ok=True, answer=answer, bvid=observation["bvid"], user_awareness=awareness)


@app.route('/api/video/timeline')
def api_video_timeline():
    """Expose timestamped CC cues without pretending ASR text has exact timings."""
    bvid = _safe_watch_bvid(request.args.get("bvid"))
    if not bvid:
        return jsonify(ok=False, message="请输入有效 BV 号"), 400
    refresh = str(request.args.get("refresh") or "") in {"1", "true"}
    try:
        timeline = _load_timeline_for_web(bvid, refresh=refresh)
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 502
    segments = timeline.get("segments") if isinstance(timeline, dict) else []
    if not isinstance(segments, list) or not segments:
        return jsonify(ok=False, message="该视频没有可用于时间定位的 CC 字幕"), 404
    return jsonify(ok=True, bvid=bvid, track=timeline.get("track", ""),
                   updated_at=timeline.get("updated_at", ""), segments=segments[:5000],
                   total=len(segments))


@app.route('/api/video/timeline/backfill', methods=['GET', 'POST'])
def api_video_timeline_backfill():
    """Inspect or safely resume the idle-only legacy CC timeline backfill."""
    if request.method == 'POST':
        body = request.get_json(silent=True) or {}
        try:
            limit = int(body.get("limit", 20))
        except (TypeError, ValueError):
            limit = 20
        if _refresh_bot_state():
            return jsonify(
                ok=False,
                message="机器人运行中，已暂停时间轴回填以避免触发频率限制",
                **_timeline_backfill_snapshot(),
            ), 409
        if not _start_scored_timeline_backfill(limit):
            return jsonify(ok=False, message="时间轴回填正在进行", **_timeline_backfill_snapshot()), 409
        return jsonify(
            ok=True,
            message="已开始低频回填历史评分视频的 CC 时间轴",
            **_timeline_backfill_snapshot(),
        )
    return jsonify(ok=True, **_timeline_backfill_snapshot())


@app.route('/api/video/timeline/answer', methods=['POST'])
def api_video_timeline_answer():
    body = request.get_json(silent=True) or {}
    bvid = _safe_watch_bvid(body.get("bvid"))
    question = str(body.get("question") or "").strip()[:800]
    if not bvid or not question:
        return jsonify(ok=False, message="需要 BV 号和问题"), 400
    try:
        timeline = _load_timeline_for_web(bvid)
        segments = timeline.get("segments") if isinstance(timeline, dict) else []
        if not isinstance(segments, list) or not segments:
            return jsonify(ok=False, message="该视频没有可用于时间定位的 CC 字幕"), 404
        evidence = _timeline_question_segments(segments, question)
        evidence_text = "\n".join(
            f"[{item.get('start_label', '00:00')} - {item.get('end_label', '00:00')}] {item.get('text', '')}"
            for item in evidence
        )
        from services._services_ai import call_ai
        prompt = (
            "你是视频字幕时间轴助手。只基于给出的带时间字幕回答问题，不能编造。"
            "先直接回答，再列出支持该结论的时间范围；时间必须采用“MM:SS - MM:SS”。"
            "若证据不足，明确说明。\n\n"
            f"问题：{question}\n\n字幕证据：\n{evidence_text}"
        )
        answer = _run_coro(call_ai([
            {"role": "system", "content": "回答简洁、准确，并保留字幕时间范围。"},
            {"role": "user", "content": prompt},
        ], temperature=0.2, max_tokens=900, verbose=False)).strip()
        if not answer:
            first = evidence[0]
            answer = (f"最相关的字幕位置是 {first.get('start_label')} - {first.get('end_label')}："
                      f"{first.get('text', '')}")
        return jsonify(ok=True, answer=answer, evidence=evidence,
                       total=len(segments), track=timeline.get("track", ""))
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 502


_DEFAULT_SCORE_COLORS = {
    "green": "#16a34a", "blue": "#2563eb", "yellow": "#a16207",
    "orange": "#ea580c", "red": "#dc2626",
}


@app.route('/api/display/score-colors', methods=['GET', 'POST'])
def api_display_score_colors():
    cfg = read_json(CONFIG_FILE, {})
    ui = cfg.get("ui") if isinstance(cfg.get("ui"), dict) else {}
    colors = dict(_DEFAULT_SCORE_COLORS)
    colors.update({key: str(value) for key, value in (ui.get("score_colors") or {}).items()
                   if key in colors and re.fullmatch(r"#[0-9a-fA-F]{6}", str(value or ""))})
    if request.method == "POST":
        body = request.get_json(silent=True) or {}
        incoming = body.get("colors") if isinstance(body.get("colors"), dict) else {}
        for key in colors:
            value = str(incoming.get(key) or "")
            if value and re.fullmatch(r"#[0-9a-fA-F]{6}", value):
                colors[key] = value
        cfg.setdefault("ui", {})["score_colors"] = colors
        write_json(CONFIG_FILE, cfg)
        log_line("[UI] 已保存评分颜色设置")
    return jsonify(ok=True, colors=colors)


@app.route('/api/watch-history/remove-unmatched', methods=['POST'])
def api_watch_history_remove_unmatched():
    """Remove only local records that were explicitly rejected by interest filtering."""
    body = request.get_json(silent=True) or {}
    if body.get("confirmed") is not True:
        return jsonify(ok=False, message="请先确认清理本地不匹配记录"), 400
    path = Path(DATA_DIR) / "history_videos.json"
    source = read_json(path, {})
    entries = source.get("videos", []) if isinstance(source, dict) else []
    kept, removed = [], 0
    for entry in entries if isinstance(entries, list) else []:
        result = str(entry.get("result") or "") if isinstance(entry, dict) else ""
        if any(word in result for word in ("兴趣不匹配", "已跳过", "避雷策略拦截")):
            removed += 1
            continue
        kept.append(entry)
    source["videos"] = kept
    write_json(path, source)
    log_line(f"[HISTORY] 已清理本地不匹配记录: {removed} 条")
    return jsonify(ok=True, removed=removed, message=f"已清理 {removed} 条本地不匹配记录")


def _favorite_payload() -> dict:
    library = _read_favorite_library()
    card_map = {card["bvid"]: card for card in _watch_history_cards() if card.get("bvid")}
    metadata = read_json(_watch_history_metadata_path(), {})
    metadata = metadata if isinstance(metadata, dict) else {}
    folders = []
    for folder in library["folders"]:
        folder_id = str(folder.get("id") or "")
        items = []
        for item in library["items"]:
            if str(item.get("folder_id") or "") != folder_id:
                continue
            bvid = _safe_watch_bvid(item.get("bvid"))
            if not bvid:
                continue
            detail = metadata.get(bvid, {}) if isinstance(metadata.get(bvid), dict) else {}
            card = dict(card_map.get(bvid) or {
                "bvid": bvid,
                "title": str(detail.get("title") or item.get("title") or bvid),
                "up": str(detail.get("up") or item.get("up") or "未知 UP"),
                "cover": str(detail.get("pic") or item.get("cover") or ""),
                "duration": _watch_history_duration_label(detail.get("duration") or item.get("duration")),
                "category": str(detail.get("category") or item.get("category") or ""),
                "view_count": detail.get("view_count"),
                "like_count": detail.get("like_count"),
                "coin_count": detail.get("coin_count"),
                "favorite_count": detail.get("favorite_count"),
                "url": f"https://www.bilibili.com/video/{bvid}",
            })
            if item.get("score") not in (None, ""):
                card["score"] = item.get("score")
            if item.get("interest_reason"):
                card["interest_reason"] = str(item.get("interest_reason"))
            # A processed history item can have its own fields but still needs the
            # cached public counters and cover shown on a local favorite card.
            for source_key, target_key in (("pic", "cover"), ("duration", "duration"), ("category", "category"),
                                           ("view_count", "view_count"), ("like_count", "like_count"),
                                           ("coin_count", "coin_count"), ("favorite_count", "favorite_count")):
                if detail.get(source_key) not in (None, ""):
                    card[target_key] = detail[source_key] if target_key != "duration" else _watch_history_duration_label(detail[source_key])
            if detail.get("title"):
                card["title"] = str(detail["title"])
            if detail.get("up"):
                card["up"] = str(detail["up"])
            card["favorite_added_at"] = _watch_history_time(item.get("added_at"))
            card["favorite_source"] = str(item.get("source") or "用户管理")
            items.append(card)
        folders.append({**folder, "items": sorted(items, key=lambda card: card.get("favorite_added_at", ""), reverse=True), "count": len(items)})
    return {"folders": folders, "available_count": len(card_map)}


@app.route('/api/favorites')
def api_favorites():
    library = _read_favorite_library()
    if not library["items"]:
        from services.local_favorites import backfill_from_history
        backfill_from_history(
            read_json(CONFIG_FILE, {}),
            read_json(Path(DATA_DIR) / "history_videos.json", {}),
            data_dir=DATA_DIR,
        )
    # The card view asks explicitly to hydrate missing public metadata.  This is
    # bounded and cached so opening a folder never produces placeholder zeroes.
    if request.args.get("enrich") in {"1", "true"}:
        library = _read_favorite_library()
        _cache_watch_history_metadata([item.get("bvid") for item in library["items"]], maximum=8)
    return jsonify(ok=True, **_favorite_payload())


@app.route('/api/favorites/folders', methods=['POST'])
def api_favorite_folder_create():
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()
    if not name:
        return jsonify(ok=False, message="收藏夹名称不能为空"), 400
    library = _read_favorite_library()
    if any(str(folder.get("name") or "").casefold() == name.casefold() for folder in library["folders"]):
        return jsonify(ok=False, message="已有同名收藏夹"), 409
    folder = _new_favorite_folder(name)
    library["folders"].append(folder)
    _write_favorite_library(library)
    return jsonify(ok=True, folder=folder, message=f"已创建收藏夹“{folder['name']}”")


@app.route('/api/favorites/folders/<folder_id>', methods=['PUT', 'DELETE'])
def api_favorite_folder_update(folder_id):
    library = _read_favorite_library()
    folder = next((item for item in library["folders"] if str(item.get("id")) == folder_id), None)
    if not folder:
        return jsonify(ok=False, message="收藏夹不存在"), 404
    if request.method == 'DELETE':
        library["folders"] = [item for item in library["folders"] if str(item.get("id")) != folder_id]
        library["items"] = [item for item in library["items"] if str(item.get("folder_id")) != folder_id]
        _write_favorite_library(library)
        return jsonify(ok=True, message="收藏夹及其中的本地条目已删除")
    body = request.get_json(silent=True) or {}
    name = str(body.get("name") or "").strip()[:60]
    if not name:
        return jsonify(ok=False, message="收藏夹名称不能为空"), 400
    folder["name"] = name
    _write_favorite_library(library)
    return jsonify(ok=True, folder=folder, message="收藏夹已重命名")


@app.route('/api/favorites/items', methods=['POST', 'DELETE'])
def api_favorite_items():
    body = request.get_json(silent=True) or {}
    folder_id = str(body.get("folder_id") or "")
    bvid = _safe_watch_bvid(body.get("bvid"))
    library = _read_favorite_library()
    if not any(str(folder.get("id")) == folder_id for folder in library["folders"]):
        return jsonify(ok=False, message="请选择有效收藏夹"), 400
    if not bvid:
        return jsonify(ok=False, message="缺少有效 BV 号"), 400
    if request.method == 'DELETE':
        before = len(library["items"])
        library["items"] = [item for item in library["items"] if not (str(item.get("folder_id")) == folder_id and _safe_watch_bvid(item.get("bvid")) == bvid)]
        _write_favorite_library(library)
        return jsonify(ok=True, removed=before - len(library["items"]), message="已从本地收藏夹移除")
    if not any(str(item.get("folder_id")) == folder_id and _safe_watch_bvid(item.get("bvid")) == bvid for item in library["items"]):
        library["items"].append({"folder_id": folder_id, "bvid": bvid, "added_at": datetime.now().isoformat(timespec="seconds"), "source": str(body.get("source") or "用户管理")[:40]})
        _write_favorite_library(library)
    fetched, failed = _cache_watch_history_metadata([bvid], maximum=1)
    return jsonify(ok=True, fetched=fetched, failed=failed, message="已加入本地收藏夹", **_favorite_payload())


@app.route('/api/favorites/import-history', methods=['POST'])
def api_favorite_import_history():
    body = request.get_json(silent=True) or {}
    folder_id = str(body.get("folder_id") or "")
    library = _read_favorite_library()
    if not any(str(folder.get("id")) == folder_id for folder in library["folders"]):
        return jsonify(ok=False, message="请选择有效收藏夹"), 400
    existing = {(str(item.get("folder_id")), _safe_watch_bvid(item.get("bvid"))) for item in library["items"]}
    added = 0
    for card in _watch_history_cards():
        rejected = any(word in str(card.get("result") or "") for word in ("跳过", "不匹配", "拦截"))
        if rejected or not card.get("interest_reason"):
            continue
        key = (folder_id, card["bvid"])
        if key in existing:
            continue
        library["items"].append({"folder_id": folder_id, "bvid": card["bvid"], "added_at": datetime.now().isoformat(timespec="seconds"), "source": "AI 兴趣匹配"})
        existing.add(key)
        added += 1
    _write_favorite_library(library)
    fetched, failed = _cache_watch_history_metadata([item.get("bvid") for item in library["items"] if str(item.get("folder_id")) == folder_id], maximum=8)
    return jsonify(ok=True, added=added, fetched=fetched, failed=failed, message=f"已加入 {added} 条兴趣匹配的视频", **_favorite_payload())


# ── 日记进化 ──
@app.route('/api/diary')
def api_diary():
    return jsonify(dict(
        diary=_web_diary_payload(read_json(DATA_DIR / "bot_diary.json", {})),
        evolution=_web_evolution_payload(read_json(DATA_DIR / "self_evolution.json", {})),
    ))


@app.route('/api/diary/entry', methods=['POST'])
def api_diary_entry():
    """Save a user-authored diary entry to the same shared data file as the bot."""
    try:
        body = request.get_json(force=True) or {}
        title = str(body.get('title') or '手动日记').strip()[:120]
        content = str(body.get('content') or '').strip()
        if not content:
            return jsonify(dict(ok=False, message='请先填写日记内容')), 400
        from persona.managers import BotDiaryManager, MoodManager
        entry = BotDiaryManager().add_entry(
            title, content, mood=MoodManager().get_current(),
            tags=['手动'], source='web_manual', entry_type='manual')
        return jsonify(dict(ok=True, entry=entry, message='日记已保存'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500


def _diary_entry_index(entries, entry_id: str):
    """Locate an entry by persisted id, including read-only legacy ids."""
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            continue
        actual_id = str(entry.get('id') or '')
        legacy_id = f"legacy-{index}-{entry.get('time', '')}"
        if entry_id in (actual_id, legacy_id):
            return index
    return None


@app.route('/api/diary/entry/<entry_id>', methods=['PUT'])
def api_diary_entry_update(entry_id):
    """Edit an existing local diary entry. This never triggers a Bilibili action."""
    try:
        body = request.get_json(force=True) or {}
        content = str(body.get('content') or '').strip()
        if not content:
            return jsonify(ok=False, message='日记内容不能为空'), 400
        data = read_json(DATA_DIR / 'bot_diary.json', {'entries': []})
        entries = data.get('entries') if isinstance(data, dict) else []
        if not isinstance(entries, list):
            entries = data.get('diaries', []) if isinstance(data, dict) else []
            data = {'entries': entries}
        index = _diary_entry_index(entries, str(entry_id))
        if index is None:
            return jsonify(ok=False, message='未找到该日记'), 404
        item = dict(entries[index])
        item['id'] = item.get('id') or f"diary-{int(time.time() * 1000)}-{index + 1}"
        item['title'] = str(body.get('title') or item.get('title') or '日记记录').strip()[:120]
        item['content'] = content
        item['updated_at'] = datetime.now().isoformat(timespec='seconds')
        entries[index] = item
        data['entries'] = entries
        data.pop('diaries', None)
        write_json(DATA_DIR / 'bot_diary.json', data)
        log_line(f"[DIARY] 已编辑日记: {item['id']}")
        return jsonify(ok=True, entry=item, message='日记已更新')
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400


@app.route('/api/diary/entry/<entry_id>', methods=['DELETE'])
def api_diary_entry_delete(entry_id):
    """Delete one explicitly selected diary entry after the browser confirmation."""
    try:
        data = read_json(DATA_DIR / 'bot_diary.json', {'entries': []})
        entries = data.get('entries') if isinstance(data, dict) else []
        if not isinstance(entries, list):
            entries = data.get('diaries', []) if isinstance(data, dict) else []
            data = {'entries': entries}
        index = _diary_entry_index(entries, str(entry_id))
        if index is None:
            return jsonify(ok=False, message='未找到该日记'), 404
        removed = entries.pop(index)
        data['entries'] = entries
        data.pop('diaries', None)
        write_json(DATA_DIR / 'bot_diary.json', data)
        log_line(f"[DIARY] 已删除日记: {removed.get('id', entry_id)}")
        return jsonify(ok=True, message='日记已删除')
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400

# ── 操作日志 ──
@app.route('/api/actions')
def api_actions():
    limit = request.args.get('limit', 50, type=int)
    data = read_json(DATA_DIR / "web_action_log.json", dict(items=[]))
    items = data.get('items', [])
    result = []
    for it in items[-limit:]:
        if isinstance(it, dict):
            result.append(dict(
                time=it.get('created_at', it.get('time', '')),
                action=it.get('action', ''),
                payload=it.get('payload', {}),
                executed=it.get('executed', False),
            ))
    return jsonify(dict(items=result))

# ── 图表数据 ──
@app.route('/api/charts')
def api_charts():
    """为仪表盘折线图提供历史统计数据"""
    days = request.args.get('days', 14, type=int)
    # 从 diary 数据提取心情/精力趋势
    diary = read_json(DATA_DIR / "bot_diary.json", dict(entries=[]))
    entries = diary.get('entries', [])
    mood_data = []
    for e in entries[-days*5:]:  # 每天可能有多个条目
        t = e.get('time', '')
        date = t[:10] if len(t) >= 10 else t  # YYYY-MM-DD
        mood_data.append(dict(
            date=date,
            valence=e.get('mood_score', e.get('valence', 50)),
            energy=int(e.get('energy', 50)),
        ))
    # 按天聚合
    daily_moods = {}
    for m in mood_data:
        d = m['date']
        if d not in daily_moods:
            daily_moods[d] = {'vals': [], 'engs': []}
        daily_moods[d]['vals'].append(m['valence'])
        daily_moods[d]['engs'].append(m['energy'])
    mood_result = []
    for d in sorted(daily_moods.keys())[-days:]:
        v = daily_moods[d]
        mood_result.append(dict(
            date=d[5:] if len(d)==10 else d,
            valence=round(sum(v['vals'])/len(v['vals']), 1),
            energy=round(sum(v['engs'])/len(v['engs']), 1),
        ))

    # 从评论日志提取评论趋势
    cmt_log = read_json(DATA_DIR / "comment_log.json", dict(items=[]))
    daily_cmts = {}
    for c in cmt_log.get('items', []):
        t = c.get('time', c.get('created_at', ''))
        date = t[:10] if len(t) >= 10 else t
        daily_cmts[date] = daily_cmts.get(date, 0) + 1
    cmt_result = [dict(date=d[5:] if len(d)==10 else d, count=c) for d, c in sorted(daily_cmts.items())[-days:]]

    # 从操作日志提取操作趋势
    act_log = read_json(DATA_DIR / "web_action_log.json", dict(items=[]))
    daily_acts = {}
    for a in act_log.get('items', []):
        t = a.get('created_at', a.get('time', ''))
        date = t[:10] if len(t) >= 10 else t
        daily_acts[date] = daily_acts.get(date, 0) + 1
    act_result = [dict(date=d[5:] if len(d)==10 else d, count=c) for d, c in sorted(daily_acts.items())[-days:]]

    # 视频处理来自 evolution 事件
    evo = read_json(DATA_DIR / "self_evolution.json", dict(events=[]))
    daily_vids = {}
    for ev in evo.get('events', []):
        t = ev.get('time', '')
        date = t[:10] if len(t) >= 10 else t
        detail = str(ev.get('detail', ''))
        if '视频' in detail or '观看' in detail or 'video' in detail.lower():
            daily_vids[date] = daily_vids.get(date, 0) + 1
    vid_result = [dict(date=d[5:] if len(d)==10 else d, count=c) for d, c in sorted(daily_vids.items())[-days:]]

    return jsonify(dict(
        comments=cmt_result,
        moods=mood_result if mood_result else [],
        actions=act_result,
        videos=vid_result,
    ))

# ── 心情管理 ──
@app.route('/api/mood/status')
def api_mood_status():
    mood = read_json(DATA_DIR / "mood_state.json", {})
    config = read_json(CONFIG_FILE, {})
    mc = config.get('mood', {})
    return jsonify(dict(
        current_mood=mood.get('mood', mc.get('default_mood', '平静')),
        energy=mood.get('energy', 100),
        random_enabled=mc.get('random_enabled', False),
        random_interval=mc.get('random_interval_minutes', 5),
        custom_enabled=mc.get('custom_enabled', False),
        custom_mood=mc.get('custom_mood', ''),
        default_mood=mc.get('default_mood', '平静'),
    ))

@app.route('/api/mood/set', methods=['POST'])
def api_mood_set():
    try:
        body = request.get_json(force=True)
        config = read_json(CONFIG_FILE, {})
        mc = config.setdefault('mood', {})
        if 'random_enabled' in body: mc['random_enabled'] = bool(body['random_enabled'])
        if 'random_interval_minutes' in body: mc['random_interval_minutes'] = int(body['random_interval_minutes'])
        if 'custom_enabled' in body: mc['custom_enabled'] = bool(body['custom_enabled'])
        if 'custom_mood' in body: mc['custom_mood'] = str(body['custom_mood'])
        if 'default_mood' in body: mc['default_mood'] = str(body['default_mood'])
        write_json(CONFIG_FILE, config)
        # 同时更新当前心情
        mood = read_json(DATA_DIR / "mood_state.json", {})
        if 'current_mood' in body:
            mood['mood'] = str(body['current_mood'])
            mood['updated_at'] = datetime.now().isoformat()
            write_json(DATA_DIR / "mood_state.json", mood)
        log_line(f"心情设置已更新")
        return jsonify(dict(ok=True, message='心情设置已更新'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

# ── 导出/导入配置 ──
BACKUP_DIR_EXPORT = get_backup_dir()
BACKUP_GROUPS = {
    'settings': ('设置（已脱敏）', '机器人和网页设置，不包含 API Key、Cookie 或密码', True),
    'memory': ('记忆与互动记录', '观看历史、评论、私信上下文、人格和心情记录', True),
    'knowledge': ('知识库与收藏归档', 'KnowledgeBase、highlights 与自定义知识', True),
    'exports': ('已生成产物', 'HTML、思维导图、Word、二维码等导出文件', True),
}

def _backup_size(paths):
    total = 0
    for path in paths:
        try:
            if path.is_file(): total += path.stat().st_size
            elif path.is_dir(): total += sum(item.stat().st_size for item in path.rglob('*') if item.is_file())
        except OSError: pass
    return total

def _backup_sources(group_id):
    data_files = [p for p in Path(DATA_DIR).glob('*.json') if p.name not in {'config.json', 'bilibili_cookies.json'}]
    if group_id == 'settings': return [Path(CONFIG_FILE)]
    if group_id == 'memory': return data_files + [Path(USER_DATA_DIR) / 'bot_memory.json', Path(USER_DATA_DIR) / 'knowledge_metadata.json']
    if group_id == 'knowledge': return [Path(KNOWLEDGE_BASE_DIR), Path(HIGHLIGHTS_DIR)]
    if group_id == 'exports': return [Path(HTML_EXPORTS_DIR), Path(MINDMAPS_DIR), Path(WORD_DIR), Path(QR_CODES_DIR)]
    return []

@app.route('/api/backup/options')
def api_backup_options():
    groups = []
    for group_id, (label, description, default) in BACKUP_GROUPS.items():
        size = _backup_size(_backup_sources(group_id))
        groups.append(dict(id=group_id, label=label, description=description, default=default,
                           size=f'{size / 1048576:.2f} MB' if size >= 1048576 else f'{size / 1024:.1f} KB'))
    return jsonify(ok=True, groups=groups)

@app.route('/api/export', methods=['POST'])
def api_export():
    try:
        BACKUP_DIR_EXPORT.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        body = request.get_json(silent=True) or {}
        # sanitize=True(默认): 脱敏导出，可安全分享；sanitize=False: 完整导出（含 API Key/Cookie），仅限自己迁移
        sanitize = body.get('sanitize', True)
        selected = body.get('groups') or list(BACKUP_GROUPS)
        selected = [str(item) for item in selected if str(item) in BACKUP_GROUPS]
        if not selected:
            return jsonify(ok=False, message='请至少选择一项备份内容'), 400
        if selected != ['settings']:
            import zipfile
            out = BACKUP_DIR_EXPORT / f"bilibili_learning_bot_backup_{ts}.zip"
            manifest = {'version': APP_VERSION, 'created_at': datetime.now().isoformat(), 'groups': selected,
                        'privacy': 'settings is sanitized; credentials are never included'}
            with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
                for group_id in selected:
                    for source in _backup_sources(group_id):
                        if not source.exists(): continue
                        if group_id == 'settings':
                            settings_data = read_json(source, {})
                            if sanitize:
                                settings_data = sanitize_config_for_export(settings_data)
                            archive.writestr('settings/config.json', json.dumps(settings_data, ensure_ascii=False, indent=2))
                        elif source.is_file(): archive.write(source, f'{group_id}/{source.name}')
                        else:
                            for child in source.rglob('*'):
                                if child.is_file() and not child.is_symlink(): archive.write(child, f'{group_id}/{source.name}/{child.relative_to(source)}')
            log_line(f"已创建可选备份: {out.name} ({', '.join(selected)})")
            return jsonify(ok=True, message=f'已创建备份：{out.name}', path=str(out), groups=selected)
        # A settings-only export must remain exactly that.  Interaction logs,
        # memories and generated files are available through their own groups.
        # settings 导出包含 config.json 与登录 Cookie（登录态迁移必需）
        export_data = {'config.json': read_json(CONFIG_FILE, {})}
        cookie_path = DATA_DIR / 'bilibili_cookies.json'
        if cookie_path.exists():
            export_data['bilibili_cookies.json'] = read_json(cookie_path, {})

        # 完整导出（自己迁移）与脱敏导出（安全分享）用不同文件名区分
        suffix = "" if sanitize else "_full"
        out = BACKUP_DIR_EXPORT / f"bilibili_learning_bot_export{suffix}_{ts}.json"
        if sanitize:
            # 🔒 脱敏导出：API Key / Cookie 替换为占位符，可安全分享
            if 'config.json' in export_data:
                export_data['config.json'] = sanitize_config_for_export(export_data['config.json'])
            if 'bilibili_cookies.json' in export_data:
                export_data['bilibili_cookies.json'] = sanitize_config_for_export(export_data['bilibili_cookies.json'])
        out.write_text(json.dumps(export_data, ensure_ascii=False, indent=2), encoding='utf-8')
        note = "（含敏感信息，请勿外传）" if not sanitize else "（已脱敏，可安全分享）"
        log_line(f"配置已导出: {out} {note}")
        return jsonify(dict(ok=True, message=f'配置已导出到 {out}{note}', path=str(out), sanitize=sanitize))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/import', methods=['GET'])
def api_import():
    try:
        files = []
        if BACKUP_DIR_EXPORT.exists():
            files = sorted([f for f in BACKUP_DIR_EXPORT.iterdir() if f.suffix in ('.json', '.zip')], key=lambda x: x.stat().st_mtime, reverse=True)
        # 返回可用备份列表
        flist = [dict(name=f.name, mtime=datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M:%S'),
                      size=f"{f.stat().st_size/1024:.1f}K") for f in files[:20]]
        return jsonify(dict(files=flist))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500


def _apply_zip_backup(zip_path):
    """从完整备份 zip 恢复各分组文件到对应目录。

    zip 内布局: manifest.json + {group_id}/{source.name}/... ，
    与 _backup_sources() 一一对应；settings 里的脱敏占位符会被过滤（保留现有值）。
    """
    import zipfile
    applied = []
    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())
        manifest = json.loads(zf.read('manifest.json').decode('utf-8'))
        groups = manifest.get('groups') or list(BACKUP_GROUPS)
        for group_id in groups:
            for source in _backup_sources(group_id):
                prefix = f'{group_id}/{source.name}'
                if source.is_file() or not any(n.startswith(prefix + '/') for n in names):
                    if prefix not in names:
                        continue
                    data = zf.read(prefix)
                    if group_id == 'settings':
                        existing = read_json(CONFIG_FILE, None)
                        val = json.loads(data.decode('utf-8'))
                        val = strip_hidden_placeholders(val, existing)
                        write_json(CONFIG_FILE, val)
                    else:
                        source.parent.mkdir(parents=True, exist_ok=True)
                        source.write_bytes(data)
                    applied.append(prefix)
                else:
                    for n in names:
                        if n.startswith(prefix + '/') and not n.endswith('/'):
                            rel = n[len(prefix) + 1:]
                            target = source / rel
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(zf.read(n))
                            applied.append(n)
    return applied

@app.route('/api/import/apply', methods=['POST'])
def api_import_apply():
    try:
        body = request.get_json(force=True, silent=True) or {}
        fname = body.get('filename', '')
        if not fname:
            return jsonify(dict(ok=False, message='未指定文件名')), 400
        # 🔒 路径穿越防护：校验 filename 不包含 ../ 且在备份目录下
        if not is_safe_path(fname, BACKUP_DIR_EXPORT):
            log_line(f"⛔ 拒绝路径穿越尝试: {fname}")
            return jsonify(dict(ok=False, message='文件名包含非法路径')), 403
        fpath = BACKUP_DIR_EXPORT / fname
        if not fpath.exists():
            return jsonify(dict(ok=False, message='备份文件不存在')), 404
        if fpath.suffix == '.zip':
            try:
                applied = _apply_zip_backup(fpath)
            except Exception as e:
                log_line(f"恢复 zip 备份失败: {fname}: {e}")
                return jsonify(dict(ok=False, message=f'恢复失败：{e}')), 500
            log_line(f"zip 备份已恢复: {fname} ({len(applied)} 个文件)")
            return jsonify(dict(ok=True, message=f'已恢复 {len(applied)} 个文件'))
        data = json.loads(fpath.read_text(encoding='utf-8'))
        count = 0
        for key, val in data.items():
            if key == 'bot_memory.json':
                write_json(USER_DATA_DIR / key, val)
            elif key == 'knowledge_metadata.json':
                write_json(USER_DATA_DIR / key, val)
            else:
                # 防止脱敏导出文件中的 '[已隐藏]' 占位符覆盖真实配置：
                # 有现有值时保留现有值，否则删除该字段（等待用户重新填写）。
                if isinstance(val, (dict, list)):
                    existing = read_json(DATA_DIR / key, None)
                    val = strip_hidden_placeholders(val, existing)
                write_json(DATA_DIR / key, val)
            count += 1
        log_line(f"配置已导入: {fname} ({count}个文件)")
        return jsonify(dict(ok=True, message=f'已导入 {count} 个文件'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

# ── 恢复出厂设置 ──
# 🔒 服务端二次确认：需要前端先生成确认令牌
_factory_reset_pending_token = None
_FACTORY_RESET_TOKEN_TTL_SECONDS = 60

@app.route('/api/factory-reset/request', methods=['POST'])
def api_factory_reset_request():
    """请求恢复出厂设置，返回一次性确认令牌（60秒有效）。"""
    global _factory_reset_pending_token
    from core.config import CIPHER_KEY_FILE
    body = request.get_json(silent=True) or {}
    selected_groups = body.get('selected_groups') or list(DEFAULT_RESET_GROUP_IDS)
    if not isinstance(selected_groups, list) or not selected_groups:
        return jsonify(ok=False, message='请至少选择一个清理范围'), 400
    selected_groups = [str(group) for group in selected_groups]
    try:
        preview = preview_reset_targets(
            data_dir=Path(DATA_DIR), user_data_dir=Path(USER_DATA_DIR),
            project_dir=Path(BASE_DIR), backup_dir=Path(get_backup_dir()),
            cipher_key_file=Path(CIPHER_KEY_FILE), config=read_json(CONFIG_FILE, {}),
            selected_groups=selected_groups,
        )
    except ValueError as exc:
        return jsonify(ok=False, message=str(exc)), 400
    _factory_reset_pending_token = {
        'token': _uuid_module.uuid4().hex,
        'created_at': time.time(),
        'selected_groups': preview['selected_groups'],
    }
    log_line("⚠ 收到恢复出厂设置请求，等待二次确认...")
    return jsonify(dict(ok=True, token=_factory_reset_pending_token['token'], preview=preview,
                        message='请核对清理范围，并在60秒内输入确认令牌完成操作'))

@app.route('/api/factory-reset', methods=['POST'])
def api_factory_reset():
    global _factory_reset_pending_token, bot_output_lines
    try:
        body = request.get_json(silent=True) or {}
        confirm_token = body.get('confirm_token', '')
        # 🔒 必须有未过期的一次性确认令牌
        pending = _factory_reset_pending_token
        selected_groups = body.get('selected_groups') or (pending.get('selected_groups') if pending else [])
        is_valid = (
            pending
            and confirm_token == pending.get('token')
            and time.time() - pending.get('created_at', 0) <= _FACTORY_RESET_TOKEN_TTL_SECONDS
            and selected_groups == pending.get('selected_groups')
        )
        if not is_valid:
            _factory_reset_pending_token = None
            return jsonify(dict(ok=False, message='确认令牌无效或已过期，请重新请求令牌')), 403
        _factory_reset_pending_token = None
        from core.config import CIPHER_KEY_FILE
        reset_config = read_json(CONFIG_FILE, {})
        result = erase_all_user_data(
            data_dir=Path(DATA_DIR),
            user_data_dir=Path(USER_DATA_DIR),
            project_dir=Path(BASE_DIR),
            backup_dir=Path(get_backup_dir()),
            cipher_key_file=Path(CIPHER_KEY_FILE),
            config=reset_config,
            selected_groups=selected_groups,
        )
        if 'credentials_runtime' in selected_groups:
            with bot_output_lock:
                bot_output_lines.clear()
            session.clear()
        if result['failures']:
            return jsonify(dict(ok=False, message='部分项目未能清除', failures=result['failures'], deleted=result['deleted'])), 500
        return jsonify(dict(ok=True, message='已清除所选的私人数据和生成产物', deleted=result['deleted'],
                            selected_groups=result['selected_groups']))

        delete_kb = body.get('delete_kb', False)
        delete_web = body.get('delete_web', False)
        delete_backup = body.get('delete_backup', False)
        deleted = []
        for fname in ['config.json', 'bilibili_cookies.json', 'mood_state.json', 'personas.json',
                       'user_profiles.json', 'comment_log.json', 'bot_diary.json',
                       'self_evolution.json', 'agent_skill_log.json', 'bot_runtime_state.json',
                       'history_videos.json', 'interests.json', 'web_personas.json',
                       'web_persona.json', 'web_mood.json', 'web_user_profiles.json',
                       'web_action_log.json', 'web_prompt_templates.json', 'web_costs.json',
                       '.web_secret_key', 'search_history.json', 'private_message_log.json',
                       'private_context_db.json', 'standby_config.json', 'standby_stats.json',
                       'monitor_config.json', 'monitor_stats.json', 'reply_cache.json',
                       'processed_comments.json', 'psycho_profile.json', 'recommendation_log.json',
                       'action_log.json', 'content_aversions.json', 'owner_profile.json',
                       'kb_vector_index.json', 'interest_engine.json']:
            fp = DATA_DIR / fname
            if fp.exists():
                fp.unlink()
                deleted.append(fname)
        from core.config import CIPHER_KEY_FILE
        from core.user_data import HIGHLIGHTS_DIR, HTML_EXPORTS_DIR, MINDMAPS_DIR, QR_CODES_DIR, WORD_DIR
        user_root_files = ['bot_memory.json', 'knowledge_metadata.json', 'bot_journal.md', 'learning_log.md']
        for fname in user_root_files:
            fp = USER_DATA_DIR / fname
            if fp.exists():
                fp.unlink()
                deleted.append(fname)
        cipher_key_file = Path(CIPHER_KEY_FILE)
        if cipher_key_file.exists():
            cipher_key_file.unlink()
            deleted.append('.cipher_key')
        if delete_kb:
            knowledge_base_dir = active_knowledge_base_dir()
            if knowledge_base_dir.exists():
                import shutil
                shutil.rmtree(knowledge_base_dir, ignore_errors=True)
                deleted.append('KnowledgeBase/')
        if delete_web:
            web_dir = HIGHLIGHTS_DIR
            if web_dir.exists():
                import shutil
                shutil.rmtree(web_dir, ignore_errors=True)
                deleted.append('highlights/')
        if delete_backup:
            backup_dir = get_backup_dir()
            if backup_dir.exists():
                import shutil
                shutil.rmtree(backup_dir, ignore_errors=True)
                deleted.append(f'{backup_dir}')
        # 清除生成的导出文件（思维导图 / Word / HTML / 二维码）
        for export_dir in (MINDMAPS_DIR, WORD_DIR, HTML_EXPORTS_DIR, QR_CODES_DIR):
            if export_dir.exists():
                import shutil
                shutil.rmtree(export_dir, ignore_errors=True)
                deleted.append(f'{export_dir.name}/')
        # 清除日志
        with bot_output_lock:
            bot_output_lines.clear()
        log_line(f"恢复出厂设置完成，删除了 {len(deleted)} 个文件/目录" + ("（含知识库）" if delete_kb else "") + ("（含干货归档）" if delete_web else "") + ("（含备份）" if delete_backup else ""))
        return jsonify(dict(ok=True, message=f'已清除 {len(deleted)} 个文件', deleted=deleted))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

# ── UP主关注列表 ──
@app.route('/api/up-follow/list')
def api_up_follow_list():
    mem_file = USER_DATA_DIR / "bot_memory.json"
    ups = {}
    followed = []
    if mem_file.exists():
        try:
            mem = json.loads(mem_file.read_text(encoding='utf-8'))
            ups = mem.get('known_ups', {})
            for name, info in ups.items():
                if isinstance(info, dict) and info.get('followed'):
                    followed.append(dict(
                        name=name,
                        uid=info.get('uid', ''),
                        followed_at=info.get('followed_at', ''),
                        impressions=info.get('impressions', 0),
                        avg_score=round(info.get('total_score', 0) / max(info.get('impressions', 1), 1), 1),
                        favorited=info.get('favorited', False),
                        profile_label=str(info.get('profile_label') or '待主页采样'),
                        profile_inspected_at=str(info.get('profile_inspected_at') or ''),
                        profile_samples=info.get('profile_samples') if isinstance(info.get('profile_samples'), list) else [],
                    ))
        except Exception:
            pass
    return jsonify(dict(total=len(followed), items=followed))

# ── 知识库统计 ──
@app.route('/api/kb/stats')
def api_kb_stats():
    kb_dir = active_knowledge_base_dir()
    result = dict(exists=kb_dir.exists(), total_files=0, categories={})
    if kb_dir.exists():
        for root, dirs, files in os.walk(kb_dir):
            rel = os.path.relpath(root, kb_dir)
            parts = rel.split(os.sep) if rel != '.' else []
            depth = len(parts)
            md_files = [f for f in files if f.endswith('.md')]
            if md_files and depth <= 3:
                cat = '/'.join(parts[:3]) if parts else '根目录'
                result['categories'][cat] = result['categories'].get(cat, 0) + len(md_files)
            result['total_files'] += len(md_files)
    return jsonify(result)

# ── 功能操作 (桥接 CLI 功能) ──
@app.route('/api/action/analyze-video', methods=['POST'])
def api_action_analyze_video():
    """手动视频分析 — 多平台输入识别，B站完整分析，其他标注暂不支持。"""
    try:
        body = request.get_json(force=True)
        raw = (body.get('bvid') or body.get('url') or '').strip()
        platform = (body.get('platform') or 'auto').strip().lower()
        if not raw:
            return jsonify(dict(ok=False, message='请输入视频链接 / BV号')), 400
        from services.platform_adapter import (
            SUPPORTED_PLATFORMS,
            PLATFORM_LABELS,
            normalize_video_input,
        )
        norm = normalize_video_input(raw)
        if platform not in ('auto', ''):
            norm = dict(norm)
            norm['platform'] = platform
            norm['ok'] = norm['platform'] in SUPPORTED_PLATFORMS
        plat = norm.get('platform')
        if plat != 'bilibili':
            label = PLATFORM_LABELS.get(plat, plat)
            result = dict(norm)
            result['ok'] = False
            result['message'] = f'{label} 已识别，但当前阶段暂不支持分析（仅 B站可用）'
            return jsonify(result), 400
        bvid = norm.get('video_id') or raw
        mode = (body.get('mode') or '').strip()
        intent = (body.get('intent') or '').strip()
        _mode_map = {"1": "subtitle_only", "2": "asr_only", "3": "vision_only",
                     "4": "subtitle+asr", "5": "subtitle+vision", "6": "asr+vision", "7": "all"}
        force_mode = _mode_map.get(mode, None)  # None = 默认智能流程
        _mode_label = {'subtitle_only': '仅字幕', 'asr_only': '仅ASR', 'vision_only': '仅视觉',
                       'subtitle+asr': '字幕+ASR', 'subtitle+vision': '字幕+视觉',
                       'asr+vision': 'ASR+视觉', 'all': '全部', None: '智能流程'}.get(force_mode)
        log_line(f"触发 B站视频分析: {bvid} (模式={_mode_label}, 意图={'有' if intent else '无'})")

        def _run_analysis():
            try:
                sys.path.insert(0, str(BASE_DIR))
                import asyncio as _asyncio
                from brain.video_analysis import analyze_bilibili_video_input
                loop = _asyncio.new_event_loop()
                _asyncio.set_event_loop(loop)
                ok, msg = loop.run_until_complete(
                    analyze_bilibili_video_input(bvid, force_mode=force_mode, intent=intent))
                log_line(f"[分析] {'完成' if ok else '失败'}: {msg}")
            except Exception as e:
                log_line(f"[分析] 失败: {e}")

        threading.Thread(target=_run_analysis, daemon=True).start()
        result = dict(norm)
        result['ok'] = True
        result['message'] = f'已触发 B站视频分析: {bvid}（{_mode_label}）'
        return jsonify(result)
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/visual-note', methods=['POST'])
def api_action_visual_note():
    """图文学习笔记视频分析，使用时间轴网格与截图标记回写。
    前端将渲染 TOC 侧栏 + 内联截图。"""
    try:
        body = request.get_json(force=True)
        raw = (body.get('bvid') or body.get('url') or '').strip()
        if not raw:
            return jsonify(dict(ok=False, message='请输入视频链接 / BV号')), 400
        from services.platform_adapter import normalize_video_input
        norm = normalize_video_input(raw)
        plat = norm.get('platform')
        if plat != 'bilibili':
            return jsonify(dict(ok=False, message=f'仅支持 B站视频（已识别到 {plat} 平台）')), 400
        bvid = norm.get('video_id') or raw
        custom_prompt = (body.get('custom_prompt') or '').strip()

        log_line(f"触发图文学习笔记分析: {bvid}{' (自定义提示词)' if custom_prompt else ''}")

        def _run_visual_note():
            try:
                sys.path.insert(0, str(BASE_DIR))
                import asyncio as _asyncio
                loop = _asyncio.new_event_loop()
                _asyncio.set_event_loop(loop)
                result = loop.run_until_complete(
                    _analyze_visual_note(bvid, custom_prompt))
                # 写入结果文件供前端轮询
                _cache_visual_note_result(bvid, result)
            except Exception as e:
                log_line(f"[VisualNote] 分析失败: {e}")
                _cache_visual_note_result(bvid, dict(ok=False, error=str(e)))

        threading.Thread(target=_run_visual_note, daemon=True).start()
        return jsonify(dict(ok=True, bvid=bvid, message=f'已触发图文学习笔记分析: {bvid}',
                           status='processing'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/visual-note/status/<bvid>', methods=['GET'])
def api_visual_note_status(bvid):
    """轮询图文学习笔记分析状态。"""
    cache_file = VISUAL_NOTE_CACHE_DIR / f"{bvid}.json"
    if cache_file.exists():
        try:
            data = json.loads(cache_file.read_text(encoding='utf-8'))
            return jsonify(data)
        except Exception:
            pass
    return jsonify(dict(ok=False, status='pending', message='分析进行中或尚未开始'))


async def _analyze_visual_note(bvid: str, custom_prompt: str = "") -> dict:
    """在后台线程中执行图文学习笔记分析。"""
    from xingye_bot.settings import load_settings
    from xingye_bot.llm import ModelClient
    from xingye_bot.state import BotState
    from xingye_bot.video_modes import VideoUnderstanding
    import xingye_bot.grid_frames as gf

    settings = load_settings()
    # 如果传了自定义提示词，临时覆盖配置
    if custom_prompt:
        settings.custom_video_prompt = custom_prompt
    state = BotState()
    model = ModelClient(settings, state)

    vu = VideoUnderstanding(settings, model)
    try:
        # 直接调用图文学习笔记管线
        asset = await vu.fetch_metadata(bvid)
        await vu.fetch_subtitles(asset)

        if asset.duration and asset.duration > settings.video_max_duration_seconds:
            return dict(ok=False, error=f"视频时长 {asset.duration}s 超过上限 {settings.video_max_duration_seconds}s")

        video_path = await vu.download_video(asset)
        grid_imgs = gf.extract_visual_note_grids(
            video_path, read_json(CONFIG_FILE, {}).get("video", {})
        )
        if not grid_imgs:
            return dict(ok=False, error="网格抽帧为空，无法生成图文笔记")

        summary = await vu.summarize_with_grid(asset, video_path, grid_imgs, True, settings.custom_video_prompt)

        # 清理
        if settings.video_delete_after_understand:
            vu.delete_downloaded_video(video_path)

        # 提取 TOC
        toc = []
        for line in summary.split('\n'):
            if line.startswith('## '):
                title = line[3:].strip()
                anchor = title.lower().replace(' ', '-').replace('#', '')
                toc.append(dict(title=title, anchor=anchor))

        result = dict(ok=True, bvid=bvid, title=asset.title, up_name=asset.up_name,
                    url=asset.url, markdown=summary, toc=toc,
                    message=f"图文笔记生成完成: {asset.title}")
        from services.research_archive import ResearchArchive
        result["research_record_id"] = ResearchArchive(DATA_DIR).save_visual_note(result, asset.subtitles).get("id")
        return result

    except Exception as e:
        return dict(ok=False, error=str(e))


# 图文学习笔记结果缓存目录
VISUAL_NOTE_CACHE_DIR = DATA_DIR / "visual_note_cache"
VISUAL_NOTE_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _cache_visual_note_result(bvid: str, result: dict):
    """缓存图文学习笔记分析结果到临时文件。"""
    try:
        cache_file = VISUAL_NOTE_CACHE_DIR / f"{bvid}.json"
        cache_file.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    except Exception:
        pass


def _research_archive():
    from services.research_archive import ResearchArchive
    return ResearchArchive(DATA_DIR)


def _review_execution_display(action_type: str, execution) -> str:
    """Return a concise, non-sensitive description for review logs and modals."""
    if isinstance(execution, dict):
        value = execution.get("result") or execution.get("message") or ""
    else:
        value = execution or ""
    text = str(value).strip()
    looks_like_raw_response = text.startswith(("{", "[")) or "\\u" in text or "msg_key" in text
    if action_type == "private_reply":
        message_key = execution.get("message_key") if isinstance(execution, dict) else ""
        suffix = f"（消息标识: {message_key}）" if message_key else ""
        return f"私信已提交并得到 B 站确认{suffix}"
    if looks_like_raw_response or not text:
        return "平台已确认执行"
    return text[:240]


def _execute_review_action(item: dict) -> dict:
    """Execute one approved action without persisting account credentials."""
    action_type = item.get('action_type') or 'video_like'
    payload = item.get('payload') or {}
    from api.client import BiliClient
    client = BiliClient()
    client._load_credential()
    if not client.credential:
        raise RuntimeError('B站尚未登录，无法执行平台操作')
    proposed_for = str(item.get('account_uid') or '').strip()
    current_uid = str(getattr(client.credential, 'dedeuserid', '') or '').strip()
    if proposed_for and current_uid and proposed_for != current_uid:
        raise RuntimeError('审核动作属于先前登录的账号，已拒绝执行')
    if action_type == 'video_like':
        from bilibili_api.video import Video
        result = _run_coro(Video(bvid=str(payload.get('bvid') or ''), credential=client.credential).like(status=True))
    elif action_type == 'follow_up':
        result = _run_coro(client.follow_up(int(payload.get('uid') or 0)))
        if result.get('code') not in {0, 22014}:
            raise RuntimeError(result.get('msg') or '关注失败')
    elif action_type == 'unfollow_user':
        result = _run_coro(client.unfollow_up(int(payload.get('uid') or 0)))
        if result.get('code') != 0:
            raise RuntimeError(result.get('msg') or '取消关注失败')
    elif action_type == 'send_danmaku':
        result = _run_coro(client.send_danmaku(str(payload.get('bvid') or ''), str(payload.get('text') or '')))
        if result.get('code') != 0:
            raise RuntimeError(result.get('msg') or '弹幕发送失败')
    elif action_type == 'coin':
        from bilibili_api.video import Video
        result = _run_coro(Video(bvid=str(payload.get('bvid') or ''), credential=client.credential).pay_coin(
            num=max(1, min(2, int(payload.get('num') or 1))), like=False))
    elif action_type == 'favorite':
        from bilibili_api import favorite_list
        from bilibili_api.video import Video
        video = Video(bvid=str(payload.get('bvid') or ''), credential=client.credential)
        folders = _run_coro(favorite_list.get_video_favorite_list(
            uid=int(client.credential.dedeuserid), video=video, credential=client.credential))
        folder_items = (folders or {}).get('list') or []
        if not folder_items:
            raise RuntimeError('未找到可用收藏夹')
        result = _run_coro(video.set_favorite(add_media_ids=[folder_items[0]['id']]))
    elif action_type == 'private_reply':
        from bilibili_api import session as bili_session
        result = _run_coro(bili_session.send_msg(
            credential=client.credential,
            receiver_id=int(payload.get('receiver_id') or 0),
            msg_type=bili_session.EventType.TEXT,
            content=str(payload.get('text') or ''),
        ))
        if isinstance(result, dict) and result.get('code') not in (None, 0, '0'):
            message = str(result.get('message') or result.get('msg') or 'B站未接受该私信')
            raise RuntimeError(f'私信未发送: {message}')
    else:
        raise RuntimeError('该行为尚未接入自动执行器，只能保留为人工审核记录')
    execution = {
        'executed': True,
        'result': _review_execution_display(action_type, result),
    }
    if action_type == 'private_reply' and isinstance(result, dict) and result.get('msg_key'):
        execution['message_key'] = str(result['msg_key'])[:120]
    return execution


@app.route('/api/reviews')
def api_reviews():
    from services.like_review import ActionReviewInbox
    inbox = ActionReviewInbox(DATA_DIR)
    items = inbox.list(status=(request.args.get('status') or '').strip(),
                       action_type=(request.args.get('type') or '').strip())
    return jsonify(ok=True, items=items, pending=len(inbox.list(status='pending')))


@app.route('/api/reviews/audit')
def api_review_audit():
    from services.like_review import ActionReviewInbox
    try:
        limit = max(1, min(int(request.args.get('limit') or 200), 1000))
    except (TypeError, ValueError):
        limit = 200
    entries = []
    for entry in ActionReviewInbox(DATA_DIR).audit(limit):
        safe_entry = dict(entry)
        if safe_entry.get('execution'):
            safe_entry['execution'] = {
                'result': _review_execution_display(safe_entry.get('action_type', ''), safe_entry['execution'])
            }
        entries.append(safe_entry)
    return jsonify(ok=True, items=entries)


@app.route('/api/reviews/audit/clear', methods=['POST'])
def api_review_audit_clear():
    """Clear historical review events without changing review queue items."""
    from services.like_review import ActionReviewInbox
    cleared = ActionReviewInbox(DATA_DIR).clear_audit()
    return jsonify(ok=True, cleared=cleared, message=f'已清空 {cleared} 条审核执行记录')


def _record_executed_private_reply_context(item: dict) -> None:
    """Persist a reviewed DM only after Bilibili has accepted it."""
    payload = item.get('payload') or {}
    receiver_id = str(payload.get('receiver_id') or '').strip()
    text = str(payload.get('text') or '').strip()
    if not receiver_id or not text:
        return
    from persona.managers import PrivateContextDB
    context_db = PrivateContextDB()
    metadata = {'sent': True, 'reviewed': True}
    for key in ('owner_share', 'owner_share_bvid', 'owner_share_test', 'owner_share_title', 'owner_share_materials'):
        if key in payload:
            metadata[key] = payload[key]
    recent = context_db.get_context(receiver_id, max_messages=1)
    if not (recent and recent[-1].get('role') == 'assistant' and recent[-1].get('content') == text):
        context_db.add_message(receiver_id, 'assistant', text, metadata=metadata)
    if payload.get('remember_outbound'):
        label = '主动分享视频' if payload.get('owner_share') else '主动私信'
        context_db.add_memory(
            receiver_id,
            f'{label}: {text}',
            tags=['private_message', 'proactive', 'owner_share'] if payload.get('owner_share') else ['private_message', 'proactive'],
            metadata=metadata,
        )
    context_db.update_profile(
        receiver_id,
        last_reply=text[:160],
        last_reply_at=datetime.now().isoformat(),
        consecutive_ai_replies=1,
    )


def _sync_owner_share_review(item: dict, status: str, detail: str = "") -> None:
    """Keep the owner-share history honest after a review decision."""
    payload = item.get('payload') or {}
    if item.get('action_type') != 'private_reply' or not payload.get('owner_share'):
        return
    bvid = str(payload.get('owner_share_bvid') or '').strip()
    if not bvid:
        return
    try:
        from services.owner_share import OwnerShareService
        OwnerShareService().mark_review_result(bvid, status, detail)
    except Exception as exc:
        log_line(f"[Owner share] Failed to sync review status: {redact_sensitive_text(str(exc))}")


@app.route('/api/reviews/settings', methods=['GET', 'POST'])
def api_review_settings():
    from services.like_review import ACTION_TYPES, review_settings
    from core.config import load_config, save_config
    config = load_config()
    if request.method == 'POST':
        body = request.get_json(force=True) or {}
        current = review_settings(config)
        current['enabled'] = body.get('enabled', current['enabled']) is not False
        current['desktop_notification'] = body.get(
            'desktop_notification', current['desktop_notification']) is not False
        selected = body.get('action_types', {})
        if isinstance(selected, dict):
            for key in ACTION_TYPES:
                if key in selected:
                    current['action_types'][key] = bool(selected[key])
        config['approval_review'] = current
        if not save_config(config):
            return jsonify(ok=False, message='审核设置保存失败'), 500
        import core.config as core_config
        core_config.config.clear()
        core_config.config.update(load_config())
    current = review_settings(config)
    types = [dict(id=key, **meta, required=current['action_types'].get(key, False)) for key, meta in ACTION_TYPES.items()]
    return jsonify(ok=True, enabled=current['enabled'],
                   desktop_notification=current['desktop_notification'],
                   action_types=current['action_types'], types=types)


@app.route('/api/reviews/decision', methods=['POST'])
def api_review_decision():
    body = request.get_json(force=True) or {}
    item_ids = [str(x) for x in body.get('ids', []) if str(x)]
    decision = str(body.get('decision') or '')
    if not item_ids or decision not in {'approved', 'rejected'}:
        return jsonify(ok=False, message='请选择审核记录并给出有效决定'), 400
    from services.like_review import ActionReviewInbox
    inbox = ActionReviewInbox(DATA_DIR)
    results = []
    for item_id in item_ids:
        item = inbox.decide(item_id, decision)
        if not item:
            results.append({'id': item_id, 'ok': False, 'message': '记录不存在或已处理'})
            continue
        details = {
            'id': item_id,
            'title': item.get('title', ''),
            'action_label': item.get('action_label') or item.get('action_type', ''),
        }
        if decision == 'approved':
            try:
                execution = _execute_review_action(item)
                executed_at = datetime.now().isoformat(timespec='seconds')
                inbox.update(item_id, status='executed', executed_at=executed_at, execution=execution)
                if item.get('action_type') == 'private_reply':
                    _record_executed_private_reply_context(item)
                message = str(execution.get('result') or '平台已返回执行成功')[:500]
                _sync_owner_share_review(item, 'executed', message)
                log_line(f"[REVIEW] 已执行 {details['action_label']}: {details['title']} | {message}")
                results.append({**details, 'ok': True, 'status': 'executed', 'executed_at': executed_at, 'message': message})
            except Exception as exc:
                error = redact_sensitive_text(str(exc))
                failed_at = datetime.now().isoformat(timespec='seconds')
                inbox.update(item_id, status='failed', failed_at=failed_at, error=error)
                _sync_owner_share_review(item, 'failed', error)
                log_line(f"[REVIEW] 执行失败 {details['action_label']}: {details['title']} | {error}")
                results.append({**details, 'ok': False, 'status': 'failed', 'failed_at': failed_at, 'message': error})
        else:
            _sync_owner_share_review(item, 'rejected', '用户在审核中拒绝')
            log_line(f"[REVIEW] 已拒绝 {details['action_label']}: {details['title']}")
            results.append({**details, 'ok': True, 'status': 'rejected', 'message': '已拒绝，未向平台发起操作'})
    succeeded = sum(1 for result in results if result.get('ok'))
    return jsonify(ok=succeeded == len(results), processed=len(results), succeeded=succeeded, results=results)

@app.route('/api/like-review')
def api_like_review():
    return api_reviews()

@app.route('/api/like-review/<item_id>/<decision>', methods=['POST'])
def api_like_review_decision(item_id, decision):
    if decision == 'ignored':
        decision = 'rejected'
    if decision not in {'approved', 'rejected'}: return jsonify(ok=False, message='无效决定'), 400
    from services.like_review import ActionReviewInbox
    inbox = ActionReviewInbox(DATA_DIR)
    item=inbox.decide(item_id, decision)
    if not item: return jsonify(ok=False, message='建议不存在或已处理'), 404
    if decision == 'approved':
        try:
            execution = _execute_review_action(item)
            item = inbox.update(item_id, status='executed', executed_at=datetime.now().isoformat(timespec='seconds'), execution=execution) or item
            log_line(f"[REVIEW] 已执行 {item.get('action_label')}: {item.get('title')}")
        except Exception as e:
            item = inbox.update(item_id, status='failed', error=redact_sensitive_text(str(e))) or item
            log_line(f"[REVIEW] 执行失败 {item.get('action_label')}: {item.get('title')} | {item.get('error', '')}")
            return jsonify(ok=False, item=item, message=item.get('error')), 400
    elif decision == 'rejected':
        log_line(f"[REVIEW] 已拒绝 {item.get('action_label')}: {item.get('title')}")
    return jsonify(ok=True, item=item)

@app.route('/like-review')
def like_review_page():
    return redirect('/?page=reviews')
    return Response('''<!doctype html><meta charset="utf-8"><title>点赞审核收件箱</title><style>body{font:14px Arial,"Microsoft YaHei";margin:28px;max-width:860px}article{border-bottom:1px solid #ddd;padding:14px 0}button{padding:7px;margin-right:8px}</style><h1>点赞审核收件箱</h1><p>AI 只提交建议，不会自动点赞。由你决定批准或忽略。</p><main id="items"></main><script>async function load(){let r=await fetch('/api/like-review').then(x=>x.json());items.innerHTML=r.items.map(x=>'<article><b>'+x.title+'</b> · '+x.up_name+' · '+x.score+'分<br>'+x.reason+'<br><a target="_blank" href="'+x.url+'">查看视频</a><p>状态：'+x.status+'</p>'+(x.status==='pending'?'<button onclick="d(\\''+x.id+'\\',\\'approved\\')">批准点赞</button><button onclick="d(\\''+x.id+'\\',\\'ignored\\')">忽略</button>':'')+'</article>').join('')}async function d(id,x){await fetch('/api/like-review/'+id+'/'+x,{method:'POST'});load()}load()</script>''', mimetype='text/html')


@app.route('/api/research/projects', methods=['GET', 'POST'])
def api_research_projects():
    try:
        archive = _research_archive()
        if request.method == 'GET':
            return jsonify(ok=True, projects=archive.projects())
        body = request.get_json(force=True) or {}
        project = archive.create_project(body.get('name', ''), body.get('description', ''), body.get('tags', []))
        return jsonify(ok=True, project=project)
    except Exception as e:
        return jsonify(ok=False, message=str(e)), 400


@app.route('/api/research/records')
def api_research_records():
    archive = _research_archive()
    return jsonify(ok=True, records=archive.records(request.args.get('q', ''), request.args.get('project_id', '')))


@app.route('/api/research/export/<fmt>')
def api_research_export(fmt):
    if fmt not in {'json', 'csv'}:
        return jsonify(ok=False, message='仅支持 json 或 csv'), 400
    content, mime = _research_archive().export(fmt, request.args.get('q', ''), request.args.get('project_id', ''))
    return Response(content, mimetype=mime, headers={'Content-Disposition': f'attachment; filename=research_records.{fmt}'})


@app.route('/api/research/batch', methods=['POST'])
def api_research_batch():
    try:
        body = request.get_json(force=True) or {}
        bvids = [str(x).strip() for x in body.get('bvids', []) if str(x).strip()]
        project_id = str(body.get('project_id', '')).strip()
        if not bvids:
            return jsonify(ok=False, message='请至少提供一个 BV 号或视频链接'), 400
        if len(bvids) > 20:
            return jsonify(ok=False, message='单次最多处理 20 个视频'), 400
        def _work(tid):
            completed = 0
            for index, raw in enumerate(bvids, 1):
                bvid_match = _re.search(r'(BV[0-9A-Za-z]{10})', raw)
                bvid = bvid_match.group(1) if bvid_match else raw
                _update_task(tid, message=f'[{index}/{len(bvids)}] 研究归档中: {bvid}')
                result = _run_coro(_analyze_visual_note(bvid))
                if result.get('ok'):
                    # Move the freshly created record into the selected project.
                    if project_id:
                        archive = _research_archive()
                        archive.assign_project(result.get('research_record_id', ''), project_id)
                    completed += 1
            _finish_task(tid, dict(ok=completed, total=len(bvids), project_id=project_id))
        tid = _start_task(f'准备归档 {len(bvids)} 个研究视频...', _work)
        return jsonify(ok=True, task_id=tid)
    except Exception as e:
        return jsonify(ok=False, message=str(e)), 400


@app.route('/research')
def research_workspace():
    return Response('''<!doctype html><meta charset="utf-8"><title>研究工作台</title>
<style>body{font:14px Arial,"Microsoft YaHei";margin:28px;max-width:1100px;color:#17212b}input,textarea,select,button{padding:8px;margin:4px}textarea{width:460px;height:80px}table{border-collapse:collapse;width:100%;margin-top:16px}th,td{border-bottom:1px solid #ddd;padding:9px;text-align:left}small{color:#68737d}.warn{background:#fff5d8;padding:10px}</style>
<h1>研究工作台</h1><p class="warn">原始字幕和视频画面是原始材料。AI 笔记、摘要和结论均属于 AI 生成或 AI 推断，引用前必须回查时间戳证据。</p>
<section><h2>新建项目</h2><input id="name" placeholder="课题或项目名称"><input id="tags" placeholder="标签，用逗号分隔"><button onclick="project()">创建</button></section>
<section><h2>批量归档视频</h2><select id="project"></select><br><textarea id="videos" placeholder="每行一个 BV 号或视频链接"></textarea><br><button onclick="batch()">开始批量分析并归档</button> <span id="status"></span></section>
<section><h2>检索与导出</h2><input id="q" placeholder="按标题、作者或标签检索" oninput="load()"><button onclick="location='/api/research/export/json?q='+encodeURIComponent(q.value)">导出 JSON</button><button onclick="location='/api/research/export/csv?q='+encodeURIComponent(q.value)">导出 CSV</button><table><thead><tr><th>来源</th><th>作者</th><th>访问日期</th><th>证据</th><th>材料边界</th></tr></thead><tbody id="rows"></tbody></table></section>
<script>async function api(url,opt){let r=await fetch(url,opt);return r.json()}async function projects(){let r=await api('/api/research/projects');project.innerHTML='<option value="">未分组</option>'+r.projects.map(x=>'<option value="'+x.id+'">'+x.name+'</option>').join('')}async function project(){let r=await api('/api/research/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.value,tags:tags.value.split(',')})});if(!r.ok)return alert(r.message);name.value='';await projects()}async function batch(){let bvids=videos.value.split(/\\n/).filter(Boolean);let r=await api('/api/research/batch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({bvids,project_id:project.value})});status.textContent=r.ok?'任务已启动：'+r.task_id:r.message}async function load(){let r=await api('/api/research/records?q='+encodeURIComponent(q.value));rows.innerHTML=r.records.map(x=>'<tr><td><a href="'+x.source.url+'" target="_blank">'+x.source.title+'</a></td><td>'+x.source.author+'</td><td>'+x.source.accessed_at+'</td><td>'+x.evidence.map(e=>'<a href="'+e.source_url+'" target="_blank">'+e.timestamp+'</a>').join('、')+'</td><td><small>'+x.materials.notice+'</small></td></tr>').join('')}projects();load()</script>''', mimetype='text/html')




@app.route('/api/mindmaps')
def api_mindmaps():
    """List generated local mind-map HTML files for the visual workspace."""
    try:
        from core.user_data import MINDMAPS_DIR
        from urllib.parse import quote as _url_quote
        root = Path(MINDMAPS_DIR)
        if not root.exists():
            return jsonify(ok=True, maps=[])
        maps = []
        for path in sorted(root.rglob('*.mindmap.html'), key=lambda item: item.stat().st_mtime, reverse=True):
            maps.append({
                'name': path.stem.replace('.mindmap', ''),
                'path': str(path),
                'updated_at': datetime.fromtimestamp(path.stat().st_mtime).strftime('%Y-%m-%d %H:%M'),
                'url': '/api/action/mindmap/view?path=' + _url_quote(str(path.resolve())),
            })
        return jsonify(ok=True, maps=maps)
    except OSError as exc:
        return jsonify(ok=False, message=str(exc), maps=[]), 500


@app.route('/api/mindmaps/delete', methods=['POST'])
def api_mindmaps_delete():
    """Delete one generated local mind-map HTML without touching its source note."""
    body = request.get_json(silent=True) or {}
    if body.get('confirmed') is not True:
        return jsonify(ok=False, message='请先确认删除本地思维导图'), 400
    requested = Path(str(body.get('path') or '')).resolve()
    cfg = read_json(CONFIG_FILE, {})
    configured = Path((cfg.get('mindmap') or {}).get('output_dir') or 'MindMaps')
    if not configured.is_absolute():
        configured = BASE_DIR / configured
    from core.user_data import MINDMAPS_DIR
    allowed_roots = {Path(MINDMAPS_DIR).resolve(), (BASE_DIR / 'MindMaps').resolve(), configured.resolve()}
    allowed = (
        requested.is_file()
        and requested.name.endswith('.mindmap.html')
        and any(requested == root or root in requested.parents for root in allowed_roots)
    )
    if not allowed:
        return jsonify(ok=False, message='思维导图不存在或路径不允许'), 404
    try:
        requested.unlink()
    except OSError as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 500
    return jsonify(ok=True, message='已删除本地思维导图')


@app.route('/api/action/mindmap', methods=['POST'])
def api_action_mindmap():
    """思维导图导出 — 单文件或整个知识库 → 可交互 HTML（复用 services.mindmap_export）。"""
    try:
        body = request.get_json(force=True)
        mode = (body.get('mode') or 'single').strip().lower()
        rel = (body.get('file') or '').strip()
        from services.mindmap_export import export_mindmap
        cfg = read_json(CONFIG_FILE, {})
        knowledge_base_dir = active_knowledge_base_dir()
        if mode == 'library':
            md_files = sorted(knowledge_base_dir.rglob('*.md'))
            if not md_files:
                return jsonify(dict(ok=False, message='知识库为空，无法导出')), 400
            ok_cnt = 0
            out = []
            for p in md_files:
                try:
                    o = export_mindmap(p, cfg=cfg)
                    ok_cnt += 1
                    from urllib.parse import quote as _url_quote
                    out.append(dict(path=o, title=Path(o).stem.replace('.mindmap', ''),
                                    url='/api/action/mindmap/view?path=' + _url_quote(str(Path(o).resolve()))))
                except Exception as e:
                    out.append({'error': str(e), 'file': str(p)})
            return jsonify(dict(ok=True, message=f'批量导出完成：成功 {ok_cnt}/{len(md_files)}',
                                mode='library', files=out))
        # single
        if not rel:
            return jsonify(dict(ok=False, message='请选择知识文件')), 400
        target = (knowledge_base_dir / rel).resolve()
        kb_root = knowledge_base_dir.resolve()
        if target != kb_root and kb_root not in target.parents:
            return jsonify(dict(ok=False, message='非法路径')), 400
        if not target.exists():
            return jsonify(dict(ok=False, message='文件不存在')), 400
        out_path = export_mindmap(target, cfg=cfg)
        html = Path(out_path).read_text(encoding='utf-8', errors='replace')
        from urllib.parse import quote as _url_quote
        return jsonify(dict(ok=True, message='思维导图已生成', mode='single',
                            path=out_path, html=html,
                            url='/api/action/mindmap/view?path=' + _url_quote(str(Path(out_path).resolve()))))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/mindmap/view')
def api_action_mindmap_view():
    """Serve only generated mind-map HTML files from configured output roots."""
    from core.user_data import MINDMAPS_DIR
    requested = Path(request.args.get('path') or '').resolve()
    cfg = read_json(CONFIG_FILE, {})
    configured = Path((cfg.get('mindmap') or {}).get('output_dir') or 'MindMaps')
    if not configured.is_absolute():
        configured = BASE_DIR / configured
    allowed_roots = {Path(MINDMAPS_DIR).resolve(), (BASE_DIR / 'MindMaps').resolve(), configured.resolve()}
    allowed = requested.is_file() and requested.suffix.lower() == '.html' and any(
        requested == root or root in requested.parents for root in allowed_roots
    )
    if not allowed:
        return jsonify(ok=False, message='思维导图不存在或路径不允许'), 404
    return send_file(requested, mimetype='text/html')


@app.route('/api/action/toggle-flag', methods=['POST'])
def api_action_toggle_flag():
    """通用开关：封面分析 / 快速模式 / 安静模式 / ASR（写入 config.json，并尽力热重载本进程全局）。"""
    try:
        body = request.get_json(force=True)
        key = (body.get('key') or '').strip()
        allowed = {
            'cover_enabled': ('vision', 'cover_enabled', 'VISION_COVER_ENABLED'),
            'quick_mode': ('speed', 'no_human_delay', 'NO_HUMAN_DELAY'),
            'quiet_mode': ('system', 'quiet_mode', 'QUIET_MODE'),
            'asr_enabled': ('asr', 'enabled', 'ASR_ENABLED'),
        }
        if key not in allowed:
            return jsonify(dict(ok=False, message='未知开关')), 400
        section, field, gname = allowed[key]
        config = read_json(CONFIG_FILE, {})
        sec = config.setdefault(section, {})
        new_val = not bool(sec.get(field, False))
        sec[field] = new_val
        write_json(CONFIG_FILE, config)
        try:
            import cli.app as _app
            setattr(_app, gname, new_val)
        except Exception:
            pass
        label = {'cover_enabled': '封面分析', 'quick_mode': '快速模式',
                 'quiet_mode': '安静模式', 'asr_enabled': 'ASR语音识别'}[key]
        return jsonify(dict(ok=True, key=key, value=new_val,
                            message=f'{label}已{"开启" if new_val else "关闭"}'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/flags')
def api_action_flags():
    """读取快捷开关当前状态（封面分析 / 快速模式 / 安静模式 / ASR）。"""
    try:
        config = read_json(CONFIG_FILE, {})
        return jsonify(dict(
            cover_enabled=bool(config.get('vision', {}).get('cover_enabled', False)),
            quick_mode=bool(config.get('speed', {}).get('no_human_delay', False)),
            quiet_mode=bool(config.get('system', {}).get('quiet_mode', False)),
            asr_enabled=bool(config.get('asr', {}).get('enabled', False)),
        ))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


# ─────────────────────────────────────────────────────────────────────────────
# 长任务机制（UP学习 / 视频转网页 / 出题 / 深入了解 都是耗时任务，前端轮询）
# ─────────────────────────────────────────────────────────────────────────────
import asyncio as _asyncio
import threading
import uuid as _uuid
import re as _re
import json as _json
from datetime import datetime as _dt
from flask import send_file

TASKS = {}  # task_id -> {status, message, result, error}
_TASKS_LOCK = threading.RLock()
_TASK_TTL_SECONDS = 60 * 60
_TASK_LIMIT = 200


def _cleanup_tasks(now=None):
    now = now if now is not None else _dt.now().timestamp()
    expired = [
        tid for tid, task in TASKS.items()
        if task.get('status') in {'done', 'error'}
        and now - task.get('finished_at', now) >= _TASK_TTL_SECONDS
    ]
    for tid in expired:
        TASKS.pop(tid, None)

    overflow = max(0, len(TASKS) - _TASK_LIMIT)
    completed = sorted(
        ((task.get('finished_at', now), tid) for tid, task in TASKS.items()
         if task.get('status') in {'done', 'error'}),
    )
    for _, tid in completed[:overflow]:
        TASKS.pop(tid, None)


def _update_task(task_id, **fields):
    with _TASKS_LOCK:
        task = TASKS.get(task_id)
        if task:
            task.update(fields)


def _finish_task(task_id, result):
    with _TASKS_LOCK:
        task = TASKS.get(task_id)
        if task:
            finished = _dt.now().timestamp()
            task.update(result=result, error=None, finished_at=finished, status='done',
                        elapsed=round(finished - task.get('started_at', finished), 3))


def _fail_task(task_id, error):
    with _TASKS_LOCK:
        task = TASKS.get(task_id)
        if task:
            finished = _dt.now().timestamp()
            task.update(result=None, error=str(error), finished_at=finished, status='error',
                        elapsed=round(finished - task.get('started_at', finished), 3))


def _start_task(message, work):
    with _TASKS_LOCK:
        _cleanup_tasks()
        task_id = _uuid.uuid4().hex
        TASKS[task_id] = dict(status='running', message=message, result=None, error=None,
                              started_at=_dt.now().timestamp(), elapsed=0)

    def _runner():
        try:
            work(task_id)
        except Exception as exc:
            log_line(redact_sensitive_text(
                f"后台任务异常 ({type(exc).__name__}): {exc}\n{traceback.format_exc(limit=8)}"))
            _fail_task(task_id, exc)

    threading.Thread(target=_runner, daemon=True).start()
    return task_id


def _run_coro(coro):
    loop = _asyncio.new_event_loop()
    try:
        _asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _mode_map():
    return {"1": "subtitle_only", "2": "asr_only", "3": "vision_only",
            "4": "subtitle+asr", "5": "subtitle+vision", "6": "asr+vision", "7": "all"}


# ── UP主搜索 / 视频列表 / 批量学习 ──
@app.route('/api/action/up-search', methods=['POST'])
def api_action_up_search():
    """搜索UP主（按名字/UID）。"""
    try:
        body = request.get_json(force=True)
        q = (body.get('query') or '').strip()
        if not q:
            return jsonify(dict(ok=False, message='请输入UP主名字或UID')), 400
        try:
            uid_candidate = int(q)
            return jsonify(dict(ok=True, ups=[dict(uid=uid_candidate, name=q, sign='', fans=0, is_uid=True)]))
        except ValueError:
            pass
        from bilibili_api import search as bili_search
        data = _run_coro(bili_search.search_by_type(
            q, search_type=bili_search.SearchObjectType.USER, page=1))
        items = (data or {}).get('result') or []
        out = []
        seen = set()
        for u in items[:10]:
            uid = int(u.get('mid') or u.get('uid', 0) or 0)
            if not uid or uid in seen:
                continue
            seen.add(uid)
            out.append(dict(uid=uid,
                            name=u.get('uname') or u.get('name', ''),
                            sign=(u.get('usign') or u.get('sign', ''))[:80],
                            fans=u.get('fans', 0)))
        return jsonify(dict(ok=True, ups=out))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/up-videos', methods=['POST'])
def api_action_up_videos():
    """获取UP主投稿视频列表。"""
    try:
        body = request.get_json(force=True)
        uid = int(body.get('uid') or 0)
        limit = int(body.get('limit') or 20)
        if not uid:
            return jsonify(dict(ok=False, message='缺少 uid')), 400
        sys.path.insert(0, str(BASE_DIR))
        from brain.agent_brain import AgentBrain
        brain = AgentBrain()
        brain.bili._load_credential()
        info = _run_coro(brain.bili.get_up_info(uid)) or {}
        raw_videos = _run_coro(brain.bili.get_up_videos(uid, limit=min(limit, 50))) or []
        videos, seen_bvids = [], set()
        for video in raw_videos:
            if not isinstance(video, dict):
                continue
            bvid = str(video.get('bvid') or '').strip()
            if not bvid or bvid in seen_bvids:
                continue
            seen_bvids.add(bvid)
            videos.append(video)
        return jsonify(dict(ok=True, up=info, videos=videos))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/up-learn', methods=['POST'])
def api_action_up_learn():
    """批量学习选中的UP主视频（后台任务，逐个调用视频分析）。"""
    try:
        body = request.get_json(force=True)
        bvids = body.get('bvids') or []
        mode = (body.get('mode') or '').strip()
        intent = (body.get('intent') or '').strip()
        if not bvids:
            return jsonify(dict(ok=False, message='请至少选择一个视频')), 400
        if len(bvids) > 50:
            return jsonify(dict(ok=False, message='单次最多学习 50 个视频')), 400
        configured_timeout = (read_json(CONFIG_FILE, {}).get('up_learning') or {}).get(
            'per_video_timeout_seconds', 600)
        try:
            timeout_seconds = max(120, min(3600, int(body.get('timeout_seconds') or configured_timeout)))
        except (TypeError, ValueError):
            timeout_seconds = 600
        force_mode = _mode_map().get(mode)
        def _work(tid):
            sys.path.insert(0, str(BASE_DIR))
            from brain.video_analysis import analyze_bilibili_video_input
            ok_cnt = 0
            details = []
            for i, bvid in enumerate(bvids, 1):
                try:
                    _update_task(tid, message=f'[{i}/{len(bvids)}] 分析中: {bvid}')
                    ok, msg = _run_coro(
                        _asyncio.wait_for(
                            analyze_bilibili_video_input(bvid, force_mode=force_mode, intent=intent),
                            timeout=timeout_seconds,
                        ))
                    if ok:
                        ok_cnt += 1
                    safe_msg = redact_sensitive_text(msg)
                    details.append(dict(bvid=bvid, ok=bool(ok), stage='完成' if ok else '分析失败',
                                        message=safe_msg))
                    _update_task(tid, message=f'[{i}/{len(bvids)}] {"完成" if ok else "失败"}: {safe_msg}')
                except _asyncio.TimeoutError:
                    safe_error = f'单个视频分析超过 {timeout_seconds} 秒，已跳过并继续下一条'
                    details.append(dict(bvid=bvid, ok=False, stage='超时', message=safe_error))
                    _update_task(tid, message=f'[{i}/{len(bvids)}] 超时: {safe_error}')
                except Exception as exc:
                    safe_error = redact_sensitive_text(str(exc))
                    details.append(dict(bvid=bvid, ok=False, stage='异常', message=safe_error))
                    _update_task(tid, message=f'[{i}/{len(bvids)}] 异常: {safe_error}')
            _finish_task(tid, dict(ok=ok_cnt, failed=len(bvids) - ok_cnt,
                                   total=len(bvids), details=details))

        tid = _start_task(f'准备学习 {len(bvids)} 个视频...', _work)
        return jsonify(dict(ok=True, task_id=tid, message=f'已启动学习 {len(bvids)} 个视频'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


# ── 视频 → 网页（多风格）/ 导出 ──
@app.route('/api/action/video2web', methods=['POST'])
def api_action_video2web():
    """生成视频学习网页（幻灯片风格 HTML）。"""
    try:
        body = request.get_json(force=True)
        raw = (body.get('bvid') or '').strip()
        theme = (body.get('theme') or 'auto').strip()
        custom_prompt = (body.get('custom_prompt') or '').strip()
        enhanced_animations = bool(body.get('enhanced_animations', False))
        try:
            slide_count = max(4, min(int(body.get('slide_count') or 10), 20))
        except (TypeError, ValueError):
            return jsonify(dict(ok=False, message='页数必须是 4 到 20 的整数')), 400
        if not raw:
            return jsonify(dict(ok=False, message='请输入视频 BV号/链接')), 400
        m = _re.search(r'(BV[0-9A-Za-z]{10})', raw)
        bvid = m.group(1) if m else raw
        def _work(tid):
            cfg = read_json(CONFIG_FILE, {})
            api_key = cfg.get('api', {}).get('unified_api_key', '') or os.getenv('BILI_AI_API_KEY', '')
            base_url = cfg.get('api', {}).get('unified_base_url', '') or os.getenv('BILI_AI_BASE_URL', '')
            model = cfg.get('api', {}).get('model_brain', '') or cfg.get('api', {}).get('model', '')
            cookies = None
            if COOKIE_FILE.exists():
                try:
                    cookies = _json.loads(COOKIE_FILE.read_text(encoding='utf-8'))
                except Exception:
                    cookies = None
            sys.path.insert(0, str(BASE_DIR))
            from services.video_to_ppt import generate_ppt_from_bvid
            res = _run_coro(generate_ppt_from_bvid(
                bvid, api_key=api_key, base_url=base_url, model=model,
                cookies_obj=cookies, theme=theme, custom_prompt=custom_prompt,
                enhanced_animations=enhanced_animations, slide_count=slide_count,
                open_browser=False, auto_save=True))
            if res.get('success'):
                _finish_task(tid, dict(html=res.get('html_content', ''),
                                       path=res.get('html_path', ''),
                                       title=res.get('title', ''),
                                       theme=res.get('theme', theme),
                                       slide_count=res.get('slide_count', 0),
                                       requested_slide_count=res.get('requested_slide_count', slide_count)))
            else:
                _fail_task(tid, res.get('error', '生成失败'))

        tid = _start_task('AI 正在生成网页...', _work)
        return jsonify(dict(ok=True, task_id=tid, message='已启动网页生成'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


def _html_to_plain_text(html):
    t = _re.sub(r'<script.*?</script>', '', html, flags=_re.S | _re.I)
    t = _re.sub(r'<style.*?</style>', '', t, flags=_re.S | _re.I)
    t = _re.sub(r'<[^>]+>', ' ', t)
    for a, b in [('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'), ('&quot;', '"')]:
        t = t.replace(a, b)
    t = _re.sub(r'[ \t]+', ' ', t)
    t = _re.sub(r'\n\s*\n+', '\n\n', t)
    return t.strip()


@app.route('/api/action/export-docx', methods=['POST'])
def api_action_export_docx():
    """把生成的网页 HTML 导出为 Word（提取正文）。"""
    try:
        body = request.get_json(force=True)
        html = body.get('html', '')
        title = (body.get('title') or '视频学习页').strip() or '视频学习页'
        from flask import send_file
        from services.document_export import export_docx_text
        fn = Path(export_docx_text(_html_to_plain_text(html), title, out_dir=DATA_DIR / 'DocumentExports'))
        return send_file(str(fn), as_attachment=True, download_name=fn.name)
    except RuntimeError as e:
        return jsonify(dict(ok=False, message=str(e))), 500
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/export-pdf', methods=['POST'])
def api_action_export_pdf():
    """把生成的网页 HTML 导出为 PDF（提取正文）。"""
    try:
        body = request.get_json(force=True)
        html = body.get('html', '')
        title = (body.get('title') or '视频学习页').strip() or '视频学习页'
        from flask import send_file
        from services.document_export import export_pdf_text
        fn = Path(export_pdf_text(_html_to_plain_text(html), title, out_dir=DATA_DIR / 'DocumentExports'))
        return send_file(str(fn), as_attachment=True, download_name=fn.name)
    except RuntimeError as e:
        return jsonify(dict(ok=False, message=str(e))), 500
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


# ── 学习工具：出题 / 深入了解 ──
@app.route('/api/action/quiz', methods=['POST'])
def api_action_quiz():
    """AI 出题考试。"""
    try:
        body = request.get_json(force=True)
        source_type = body.get('source_type', 'video')
        def _work(tid):
            sys.path.insert(0, str(BASE_DIR))
            from services.quiz_generator import generate_quiz
            kw = dict(
                source_type=source_type,
                bvid=body.get('bvid', ''),
                kb_file_path=body.get('kb_file_path', ''),
                kb_file_content=body.get('kb_file_content', ''),
                question_count=int(body.get('question_count') or 5),
                difficulty=body.get('difficulty', 'medium'),
                question_type=body.get('question_type', 'mixed'),
                style=body.get('style', 'standard'),
                custom_prompt=body.get('custom_prompt', ''),
            )
            res = _run_coro(generate_quiz(**kw))
            if res.get('success'):
                _finish_task(tid, dict(content=res.get('quiz_content', ''),
                                       path=res.get('saved_path', ''),
                                       title=res.get('source_title', '')))
            else:
                _fail_task(tid, res.get('error', '出题失败'))

        tid = _start_task('AI 正在出题...', _work)
        return jsonify(dict(ok=True, task_id=tid, message='已启动出题'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/deep-dive', methods=['POST'])
def api_action_deep_dive():
    """AI 深入了解 / 深度学习。"""
    try:
        body = request.get_json(force=True)
        topic = (body.get('topic') or '').strip()
        if not topic:
            return jsonify(dict(ok=False, message='请输入想了解的主题')), 400
        def _work(tid):
            sys.path.insert(0, str(BASE_DIR))
            from services.deep_dive import run_deep_dive
            res = _run_coro(run_deep_dive(
                topic=topic, mode=body.get('mode', 'search'),
                video_count=int(body.get('video_count') or 10),
                sort_by=body.get('sort_by', 'default'),
                additional_context=body.get('context', '')))
            if res.get('success'):
                _finish_task(tid, dict(report=res.get('report', ''), path=res.get('saved_path', '')))
            else:
                _fail_task(tid, res.get('error', '深入了解失败'))

        tid = _start_task('AI 正在深入学习...', _work)
        return jsonify(dict(ok=True, task_id=tid, message='已启动深入了解'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400




@app.route('/api/action/deep-research', methods=['POST'])
def api_action_deep_research():
    """深研计划：多来源证据链研究与可复现来源清单。"""
    try:
        body = request.get_json(force=True)
        topic = (body.get('topic') or '').strip()
        if not topic:
            return jsonify(dict(ok=False, message='请输入研究主题')), 400
        mode = body.get('mode', 'search')
        mode = mode if mode in {'search', 'bilibili'} else 'search'
        try:
            source_count = max(12, min(40, int(body.get('source_count') or 24)))
        except (TypeError, ValueError):
            source_count = 24
        def _work(tid):
            sys.path.insert(0, str(BASE_DIR))
            from services.deep_dive import run_deep_research
            res = _run_coro(run_deep_research(
                topic=topic,
                mode=mode,
                source_count=source_count,
                sort_by=body.get('sort_by', 'default'),
                additional_context=(body.get('context') or '').strip(),
                custom_prompt=(body.get('custom_prompt') or '').strip(),
            ))
            if res.get('success'):
                _finish_task(tid, dict(
                    report=res.get('report', ''),
                    path=res.get('saved_path', ''),
                    manifest_path=res.get('research_manifest_path', ''),
                    extra_paths=res.get('extra_paths', {}),
                ))
            else:
                _fail_task(tid, res.get('error', '深研计划失败'))

        tid = _start_task('深研计划正在收集来源与整理证据链...', _work)
        return jsonify(dict(ok=True, task_id=tid, message='深研计划已启动'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


# ── Agent 模式 API ──

@app.route('/api/action/deep-dive-agent', methods=['POST'])
def api_action_deep_dive_agent():
    """Agent 模式深入了解 — 多轮对话。"""
    try:
        body = request.get_json(force=True)
        topic = (body.get('topic') or '').strip()
        session_id = body.get('session_id', '')
        user_msg = body.get('message', '')
        # 如果是新会话
        if not session_id:
            if not topic:
                return jsonify(dict(ok=False, message='请输入主题或提供 session_id')), 400
        if session_id and not user_msg and not topic:
            return jsonify(dict(ok=False, message='请输入消息内容')), 400

        def _work(tid):
            sys.path.insert(0, str(BASE_DIR))
            from services.learning_agent import LearningAgentSession, run_learning_agent
            if session_id:
                session = LearningAgentSession.load(session_id)
                if not session:
                    _fail_task(tid, f'会话 {session_id} 不存在')
                    return
            else:
                session = LearningAgentSession(session_type="deep_dive")
            _update_task(tid, message='正在分析学习目标，并由 Agent 规划检索与阅读步骤...')
            res = _run_coro(run_learning_agent(
                session, user_msg or topic, verbose=False,
            ))
            _finish_task(tid, dict(
                reply=res, session_id=session.session_id,
                topic=session.topic, msg_count=len(session.messages),
                sources=dict(
                    videos=len(session.metadata.get('searched_videos', [])),
                    web=len(session.metadata.get('web_results', [])),
                    video_contents=len(session.metadata.get('video_contents', [])),
                ),
            ))

        tid = _start_task('Agent 正在处理...', _work)
        return jsonify(dict(ok=True, task_id=tid, message='Agent 已启动'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/deep-dive-multi', methods=['POST'])
def api_action_deep_dive_multi():
    """多Agent协调 — 并行深入了解多个主题。"""
    try:
        body = request.get_json(force=True)
        topics = body.get('topics', [])
        if isinstance(topics, str):
            topics = [t.strip() for t in topics.split(',') if t.strip()]
        if not topics:
            return jsonify(dict(ok=False, message='请提供至少一个主题')), 400

        def _work(tid):
            sys.path.insert(0, str(BASE_DIR))
            from services.learning_agent import run_multi_agent_deep_dive
            res = _run_coro(run_multi_agent_deep_dive(
                topics=topics,
                mode=body.get('mode', 'search'),
                sort_by=body.get('sort_by', 'default'),
                video_count=int(body.get('video_count') or 8),
                additional_context=body.get('context', ''),
                parallel=True, verbose=False,
            ))
            if res.get('success'):
                _finish_task(tid, dict(
                    total=res['total'], success_count=res['success_count'],
                    saved_path=res.get('saved_path', ''),
                    combined_report=res.get('combined_report', '')[:500],
                    topics=topics,
                ))
            else:
                _fail_task(tid, '所有主题探索失败')

        tid = _start_task(f'多Agent正在并行探索 {len(topics)} 个主题...', _work)
        return jsonify(dict(ok=True, task_id=tid, message=f'多Agent已启动 ({len(topics)} 主题)'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/action/quiz-agent', methods=['POST'])
def api_action_quiz_agent():
    """Agent 模式出题 — 多轮对话。"""
    try:
        body = request.get_json(force=True)
        session_id = body.get('session_id', '')
        user_msg = body.get('message', '')
        bvid = body.get('bvid', '')
        kb_file_path = body.get('kb_file_path', '')

        if not session_id:
            if not bvid and not kb_file_path:
                return jsonify(dict(ok=False, message='请提供 BV号 或 知识库文件路径')), 400
            init_msg = body.get('prompt', '')
            if not init_msg:
                init_msg = f"请生成考题：BV{bvid}" if bvid else f"请从知识库文件生成考题：{kb_file_path}"
        else:
            if not user_msg:
                return jsonify(dict(ok=False, message='请输入消息内容')), 400

        def _work(tid):
            sys.path.insert(0, str(BASE_DIR))
            from services.learning_agent import LearningAgentSession, run_learning_agent
            if session_id:
                session = LearningAgentSession.load(session_id)
                if not session:
                    _fail_task(tid, f'会话 {session_id} 不存在')
                    return
            else:
                session = LearningAgentSession(session_type="quiz")
            full_msg = user_msg or init_msg
            # 如果有 BV号，预加载上下文
            if bvid:
                session.metadata["target_bvid"] = bvid
                full_msg = f"BV号: {bvid}\n{full_msg}"
            if kb_file_path:
                session.metadata["target_kb"] = kb_file_path
                full_msg = f"知识库文件: {kb_file_path}\n{full_msg}"
            res = _run_coro(run_learning_agent(
                session, full_msg, verbose=False,
            ))
            _finish_task(tid, dict(
                reply=res, session_id=session.session_id,
                topic=session.topic, msg_count=len(session.messages),
            ))

        tid = _start_task('Agent 正在出题...', _work)
        return jsonify(dict(ok=True, task_id=tid, message='出题Agent已启动'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/learning-agent/sessions')
def api_learning_agent_sessions():
    """列出 Agent 会话。"""
    stype = request.args.get('type', '')
    try:
        from services.learning_agent import LearningAgentSession
        sessions = LearningAgentSession.list_sessions(stype)
        return jsonify(dict(ok=True, sessions=sessions))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500


@app.route('/api/learning-agent/session/<sid>', methods=['GET', 'DELETE'])
def api_learning_agent_session(sid):
    """获取/删除 Agent 会话详情。"""
    try:
        from services.learning_agent import LearningAgentSession
        if request.method == 'DELETE':
            from pathlib import Path as _P
            p = DATA_DIR / 'learning_sessions' / f'{sid}.json'

            if p.exists():
                p.unlink()
                return jsonify(dict(ok=True, deleted=sid))
            return jsonify(dict(ok=False, message='会话不存在')), 404
        session = LearningAgentSession.load(sid)
        if not session:
            return jsonify(dict(ok=False, message='会话不存在')), 404
        # Browser learning chat needs the full locally persisted transcript so
        # users can continue a real session instead of seeing a bare preview.
        return jsonify(dict(ok=True, session=dict(
            session_id=session.session_id,
            session_type=session.session_type,
            topic=session.topic,
            msg_count=len(session.messages),
            created_at=session.created_at,
            updated_at=session.updated_at,
            results=session.results,
            messages=[{
                "role": str(m.get("role", "assistant")),
                "content": str(m.get("content", "")),
            } for m in session.messages[-80:]],
        )))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500


@app.route('/api/action/task')
def api_action_task():
    """轮询长任务状态。"""
    tid = request.args.get('id', '')
    with _TASKS_LOCK:
        task = TASKS.get(tid)
        if not task:
            return jsonify(dict(status='notfound'))
        snapshot = dict(task)
        if snapshot.get('status') == 'running':
            snapshot['elapsed'] = round(_dt.now().timestamp() - snapshot.get('started_at', _dt.now().timestamp()), 3)
        return jsonify(snapshot)


# ── 自定义知识管理 CRUD ──
def _custom_paths():
    return active_knowledge_base_dir() / '自定义知识', USER_DATA_DIR / 'knowledge_metadata.json'


def _custom_init():
    cdir, _ = _custom_paths()
    cdir.mkdir(parents=True, exist_ok=True)
    return cdir


def _custom_sanitize(name):
    return _re.sub(r'[\\/:*?"<>|\n\r]+', '_', name).strip()[:80] or 'untitled'


def _custom_meta():
    _, mpath = _custom_paths()
    if mpath.exists():
        try:
            meta = _json.loads(mpath.read_text(encoding='utf-8'))
        except Exception:
            meta = {}
    else:
        meta = {}
    meta.setdefault('file_index', {})
    meta.setdefault('categories', {})
    meta['file_index'].setdefault('自定义知识', [])
    meta['categories'].setdefault('自定义知识', {})
    return meta, mpath


def _custom_find(bvid, title):
    cdir = _custom_init()
    fn = f"[{bvid}] - {_custom_sanitize(title)}.md"
    fp = cdir / fn
    if not fp.exists():
        for f in cdir.iterdir():
            if f.is_file() and bvid in f.name:
                return f
        return None
    return fp


@app.route('/api/kb/custom-list')
def api_kb_custom_list():
    try:
        cdir = _custom_init()
        meta, _ = _custom_meta()
        out = []
        for e in meta['file_index'].get('自定义知识', []):
            bvid = e.get('bvid', '')
            title = e.get('title', '无标题')
            fp = _custom_find(bvid, title)
            if not fp:
                continue
            out.append(dict(bvid=bvid, title=title, added=e.get('added', ''),
                            category=e.get('category', '自定义知识'),
                            size_kb=round(fp.stat().st_size / 1024, 1)))
        return jsonify(dict(ok=True, entries=out))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/kb/custom-get', methods=['POST'])
def api_kb_custom_get():
    try:
        body = request.get_json(force=True)
        fp = _custom_find(body.get('bvid', ''), body.get('title', ''))
        if not fp:
            return jsonify(dict(ok=False, message='文件不存在')), 404
        return jsonify(dict(ok=True, content=fp.read_text(encoding='utf-8', errors='replace'),
                            filename=fp.name))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/kb/custom-add', methods=['POST'])
def api_kb_custom_add():
    try:
        body = request.get_json(force=True)
        title = (body.get('title') or '').strip()
        content = (body.get('content') or '').strip()
        category = (body.get('category') or '自定义知识').strip() or '自定义知识'
        if not title:
            return jsonify(dict(ok=False, message='标题不能为空')), 400
        if len(content) < 10:
            return jsonify(dict(ok=False, message='内容至少 10 字')), 400
        cdir = _custom_init()
        import hashlib as _hl
        bvid = 'custom_' + _hl.md5(title.encode()).hexdigest()[:8]
        now = _dt.now().isoformat()
        fp = cdir / f"[{bvid}] - {_custom_sanitize(title)}.md"
        full = (f"# 📝 {title}\n\n【信息】\n- 标题: {title}\n- 分类: {category}\n"
                f"- 创建时间: {now}\n\n---\n\n## 内容\n\n{content}\n")
        fp.write_text(full, encoding='utf-8')
        meta, mpath = _custom_meta()
        lst = [x for x in meta['file_index']['自定义知识'] if x.get('bvid') != bvid]
        lst.append(dict(bvid=bvid, title=title, category=category, added=now))
        meta['file_index']['自定义知识'] = lst
        meta['last_updated'] = now
        mpath.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify(dict(ok=True, bvid=bvid, title=title, message='已新增自定义知识'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/kb/custom-update', methods=['POST'])
def api_kb_custom_update():
    try:
        body = request.get_json(force=True)
        bvid = body.get('bvid', '')
        title = (body.get('title') or '').strip()
        content = (body.get('content') or '').strip()
        category = (body.get('category') or '自定义知识').strip() or '自定义知识'
        if not bvid or not title:
            return jsonify(dict(ok=False, message='缺少参数')), 400
        fp = _custom_find(bvid, title)
        if not fp:
            return jsonify(dict(ok=False, message='文件不存在')), 404
        now = _dt.now().isoformat()
        full = (f"# 📝 {title}\n\n【信息】\n- 标题: {title}\n- 分类: {category}\n"
                f"- 更新时间: {now}\n\n---\n\n## 内容\n\n{content}\n")
        fp.write_text(full, encoding='utf-8')
        meta, mpath = _custom_meta()
        lst = [x for x in meta['file_index']['自定义知识'] if x.get('bvid') != bvid]
        lst.append(dict(bvid=bvid, title=title, category=category, added=now))
        meta['file_index']['自定义知识'] = lst
        meta['last_updated'] = now
        mpath.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify(dict(ok=True, message='已更新'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/kb/custom-delete', methods=['POST'])
def api_kb_custom_delete():
    try:
        body = request.get_json(force=True)
        bvid = body.get('bvid', '')
        fp = _custom_find(bvid, body.get('title', ''))
        if fp and fp.exists():
            fp.unlink()
        meta, mpath = _custom_meta()
        meta['file_index']['自定义知识'] = [
            x for x in meta['file_index']['自定义知识'] if x.get('bvid') != bvid]
        meta['last_updated'] = _dt.now().isoformat()
        mpath.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
        return jsonify(dict(ok=True, message='已删除'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/kb/custom-search', methods=['POST'])
def api_kb_custom_search():
    try:
        body = request.get_json(force=True)
        q = (body.get('q') or '').strip().lower()
        if not q:
            return api_kb_custom_list()
        cdir = _custom_init()
        meta, _ = _custom_meta()
        metadata_by_bvid = {
            str(item.get("bvid") or ""): item
            for item in meta.get("file_index", {}).get("自定义知识", [])
            if isinstance(item, dict)
        }
        out = []
        for f in cdir.glob('*.md'):
            txt = f.read_text(encoding='utf-8', errors='replace')
            if q in txt.lower():
                mh = _re.search(r'^#\s+(.*)$', txt, _re.M)
                bv = _re.match(r'^\[([^\]]+)\]', f.name)
                bvid = bv.group(1) if bv else ''
                info = metadata_by_bvid.get(bvid, {})
                out.append(dict(
                    bvid=bvid,
                    filename=f.name,
                    title=info.get("title") or (mh.group(1) if mh else f.stem),
                    category=info.get("category") or "自定义知识",
                    added=info.get("added", ""),
                    size_kb=round(f.stat().st_size / 1024, 1),
                ))
        return jsonify(dict(ok=True, entries=out))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/platform/probe', methods=['POST'])
def api_platform_probe():
    """多平台视频链接识别与归一化。"""
    try:
        body = request.get_json(force=True)
        url = (body.get('url') or body.get('bvid') or '').strip()
        if not url:
            return jsonify(dict(ok=False, message='请输入视频链接 / BV号')), 400
        from services.platform_adapter import fetch_platform_metadata
        cfg = read_json(CONFIG_FILE, {})
        result = fetch_platform_metadata(url, cfg=cfg)
        return jsonify(result), (200 if result.get('ok') else 400)
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/action/send-danmaku', methods=['POST'])
def api_action_send_danmaku():
    """手动发送弹幕 — 桥接到主进程"""
    try:
        body = request.get_json(force=True)
        bvid = (body.get('bvid') or '').strip()
        text = (body.get('text') or '').strip()
        if not bvid or not text:
            return jsonify(dict(ok=False, message='BV号和弹幕内容不能为空')), 400
        if len(text) > 20:
            return jsonify(dict(ok=False, message='弹幕不能超过20字')), 400
        # 写入任务文件让主进程执行
        task_file = DATA_DIR / "web_action_queue.json"
        tasks = read_json(task_file, [])
        tasks.append(dict(type='send_danmaku', bvid=bvid, text=text, time=datetime.now().isoformat()))
        write_json(task_file, tasks)
        log_line(f"弹幕任务已排队: {bvid} -> {text}")
        return jsonify(dict(ok=True, message=f'弹幕"{text}"已加入发送队列'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/action/agent-skill', methods=['POST'])
def api_action_agent_skill():
    """执行 Agent 技能"""
    try:
        body = request.get_json(force=True)
        goal = (body.get('goal') or '').strip()
        if not goal:
            return jsonify(dict(ok=False, message='请输入目标描述')), 400
        task_file = DATA_DIR / "web_action_queue.json"
        tasks = read_json(task_file, [])
        tasks.append(dict(type='agent_skill', goal=goal, time=datetime.now().isoformat()))
        write_json(task_file, tasks)
        log_line(f"Agent技能已排队: {goal}")
        return jsonify(dict(ok=True, message=f'Agent任务已加入队列: {goal}'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/action/kb-organize', methods=['POST'])
def api_action_kb_organize():
    """知识库整理"""
    try:
        task_file = DATA_DIR / "web_action_queue.json"
        tasks = read_json(task_file, [])
        tasks.append(dict(type='kb_organize', time=datetime.now().isoformat()))
        write_json(task_file, tasks)
        log_line("知识库整理任务已排队")
        return jsonify(dict(ok=True, message='知识库整理已加入队列'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/action/kb-revisit', methods=['POST'])
def api_action_kb_revisit():
    """知识库重温"""
    try:
        task_file = DATA_DIR / "web_action_queue.json"
        tasks = read_json(task_file, [])
        tasks.append(dict(type='kb_revisit', time=datetime.now().isoformat()))
        write_json(task_file, tasks)
        log_line("知识库重温任务已排队")
        return jsonify(dict(ok=True, message='知识库重温已加入队列'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

# ── 知识辅导 (v2.0.3) ──
@app.route('/api/kb/list-files')
def api_kb_list_files():
    """列出 KnowledgeBase 下所有 .md 文件"""
    try:
        from services.knowledge_tutor import scan_md_files
        files = scan_md_files(active_knowledge_base_dir())
        metadata = read_json(_watch_history_metadata_path(), {})
        metadata = metadata if isinstance(metadata, dict) else {}
        history_cards = {card["bvid"]: card for card in _watch_history_cards() if card.get("bvid")}
        for item in files:
            bvid = _safe_watch_bvid(item.get("bvid"))
            detail = metadata.get(bvid, {}) if bvid and isinstance(metadata.get(bvid), dict) else {}
            history = history_cards.get(bvid, {})
            # 封面优先顺序：metadata.pic -> history.cover (和观看历史一致)
            cover = detail.get("pic") or history.get("cover") or history.get("pic") or ""
            item["cover"] = str(cover)
            item["duration"] = _watch_history_duration_label(detail.get("duration")) if detail.get("duration") else history.get("duration", "--:--")
            item["score"] = history.get("score", 0)
            item["watched_at"] = history.get("watched_at", "")
            item["video_url"] = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
            item["source"] = history.get("source", "知识库归档")
            item["interest_reason"] = history.get("interest_reason", "")
            item["result"] = history.get("result", "知识库归档")
            item["actions"] = history.get("actions", [])
            item["archived"] = bool(history.get("archived") or bvid)
            item["view_count"] = int(detail.get("view_count") or history.get("view_count") or 0)
            item["like_count"] = int(detail.get("like_count") or history.get("like_count") or 0)
            item["favorite_count"] = int(detail.get("favorite_count") or history.get("favorite_count") or 0)
            item["published_at"] = int(detail.get("published_at") or history.get("published_at") or 0)
        return jsonify(dict(ok=True, files=files, total=len(files)))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/kb/read-file', methods=['POST'])
def api_kb_read_file():
    """读取指定 .md 文件的内容（支持单文件或多文件）"""
    try:
        body = request.get_json(force=True)
        rel_paths = body.get('rel_paths') or body.get('rel_path')
        if isinstance(rel_paths, str):
            rel_paths = [rel_paths]
        if not rel_paths:
            return jsonify(dict(ok=False, message='请提供文件路径')), 400
        from services.knowledge_tutor import read_md_file, scan_md_files
        available_files = {
            str(item.get("rel_path", "")).replace("\\", "/"): Path(item["file_path"])
            for item in scan_md_files(active_knowledge_base_dir())
            if item.get("rel_path") and item.get("file_path")
        }
        parts = []
        total_size = 0
        for rp in rel_paths:
            normalized_path = str(rp or "").strip().replace("\\", "/")
            full_path = available_files.get(normalized_path)
            if full_path is None:
                return jsonify(dict(ok=False, message=f'文件不存在: {rp}')), 404
            c = read_md_file(full_path)
            total_size += len(c)
            fname = os.path.basename(str(full_path))
            parts.append(f'=== {fname} ===\n{c}')
        combined = '\n\n'.join(parts)
        return jsonify(dict(ok=True, content=combined, paths=[str(available_files[str(rp or "").strip().replace("\\", "/")]) for rp in rel_paths], total_size=total_size, file_count=len(rel_paths)))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/kb/delete-file', methods=['POST'])
def api_kb_delete_file():
    """Delete one indexed Markdown note from the active local knowledge base."""
    try:
        body = request.get_json(silent=True) or {}
        if body.get('confirmed') is not True:
            return jsonify(ok=False, message='请先确认删除本地知识笔记'), 400
        rel_path = str(body.get('rel_path') or '').strip().replace('\\', '/')
        if not rel_path:
            return jsonify(ok=False, message='缺少知识文件路径'), 400
        from services.knowledge_tutor import scan_md_files
        indexed = {
            str(item.get('rel_path') or '').replace('\\', '/'): Path(item['file_path'])
            for item in scan_md_files(active_knowledge_base_dir())
            if item.get('rel_path') and item.get('file_path')
        }
        target = indexed.get(rel_path)
        if target is None or target.suffix.lower() != '.md':
            return jsonify(ok=False, message='知识笔记不存在或不允许删除'), 404
        target.unlink()
        log_line(f'[KB] 已删除本地知识笔记: {rel_path}')
        return jsonify(ok=True, message='已删除本地知识笔记', rel_path=rel_path)
    except OSError as exc:
        return jsonify(ok=False, message=f'删除知识笔记失败: {exc}'), 500
    except Exception as exc:
        return jsonify(ok=False, message=str(exc)), 500


@app.route('/api/kb/tutor-chat', methods=['POST'])
def api_kb_tutor_chat():
    """知识辅导：AI 对话（支持单文件或多文件）"""
    try:
        body = request.get_json(force=True)
        rel_paths = body.get('rel_paths') or body.get('rel_path')
        if isinstance(rel_paths, str):
            rel_paths = [rel_paths]
        message = (body.get('message') or '').strip()
        history = body.get('history') or []
        mode = (body.get('mode') or 'chat').strip()  # chat / rewrite / html
        style = (body.get('style') or 'dark').strip()

        if not rel_paths:
            return jsonify(dict(ok=False, message='请提供文件路径')), 400
        if not message and mode == 'chat':
            return jsonify(dict(ok=False, message='请输入问题')), 400

        from services.knowledge_tutor import get_tutor, safe_resolve
        knowledge_base_dir = active_knowledge_base_dir()
        full_paths = []
        for rp in rel_paths:
            fp = safe_resolve(rp.strip(), knowledge_base_dir)
            if fp is None:
                return jsonify(dict(ok=False, message=f'非法路径: {rp}')), 400
            if not fp.exists():
                return jsonify(dict(ok=False, message=f'文件不存在: {rp}')), 404
            full_paths.append(str(fp))

        tutor = get_tutor()
        if not tutor.is_available():
            return jsonify(dict(ok=False, message='AI 接口不可用，请先配置 API Key')), 503

        # 在后台线程中运行异步任务
        import threading
        result = {}
        error = None

        def _run():
            nonlocal result, error
            loop = None
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                if mode == 'rewrite':
                    # rewrite 只支持单文件
                    summary, new_content = loop.run_until_complete(
                        tutor.rewrite_file(full_paths[0], message)
                    )
                    result = dict(mode='rewrite', summary=summary, new_content=new_content)
                elif mode == 'html':
                    # html 支持多文件拼接
                    if len(full_paths) == 1:
                        html = loop.run_until_complete(
                            tutor.generate_html(full_paths[0], style)
                        )
                    else:
                        html = loop.run_until_complete(
                            tutor.generate_html(full_paths, style)
                        )
                    result = dict(mode='html', html=html, style=style)
                else:
                    # chat 支持多文件
                    if len(full_paths) == 1:
                        reply = loop.run_until_complete(
                            tutor.chat_about_file(full_paths[0], message, history)
                        )
                    else:
                        reply = loop.run_until_complete(
                            tutor.chat_about_file(full_paths, message, history)
                        )
                    result = dict(mode='chat', reply=reply)
            except Exception as e:
                error = str(e)
            finally:
                if loop is not None and not loop.is_closed():
                    loop.close()

        t = threading.Thread(target=_run, daemon=True)
        t.start()
        t.join(timeout=180)  # 最多等3分钟

        if error:
            return jsonify(dict(ok=False, message=error)), 500
        return jsonify(dict(ok=True, **result))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/kb/tutor-save', methods=['POST'])
def api_kb_tutor_save():
    """保存改写后的知识文件"""
    try:
        body = request.get_json(force=True)
        rel_path = (body.get('rel_path') or '').strip()
        content = (body.get('content') or '').strip()
        if not rel_path or not content:
            return jsonify(dict(ok=False, message='请提供文件路径和内容')), 400
        from services.knowledge_tutor import write_md_file, safe_resolve
        full_path = safe_resolve(rel_path, active_knowledge_base_dir())
        if full_path is None:
            return jsonify(dict(ok=False, message='非法路径')), 400
        if not full_path.exists():
            return jsonify(dict(ok=False, message='文件不存在')), 404
        success = write_md_file(full_path, content)
        if success:
            return jsonify(dict(ok=True, message='文件已保存（原文件已备份）'))
        else:
            return jsonify(dict(ok=False, message='保存失败')), 500
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

@app.route('/api/kb/tutor-html-save', methods=['POST'])
def api_kb_tutor_html_save():
    """保存生成的 HTML 文件"""
    try:
        body = request.get_json(force=True)
        html = (body.get('html') or '').strip()
        title = (body.get('title') or 'knowledge').strip()
        if not html:
            return jsonify(dict(ok=False, message='HTML内容为空')), 400
        import re as _re
        html_dir = active_knowledge_base_dir() / ".html_exports"
        html_dir.mkdir(parents=True, exist_ok=True)
        safe_title = _re.sub(r'[\\/*?:"<>|]', '_', title)[:40]
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        html_path = html_dir / f"{safe_title}_{ts}.html"
        html_path.write_text(html, encoding='utf-8')
        return jsonify(dict(ok=True, path=str(html_path), message='HTML已保存'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 500

# ── 行为设置 ──
@app.route('/api/behavior/get')
def api_behavior_get():
    config = read_json(CONFIG_FILE, {})
    behavior = config.get('behavior', {})
    energy = config.get('energy', {})
    interaction = config.get('interaction', {})
    return jsonify(dict(
        ai_marker=behavior.get('ai_marker', '（内容由AI生成并由AI回复）'),
        comment_mode=behavior.get('comment_mode', 'real'),
        energy=dict(
            max_energy=interaction.get('max_energy', 100),
            energy_recovery_min=energy.get('energy_recovery_min', 5),
            energy_recovery_max=energy.get('energy_recovery_max', 10),
            rounds_min=energy.get('rounds_min', 3),
            rounds_max=energy.get('rounds_max', 10),
            round_interval_min=energy.get('round_interval_min', 60),
            round_interval_max=energy.get('round_interval_max', 180),
            video_interval_min=energy.get('video_interval_min', 1),
            video_interval_max=energy.get('video_interval_max', 5),
        )
    ))

@app.route('/api/behavior/ai-marker/toggle', methods=['POST'])
def api_behavior_ai_marker_toggle():
    try:
        body = request.get_json(force=True)
        enabled = bool(body.get('enabled', True))
        config = read_json(CONFIG_FILE, {})
        behavior = config.setdefault('behavior', {})
        if enabled:
            behavior['ai_marker'] = body.get('marker') or '（内容由AI生成并由AI回复）'
        else:
            behavior['ai_marker'] = ''
        write_json(CONFIG_FILE, config)
        msg = 'AI免责声明已开启' if enabled else 'AI免责声明已关闭'
        log_line(msg)
        return jsonify(dict(ok=True, message=msg, marker=behavior['ai_marker']))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400

@app.route('/api/behavior/save', methods=['POST'])
def api_behavior_save():
    try:
        body = request.get_json(force=True)
        config = read_json(CONFIG_FILE, {})
        changed = []
        # ai_marker
        if 'ai_marker' in body:
            config.setdefault('behavior', {})['ai_marker'] = str(body['ai_marker'])
            changed.append('AI免责声明')
        # comment_mode
        if 'comment_mode' in body:
            config.setdefault('behavior', {})['comment_mode'] = str(body['comment_mode'])
            changed.append('评论模式')
        # energy settings
        if 'energy' in body:
            eng = body['energy']
            energy = config.setdefault('energy', {})
            interaction = config.setdefault('interaction', {})
            for k in ['energy_recovery_min','energy_recovery_max','rounds_min','rounds_max',
                       'round_interval_min','round_interval_max','video_interval_min','video_interval_max']:
                if k in eng:
                    energy[k] = int(eng[k])
            if 'max_energy' in eng:
                interaction['max_energy'] = int(eng['max_energy'])
            changed.append('精力设置')
        write_json(CONFIG_FILE, config)
        msg = '、'.join(changed) + ' 已保存' if changed else '无变更'
        log_line(msg)
        return jsonify(dict(ok=True, message=msg))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


# ── 安全关键词 ──
@app.route('/api/behavior/safety')
def api_behavior_safety():
    # The raw file intentionally keeps keywords encrypted. Load through the
    # config layer for runtime/plaintext view, but retain raw storage for the
    # panel's read-only encrypted view.
    raw_config = read_json(CONFIG_FILE, {})
    raw_safety = raw_config.get('reply_safety', {}) if isinstance(raw_config, dict) else {}
    try:
        from core.config import load_config
        config = load_config()
    except Exception:
        config = raw_config
    safety = config.get('reply_safety', {}) if isinstance(config, dict) else {}
    return jsonify(dict(
        enabled=safety.get('enabled', True),
        keywords=safety.get('blocked_keywords', []),
        encrypted_keywords=raw_safety.get('blocked_keywords', []),
        storage_encrypted=True,
    ))


@app.route('/api/behavior/safety/toggle', methods=['POST'])
def api_behavior_safety_toggle():
    try:
        body = request.get_json(force=True)
        enabled = bool(body.get('enabled', True))
        from core.config import load_config, save_config
        config = load_config()
        safety = config.setdefault('reply_safety', {})
        safety['enabled'] = enabled
        save_config(config)
        msg = '关键词安全校验已开启' if enabled else '关键词安全校验已关闭'
        return jsonify(dict(ok=True, message=msg))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/behavior/safety/save', methods=['POST'])
def api_behavior_safety_save():
    try:
        body = request.get_json(force=True)
        if body.get('view') == 'encrypted':
            return jsonify(ok=False, message='密文视图仅供查看，请切换到明文后编辑'), 400
        keywords = body.get('keywords', [])
        if not isinstance(keywords, list):
            return jsonify(ok=False, message='关键词格式不正确'), 400
        from core.config import load_config, save_config
        config = load_config()
        safety = config.setdefault('reply_safety', {})
        safety['blocked_keywords'] = [str(k).strip() for k in keywords if str(k).strip()]
        safety.setdefault('enabled', True)
        save_config(config)
        return jsonify(dict(ok=True, message=f'已保存 {len(safety["blocked_keywords"])} 个关键词'))
    except Exception as e:
        return jsonify(dict(ok=False, message=str(e))), 400


@app.route('/api/behavior/safety/political-preset', methods=['POST'])
def api_behavior_safety_political_preset():
    """Replace legacy opaque terms with the editable political-safety preset."""
    try:
        from core.config import (POLITICAL_SAFETY_DEFAULT_KEYWORDS, load_config, save_config)
        config = load_config()
        safety = config.setdefault('reply_safety', {})
        safety['enabled'] = True
        safety['blocked_keywords'] = POLITICAL_SAFETY_DEFAULT_KEYWORDS.copy()
        if not save_config(config):
            return jsonify(ok=False, message='关键词保存失败'), 500
        return jsonify(ok=True, message=f'已应用政治内容安全词库（{len(safety["blocked_keywords"])} 项，可继续编辑）')
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400


@app.route('/api/behavior/prompt-injection', methods=['GET', 'POST'])
def api_prompt_injection():
    try:
        from core.config import load_config, save_config
        config = load_config()
        injection = config.setdefault('prompt_injection', {})
        if request.method == 'GET':
            return jsonify(ok=True, enabled=injection.get('enabled', True),
                           terms=injection.get('custom_terms', []))
        body = request.get_json(force=True) or {}
        enabled = bool(body.get('enabled', True))
        terms = body.get('terms', [])
        if not isinstance(terms, list):
            return jsonify(ok=False, message='防注入关键词格式不正确'), 400
        clean = []
        for term in terms:
            value = str(term).strip()
            if value and value.lower() not in {item.lower() for item in clean}:
                clean.append(value[:80])
        injection['enabled'] = enabled
        injection['custom_terms'] = clean[:100]
        if not save_config(config):
            return jsonify(ok=False, message='防注入设置保存失败'), 500
        return jsonify(ok=True, message=f'防提示词注入已保存（{len(clean)} 个自定义词）',
                       enabled=enabled, terms=clean)
    except Exception as exc:
        return jsonify(ok=False, message=redact_sensitive_text(str(exc))), 400


# ── 免责声明 HTML 页面 ──
def _disclaimer_html():
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<meta name="color-scheme" content="light dark">
<title>免责声明 — B站 AI 管理系统</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#f7f7f7;color:#0d0d0d;display:flex;align-items:center;justify-content:center;min-height:100vh;-webkit-font-smoothing:antialiased}
.card{background:#fff;border:1px solid #e6e6e6;border-radius:16px;padding:40px 36px;max-width:480px;width:90%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.06)}
.card .icon{font-size:36px;margin-bottom:16px}
.card h2{color:#D14343;font-size:20px;font-weight:600;margin-bottom:8px;letter-spacing:-.3px}
.card .sub{font-size:13px;color:#999;margin-bottom:24px}
.card .lines{background:rgba(209,67,67,.04);border:1px solid rgba(209,67,67,.15);border-radius:10px;padding:18px 20px;margin-bottom:24px;font-size:14px;line-height:1.9;text-align:left;font-weight:400}
.card .lines .en{font-size:12px;color:#999;margin-top:8px;display:block}
.inp-row{display:flex;gap:10px}
.inp-row input{flex:1;background:#f7f7f7;border:1px solid #e6e6e6;border-radius:8px;padding:10px 14px;color:#0d0d0d;font-size:15px;outline:none;transition:border-color .2s;font-family:inherit}
.inp-row input:focus{border-color:#D97757;box-shadow:0 0 0 3px rgba(217,119,87,.1)}
.inp-row input.error{border-color:#D14343;animation:shake .4s}
.btn{background:#D14343;color:#fff;border:none;border-radius:8px;padding:10px 24px;font-size:14px;font-weight:500;cursor:pointer;transition:all .2s;font-family:inherit}
.btn:hover{background:#B53535;box-shadow:0 4px 12px rgba(209,67,67,.25)}
.btn:disabled{opacity:.4;cursor:not-allowed}
.msg{margin-top:12px;font-size:13px;min-height:20px;font-weight:500}
.msg.err{color:#D14343}
.msg.ok{color:#2D8A4E}
.recover{font-size:12px;color:#777;margin-top:14px;line-height:1.6}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-6px)}75%{transform:translateX(6px)}}
@media (prefers-color-scheme:dark){
body{background:#111214;color:#f1f2f4}
.card{background:#1a1c1f;border-color:#30343a;box-shadow:0 8px 32px rgba(0,0,0,.35)}
.card h2{color:#ff7b72}
.card .sub,.card .lines .en{color:#9ca3ad}
.card .lines{background:rgba(255,123,114,.07);border-color:rgba(255,123,114,.24)}
.inp-row input{background:#111214;border-color:#3a3f46;color:#f1f2f4}
.inp-row input::placeholder{color:#727984}
.inp-row input:focus{border-color:#ef8f70;box-shadow:0 0 0 3px rgba(239,143,112,.16)}
.btn{background:#d95656}.btn:hover{background:#ea6767}
.msg.err{color:#ff7b72}.msg.ok{color:#63c985}
}
</style>
</head>
<body>
<div class="card">
<div class="icon">⚠</div>
<h2>免责声明 / DISCLAIMER</h2>
<p class="sub">请阅读并确认以下声明</p>
<div class="lines">
本项目仅供学习参考，<br>
若因使用本项目产生任何后果，本人一概不负责。
<span class="en">This project is for learning purposes only.<br>Any consequences are solely your own responsibility.</span>
</div>
<div class="inp-row">
<input id="agreeInput" type="text" placeholder="请输入：我同意" autocomplete="off" autofocus>
<button class="btn" id="confirmBtn" onclick="doConfirm()">确认</button>
</div>
<div class="msg" id="msg"></div>
</div>
<script>
var inp=document.getElementById('agreeInput');
var btn=document.getElementById('confirmBtn');
var msg=document.getElementById('msg');
inp.addEventListener('keydown',function(e){if(e.key==='Enter')doConfirm()});
function doConfirm(){
var v=inp.value.trim();
if(!v){msg.textContent='请输入内容';msg.className='msg err';return}
btn.disabled=true;
fetch('/api/disclaimer/confirm',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({agree:v})})
.then(function(r){return r.json()})
.then(function(d){
if(d.ok){msg.textContent='\u2713 已确认，跳转中...';msg.className='msg ok';var next=new URLSearchParams(location.search).get('next')||'/';setTimeout(function(){location.href=next},600)}
else{msg.textContent='\u2717 请输入"我同意"';msg.className='msg err';btn.disabled=false;inp.classList.add('error');setTimeout(function(){inp.classList.remove('error')},400)}
})
.catch(function(){msg.textContent='请求失败，请重试';msg.className='msg err';btn.disabled=false})
}
</script>
</body>
</html>"""

# ── 首次设置页面（配置用户名和密码）──
def _setup_html():
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>首次设置 · 管理面板</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:#f7f7f7;color:#0d0d0d;display:flex;align-items:center;justify-content:center;min-height:100vh;-webkit-font-smoothing:antialiased}
.card{background:#fff;border:1px solid #e6e6e6;border-radius:16px;padding:40px 36px;max-width:420px;width:90%;text-align:center;box-shadow:0 4px 24px rgba(0,0,0,.06)}
.card .icon{font-size:36px;margin-bottom:16px}
.card h2{color:#0d0d0d;font-size:20px;font-weight:600;margin-bottom:6px;letter-spacing:-.3px}
.card .sub{font-size:13px;color:#999;margin-bottom:28px;line-height:1.6}
.fg{margin-bottom:16px;text-align:left}
.fg label{display:block;font-size:11px;font-weight:600;color:#999;margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
.fg input,.fg select{width:100%;background:#f7f7f7;border:1px solid #e6e6e6;border-radius:8px;padding:10px 14px;color:#0d0d0d;font-size:15px;outline:none;transition:border-color .2s;font-family:inherit}
.fg input:focus,.fg select:focus{border-color:#D97757;box-shadow:0 0 0 3px rgba(217,119,87,.1)}
.fg input.error{border-color:#D14343;animation:shake .4s}
.hint{font-size:11px;color:#999;margin-top:4px}
.btn{background:#D97757;color:#fff;border:none;border-radius:8px;padding:11px 24px;font-size:14px;font-weight:500;cursor:pointer;transition:all .2s;width:100%;margin-top:4px;font-family:inherit}
.btn:hover{background:#C56545;box-shadow:0 4px 12px rgba(217,119,87,.25)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.msg{margin-top:12px;font-size:13px;min-height:20px;font-weight:500}
.msg.err{color:#D14343}
.msg.ok{color:#2D8A4E}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-6px)}75%{transform:translateX(6px)}}
</style>
</head>
<body>
<div class="card">
<div class="icon">🔐</div>
<h2>首次设置</h2>
<p class="sub">欢迎使用 B站 AI 管理系统<br>请设置管理面板的用户名和密码</p>
<div class="fg"><label>用户名</label><input id="setupUser" type="text" placeholder="设置用户名" autocomplete="off" autofocus></div>
<div class="fg"><label>密码</label><input id="setupPass" type="password" placeholder="设置密码（至少4位）" autocomplete="off"></div>
<div class="fg"><label>确认密码</label><input id="setupPass2" type="password" placeholder="再次输入密码" autocomplete="off"></div>
<div class="fg"><label>密保问题（可选）</label><select id="setupQuestion" onchange="toggleCustomQuestion()"><option value="">暂不设置</option><option value="父亲的名字是什么？">父亲名字</option><option value="你的小学名字是什么？">小学名字</option><option value="custom">自定义问题</option></select></div>
<div class="fg" id="customQuestionRow" style="display:none"><label>自定义问题</label><input id="setupCustomQuestion" type="text" placeholder="输入只有你知道答案的问题" autocomplete="off"></div>
<div class="fg"><label>密保答案</label><input id="setupAnswer" type="password" placeholder="设置密保答案" autocomplete="off"></div>
<button class="btn" id="setupBtn" onclick="doSetup()">完成设置</button>
<div class="msg" id="msg"></div>
</div>
<script>
var inpU=document.getElementById('setupUser'),inpP=document.getElementById('setupPass'),inpP2=document.getElementById('setupPass2');
var btn=document.getElementById('setupBtn'),msg=document.getElementById('msg');
function toggleCustomQuestion(){document.getElementById('customQuestionRow').style.display=document.getElementById('setupQuestion').value==='custom'?'block':'none'}
[inpU,inpP,inpP2].forEach(function(el){el.addEventListener('keydown',function(e){if(e.key==='Enter')doSetup()})});
async function doSetup(){
var u=inpU.value.trim(),p=inpP.value,p2=inpP2.value;
var q=document.getElementById('setupQuestion').value,a=document.getElementById('setupAnswer').value;
if(q==='custom')q=document.getElementById('setupCustomQuestion').value.trim();
if(!u){msg.textContent='请输入用户名';msg.className='msg err';inpU.classList.add('error');setTimeout(function(){inpU.classList.remove('error')},400);return}
if(u.length<2){msg.textContent='用户名至少2个字符';msg.className='msg err';return}
if(p.length<4){msg.textContent='密码至少4位';msg.className='msg err';inpP.classList.add('error');setTimeout(function(){inpP.classList.remove('error')},400);return}
if(p!==p2){msg.textContent='两次输入的密码不一致';msg.className='msg err';inpP2.classList.add('error');setTimeout(function(){inpP2.classList.remove('error')},400);return}
if((q&&!a)||(!q&&a)){msg.textContent='密保问题和答案需要同时填写';msg.className='msg err';return}
btn.disabled=true;btn.textContent='正在保存...';
try{
var r=await fetch('/api/auth/setup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p,recovery_question:q,recovery_answer:a})});
var d=await r.json();
if(d.ok){msg.textContent='\u2713 设置成功！正在跳转...';msg.className='msg ok';setTimeout(function(){location.href='/login'},800)}
else{msg.textContent='\u2717 '+d.message;msg.className='msg err';btn.disabled=false;btn.textContent='完成设置'}
}catch(e){msg.textContent='请求失败，请重试';msg.className='msg err';btn.disabled=false;btn.textContent='完成设置'}
}
</script>
</body>
</html>"""

# ── 登录页面 ──
def _login_html():
    return r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0,maximum-scale=1.0,user-scalable=no">
<title>登录 · 管理面板</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
:root{color-scheme:light;--bg:#f7f7f7;--surface:#fff;--text:#0d0d0d;--muted:#777;--faint:#999;--border:#e6e6e6;--input:#f7f7f7;--shadow:0 4px 24px rgba(0,0,0,.06)}
:root[data-theme="dark"]{color-scheme:dark;--bg:#0d0d0d;--surface:#161616;--text:#f5f5f5;--muted:#a3a3a3;--faint:#8a8a8a;--border:#303030;--input:#101010;--shadow:0 20px 60px rgba(0,0,0,.42)}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Microsoft YaHei',sans-serif;background:var(--bg);color:var(--text);display:flex;align-items:center;justify-content:center;min-height:100vh;-webkit-font-smoothing:antialiased;transition:background .25s,color .25s}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:40px 36px;max-width:400px;width:90%;text-align:center;box-shadow:var(--shadow)}
.card .icon{font-size:36px;margin-bottom:16px}
.card h2{color:var(--text);font-size:20px;font-weight:600;margin-bottom:6px;letter-spacing:0}
.card .sub{font-size:13px;color:var(--faint);margin-bottom:28px}
.fg{margin-bottom:16px;text-align:left}
.fg label{display:block;font-size:11px;font-weight:600;color:var(--faint);margin-bottom:5px;text-transform:uppercase;letter-spacing:.4px}
.fg input{width:100%;background:var(--input);border:1px solid var(--border);border-radius:8px;padding:10px 14px;color:var(--text);font-size:15px;outline:none;transition:border-color .2s;font-family:inherit}
.fg input:focus{border-color:#D97757;box-shadow:0 0 0 3px rgba(217,119,87,.1)}
.fg input.error{border-color:#D14343;animation:shake .4s}
.btn{background:#D97757;color:#fff;border:none;border-radius:8px;padding:11px 24px;font-size:14px;font-weight:500;cursor:pointer;transition:all .2s;width:100%;margin-top:4px;font-family:inherit}
.btn:hover{background:#C56545;box-shadow:0 4px 12px rgba(217,119,87,.25)}
.btn:disabled{opacity:.5;cursor:not-allowed}
.msg{margin-top:12px;font-size:13px;min-height:20px;font-weight:500}
.msg.err{color:#D14343}
.msg.ok{color:#2D8A4E}
.recover{font-size:12px;color:var(--muted);margin-top:14px;line-height:1.7}
.recover a{color:#C56545;text-decoration:none}
.theme-btn{position:fixed;right:18px;top:18px;width:38px;height:38px;border-radius:8px;border:1px solid var(--border);background:var(--surface);color:var(--text);font-size:17px;cursor:pointer}
@keyframes shake{0%,100%{transform:translateX(0)}25%{transform:translateX(-6px)}75%{transform:translateX(6px)}}
</style>
</head>
<body>
<button class="theme-btn" type="button" onclick="toggleTheme()" id="themeBtn" aria-label="切换暗色模式">◐</button><div class="card">
<div class="icon">⚡</div>
<h2>管理面板登录</h2>
<p class="sub">B站 AI 管理系统</p>
<div class="fg"><label>用户名</label><input id="loginUser" type="text" placeholder="输入用户名" autocomplete="off" autofocus></div>
<div class="fg"><label>密码</label><input id="loginPass" type="password" placeholder="输入密码" autocomplete="off"></div>
<button class="btn" id="loginBtn" onclick="doLogin()">登录</button>
<div class="msg" id="msg"></div>
<div class="recover"><a href="/forgot-password">忘记密码</a></div>
</div>
<script>
var inpU=document.getElementById('loginUser'),inpP=document.getElementById('loginPass');
var btn=document.getElementById('loginBtn'),msg=document.getElementById('msg');
function applyTheme(){var t='light';try{t=localStorage.getItem('panel_theme')||'light'}catch(e){}document.documentElement.setAttribute('data-theme',t);document.getElementById('themeBtn').textContent=t==='dark'?'☀':'◐'}
function toggleTheme(){var t=document.documentElement.getAttribute('data-theme')==='dark'?'light':'dark';try{localStorage.setItem('panel_theme',t)}catch(e){}applyTheme()}
applyTheme();
[inpU,inpP].forEach(function(el){el.addEventListener('keydown',function(e){if(e.key==='Enter')doLogin()})});
async function doLogin(){
var u=inpU.value.trim(),p=inpP.value;
if(!u||!p){msg.textContent='请输入用户名和密码';msg.className='msg err';return}
btn.disabled=true;btn.textContent='验证中...';
try{
var r=await fetch('/api/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u,password:p})});
var d=await r.json();
if(d.ok){msg.textContent='\u2713 登录成功，跳转中...';msg.className='msg ok';var next=new URLSearchParams(location.search).get('next')||'/';setTimeout(function(){location.href=(d.recovery&&!d.security_question_configured)?'/account-security':next},500)}
else{msg.textContent='\u2717 '+d.message;msg.className='msg err';btn.disabled=false;btn.textContent='登录';inpP.value='';inpP.classList.add('error');setTimeout(function(){inpP.classList.remove('error')},400)}
}catch(e){msg.textContent='请求失败，请重试';msg.className='msg err';btn.disabled=false;btn.textContent='登录'}
}
</script>
</body>
</html>"""


def _forgot_password_html():
    return r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>忘记密码 · 管理面板</title><style>
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;background:#f7f7f7;color:#111;display:flex;align-items:center;justify-content:center;min-height:100vh}.card{background:#fff;border:1px solid #e6e6e6;border-radius:8px;padding:32px;max-width:420px;width:92%;box-shadow:0 4px 24px rgba(0,0,0,.06)}h2{font-size:20px;margin:0 0 24px}.fg{margin-bottom:15px}.fg label{display:block;font-size:12px;color:#777;margin-bottom:6px}.fg input{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:6px;font-size:15px}.question{padding:11px 12px;background:#f3f3f3;border-radius:6px;margin-bottom:15px}.btn{width:100%;padding:11px;border:0;border-radius:6px;background:#D97757;color:#fff;font-size:14px;cursor:pointer}.msg{font-size:13px;min-height:20px;margin-top:12px}.err{color:#b42318}.ok{color:#267a45}.back{display:block;text-align:center;margin-top:16px;color:#666;text-decoration:none;font-size:13px}
</style></head><body><div class="card"><h2>找回网页端密码</h2>
<div id="lookup"><div class="fg"><label>用户名</label><input id="username" autocomplete="username"></div><button class="btn" onclick="loadQuestion()">下一步</button></div>
<div id="reset" style="display:none"><div class="question" id="question"></div><div class="fg"><label>密保答案</label><input id="answer" type="password" autocomplete="off"></div><div class="fg"><label>新密码</label><input id="password" type="password" autocomplete="new-password"></div><div class="fg"><label>确认新密码</label><input id="password2" type="password" autocomplete="new-password"></div><button class="btn" onclick="resetPassword()">重置密码</button></div>
<div class="msg" id="msg"></div><a class="back" href="/login">返回登录</a></div><script>
var msg=document.getElementById('msg');
async function loadQuestion(){var u=document.getElementById('username').value.trim();if(!u){msg.textContent='请输入用户名';msg.className='msg err';return}var r=await fetch('/api/auth/recovery-question',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:u})});var d=await r.json();if(!d.ok){msg.textContent=d.message;msg.className='msg err';return}document.getElementById('question').textContent=d.question;document.getElementById('lookup').style.display='none';document.getElementById('reset').style.display='block';msg.textContent=''}
async function resetPassword(){var p=document.getElementById('password').value,p2=document.getElementById('password2').value;if(p.length<4){msg.textContent='新密码至少4位';msg.className='msg err';return}if(p!==p2){msg.textContent='两次输入的密码不一致';msg.className='msg err';return}var r=await fetch('/api/auth/reset-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:document.getElementById('username').value.trim(),answer:document.getElementById('answer').value,password:p})});var d=await r.json();msg.textContent=d.message;msg.className='msg '+(d.ok?'ok':'err');if(d.ok)setTimeout(function(){location.href='/'},800)}
</script></body></html>"""


def _account_security_html():
    return r"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>账号安全 · 管理面板</title><style>
*{box-sizing:border-box}body{margin:0;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',sans-serif;background:#f7f7f7;color:#111;display:flex;align-items:center;justify-content:center;min-height:100vh}.card{background:#fff;border:1px solid #e6e6e6;border-radius:8px;padding:32px;max-width:420px;width:92%;box-shadow:0 4px 24px rgba(0,0,0,.06)}h2{font-size:20px;margin:0 0 24px}.fg{margin-bottom:15px}.fg label{display:block;font-size:12px;color:#777;margin-bottom:6px}.fg input,.fg select{width:100%;padding:10px 12px;border:1px solid #ddd;border-radius:6px;font-size:15px;background:#fff}.btn{width:100%;padding:11px;border:0;border-radius:6px;background:#D97757;color:#fff;font-size:14px;cursor:pointer}.msg{font-size:13px;min-height:20px;margin-top:12px}.err{color:#b42318}.ok{color:#267a45}.back{display:block;text-align:center;margin-top:16px;color:#666;text-decoration:none;font-size:13px}
</style></head><body><div class="card"><h2>设置密保问题</h2><div class="fg"><label>问题</label><select id="preset" onchange="toggleCustom()"><option value="父亲的名字是什么？">父亲名字</option><option value="你的小学名字是什么？">小学名字</option><option value="custom">自定义问题</option></select></div><div class="fg" id="customRow" style="display:none"><label>自定义问题</label><input id="custom" autocomplete="off"></div><div class="fg"><label>答案</label><input id="answer" type="password" autocomplete="off"></div><button class="btn" onclick="saveQuestion()">保存密保问题</button><div class="msg" id="msg"></div><a class="back" href="/">返回管理面板</a></div><script>
function toggleCustom(){document.getElementById('customRow').style.display=document.getElementById('preset').value==='custom'?'block':'none'}async function saveQuestion(){var q=document.getElementById('preset').value;if(q==='custom')q=document.getElementById('custom').value.trim();var a=document.getElementById('answer').value,m=document.getElementById('msg');if(q.length<2||!a.trim()){m.textContent='请完整填写问题和答案';m.className='msg err';return}var r=await fetch('/api/auth/security-question',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question:q,answer:a})});var d=await r.json();m.textContent=d.message;m.className='msg '+(d.ok?'ok':'err');if(d.ok)setTimeout(function(){location.href='/'},700)}
</script></body></html>"""

# ── 免责声明确认页（Web端）──
@app.route('/disclaimer')
def disclaimer_page():
    return _disclaimer_html(), 200, {'Content-Type': 'text/html; charset=utf-8'}

@app.route('/api/disclaimer/confirm', methods=['POST'])
def api_disclaimer_confirm():
    data = request.get_json(force=True) if request.is_json else {}
    if data.get('agree') == '我同意':
        session['disclaimer_agreed'] = True
        return jsonify(dict(ok=True))
    return jsonify(dict(ok=False, message='请手动输入 我同意'))

# ── 首次设置页面 ──
@app.route('/setup')
def setup_page():
    return _setup_html(), 200, {'Content-Type': 'text/html; charset=utf-8'}

# ── 登录页面 ──
@app.route('/login')
def login_page():
    return _login_html(), 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/forgot-password')
def forgot_password_page():
    return _forgot_password_html(), 200, {'Content-Type': 'text/html; charset=utf-8'}


@app.route('/account-security')
def account_security_page():
    return _account_security_html(), 200, {'Content-Type': 'text/html; charset=utf-8'}

# ── 认证 API ──
_PASSWORD_RESET_ATTEMPTS = {}
_PASSWORD_RESET_LOCK = threading.Lock()


def _password_reset_rate_limited(client_key: str) -> bool:
    now = time.time()
    with _PASSWORD_RESET_LOCK:
        recent = [stamp for stamp in _PASSWORD_RESET_ATTEMPTS.get(client_key, []) if now - stamp < 600]
        if len(recent) >= 5:
            _PASSWORD_RESET_ATTEMPTS[client_key] = recent
            return True
        recent.append(now)
        _PASSWORD_RESET_ATTEMPTS[client_key] = recent
        return False


@app.route('/api/auth/setup', methods=['POST'])
def api_auth_setup():
    """首次设置：保存用户名和密码到 config.json"""
    data = request.get_json(force=True) if request.is_json else {}
    username = (data.get('username') or '').strip()
    password = (data.get('password') or '')
    recovery_question = (data.get('recovery_question') or '').strip()
    recovery_answer = _normalize_security_answer(data.get('recovery_answer') or '')
    if len(username) < 2:
        return jsonify(dict(ok=False, message='用户名至少2个字符'))
    if len(password) < 4:
        return jsonify(dict(ok=False, message='密码至少4位'))
    if bool(recovery_question) != bool(recovery_answer):
        return jsonify(dict(ok=False, message='密保问题和答案需要同时填写'))
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.setdefault('web', {})
    web_cfg['username'] = username
    web_cfg['password'] = _hash_password(password)
    web_cfg['onboarding_state'] = 'pending'
    if recovery_question and recovery_answer:
        web_cfg['recovery_question'] = recovery_question
        web_cfg['recovery_answer'] = _hash_password(recovery_answer)
    recovery_code = _new_recovery_code()
    web_cfg['recovery_code'] = _hash_password(recovery_code)
    if write_json(CONFIG_FILE, config):
        if not _write_recovery_file(username, recovery_code):
            return jsonify(dict(ok=False, message='账号已保存，但恢复文件创建失败，请检查数据目录权限'))
        # 设置成功后自动登录
        session['disclaimer_agreed'] = True
        session['panel_authenticated'] = True
        log_line(f"面板首次设置完成，用户: {username}")
        return jsonify(dict(ok=True, message='设置成功'))
    return jsonify(dict(ok=False, message='保存配置失败'))

@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    """登录验证"""
    data = request.get_json(force=True) if request.is_json else {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.get('web', {})
    saved_user = web_cfg.get('username', '')
    saved_pass = web_cfg.get('password', '')
    if not saved_user or not saved_pass:
        return jsonify(dict(ok=False, message='面板尚未设置，请先完成首次配置'))
    password_ok = username == saved_user and _verify_password(password, saved_pass)
    recovery_hash = web_cfg.get('recovery_code', '')
    recovery_ok = username == saved_user and bool(recovery_hash) and _verify_password(password, recovery_hash)
    if password_ok or recovery_ok:
        session['panel_authenticated'] = True
        if recovery_ok:
            rotated = _rotate_recovery_code(config, saved_user)
            log_line(f"面板使用一次性恢复码登录，用户: {username}")
            message = '恢复登录成功，恢复码已更新' if rotated else '恢复登录成功，但恢复码更新失败'
            return jsonify(dict(
                ok=True,
                message=message,
                recovery=True,
                security_question_configured=bool(web_cfg.get('recovery_question') and web_cfg.get('recovery_answer')),
            ))
        log_line(f"面板登录成功，用户: {username}")
        return jsonify(dict(
            ok=True,
            message='登录成功',
            recovery=False,
            security_question_configured=bool(web_cfg.get('recovery_question') and web_cfg.get('recovery_answer')),
        ))
    import time as _time
    _time.sleep(0.8)
    return jsonify(dict(ok=False, message='用户名或密码错误'))


@app.route('/api/auth/recovery-question', methods=['POST'])
def api_auth_recovery_question():
    data = request.get_json(force=True) if request.is_json else {}
    username = (data.get('username') or '').strip()
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.get('web', {})
    question = web_cfg.get('recovery_question', '')
    if username != web_cfg.get('username') or not question or not web_cfg.get('recovery_answer'):
        time.sleep(0.5)
        return jsonify(dict(ok=False, message='账号不存在或尚未设置密保问题'))
    return jsonify(dict(ok=True, question=question))


@app.route('/api/auth/reset-password', methods=['POST'])
def api_auth_reset_password():
    client_key = request.remote_addr or 'local'
    if _password_reset_rate_limited(client_key):
        return jsonify(dict(ok=False, message='尝试次数过多，请10分钟后再试')), 429
    data = request.get_json(force=True) if request.is_json else {}
    username = (data.get('username') or '').strip()
    answer = _normalize_security_answer(data.get('answer') or '')
    password = data.get('password') or ''
    if len(password) < 4:
        return jsonify(dict(ok=False, message='新密码至少4位'))
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.get('web', {})
    answer_hash = web_cfg.get('recovery_answer', '')
    if username != web_cfg.get('username') or not answer_hash or not _verify_password(answer, answer_hash):
        time.sleep(0.8)
        return jsonify(dict(ok=False, message='用户名或密保答案错误'))
    web_cfg['password'] = _hash_password(password)
    rotated = _rotate_recovery_code(config, username)
    session['disclaimer_agreed'] = True
    session['panel_authenticated'] = True
    with _PASSWORD_RESET_LOCK:
        _PASSWORD_RESET_ATTEMPTS.pop(client_key, None)
    log_line(f"面板密码通过密保问题重置，用户: {username}")
    message = '密码已重置' if rotated else '密码已重置，但本地恢复码更新失败'
    return jsonify(dict(ok=True, message=message))


@app.route('/api/auth/security-question', methods=['POST'])
def api_auth_security_question():
    if not session.get('panel_authenticated'):
        return jsonify(dict(ok=False, message='请先登录')), 401
    data = request.get_json(force=True) if request.is_json else {}
    question = (data.get('question') or '').strip()
    answer = _normalize_security_answer(data.get('answer') or '')
    if len(question) < 2 or not answer:
        return jsonify(dict(ok=False, message='请完整填写问题和答案'))
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.setdefault('web', {})
    web_cfg['recovery_question'] = question
    web_cfg['recovery_answer'] = _hash_password(answer)
    if not write_json(CONFIG_FILE, config):
        return jsonify(dict(ok=False, message='密保问题保存失败'))
    log_line(f"面板密保问题已更新，用户: {web_cfg.get('username', '')}")
    return jsonify(dict(ok=True, message='密保问题已保存'))

@app.route('/api/auth/logout', methods=['POST'])
def api_auth_logout():
    """退出登录"""
    session.pop('panel_authenticated', None)
    session.pop('disclaimer_agreed', None)
    return jsonify(dict(ok=True, message='已退出登录'))

@app.route('/api/auth/status')
def api_auth_status():
    """检查登录状态"""
    return jsonify(dict(authenticated=bool(session.get('panel_authenticated'))))

# ── 健康检查与部署状态（免登录，供 Docker / 监控探针使用）──
_START_TIME = time.time()

@app.route('/api/health')
def api_health():
    """Docker HEALTHCHECK / 监控探针：返回基本健康信息。"""
    try:
        psutil_available = False
        mem_info = {}
        try:
            import psutil
            psutil_available = True
            proc = psutil.Process()
            mem_info = {
                'rss_mb': round(proc.memory_info().rss / 1024 / 1024, 2),
                'cpu_percent': proc.cpu_percent(interval=0.1),
            }
        except Exception:
            pass

        _cfg = read_json(CONFIG_FILE, {})
        ai_configured = bool(
            os.getenv('BILI_AI_API_KEY') or
            _cfg.get('api', {}).get('unified_api_key', '')
        )

        return jsonify({
            'ok': True,
            'service': WEB_SERVICE_ID,
            'status': 'ok',
            'version': APP_VERSION,
            'uptime_seconds': round(time.time() - _START_TIME, 1),
            'memory': mem_info,
            'psutil_available': psutil_available,
            'ai_configured': ai_configured,
            'timestamp': datetime.now().isoformat(),
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


def _system_metrics_snapshot():
    config = read_json(CONFIG_FILE, {})
    api = config.get('asr', {}) if isinstance(config, dict) else {}
    cpu_percent = 0.0
    memory_used_gb = 0.0
    memory_total_gb = 0.0
    memory_percent = 0.0
    disk_used_gb = 0.0
    disk_total_gb = 0.0
    disk_percent = 0.0
    try:
        import psutil
        cpu_percent = round(float(psutil.cpu_percent(interval=0.05)), 1)
        memory = psutil.virtual_memory()
        memory_used_gb = round(memory.used / 1024 ** 3, 2)
        memory_total_gb = round(memory.total / 1024 ** 3, 2)
        memory_percent = round(float(memory.percent), 1)
        drive = os.path.splitdrive(str(DATA_DIR.resolve()))[0] + os.sep
        disk = psutil.disk_usage(drive)
        disk_used_gb = round(disk.used / 1024 ** 3, 2)
        disk_total_gb = round(disk.total / 1024 ** 3, 2)
        disk_percent = round(float(disk.percent), 1)
    except Exception:
        pass
    return {
        'time': datetime.now().strftime('%H:%M:%S'),
        'cpu_percent': cpu_percent,
        'memory_percent': memory_percent,
        'memory_used_gb': memory_used_gb,
        'memory_total_gb': memory_total_gb,
        'disk_percent': disk_percent,
        'disk_used_gb': disk_used_gb,
        'disk_total_gb': disk_total_gb,
        'asr_enabled': bool(api.get('enabled', False)),
        'asr_backend': str(api.get('backend', 'funasr') or 'funasr'),
        'uptime_seconds': max(0, int((datetime.now() - panel_start).total_seconds())),
    }


@app.route('/api/system/metrics')
def api_system_metrics():
    snapshot = _system_metrics_snapshot()
    with system_metrics_lock:
        system_metrics_history.append(snapshot)
        history = list(system_metrics_history)
    return jsonify(ok=True, current=snapshot, history=history)

@app.route('/deploy_status')
def deploy_status():
    """部署状态详情（免登录）：版本、配置、模块可用性。"""
    _cfg = read_json(CONFIG_FILE, {})
    status = {
        'version': APP_VERSION,
        'uptime_seconds': round(time.time() - _START_TIME, 1),
        'python_version': sys.version,
        'checks': {},
    }

    # AI 配置检查
    ai_cfg = _cfg.get('api', {})
    status['checks']['ai'] = {
        'configured': bool(ai_cfg.get('unified_api_key') or os.getenv('BILI_AI_API_KEY')),
        'base_url': ai_cfg.get('unified_base_url', '') or os.getenv('BILI_AI_BASE_URL', ''),
        'model': ai_cfg.get('model_brain', '') or os.getenv('BILI_AI_MODEL_BRAIN', ''),
    }

    # B站 Cookie 检查
    cookie_exists = os.path.exists(COOKIE_FILE) if COOKIE_FILE else False
    status['checks']['bilibili'] = {
        'cookie_file_exists': cookie_exists,
        'logged_in': _has_valid_bili_cookies(),
    }

    # ASR 依赖检查
    import importlib.util as _iu
    asr_status = {'ffmpeg': False, 'funasr': False, 'whisper': False}
    try:
        import shutil
        asr_status['ffmpeg'] = shutil.which('ffmpeg') is not None
    except Exception:
        pass
    try:
        asr_status['funasr'] = _iu.find_spec('funasr') is not None
    except Exception:
        pass
    try:
        asr_status['whisper'] = _iu.find_spec('faster_whisper') is not None or _iu.find_spec('whisper') is not None
    except Exception:
        pass
    status['checks']['asr'] = asr_status

    # 知识库
    kb_dir = active_knowledge_base_dir()
    md_count = 0
    if kb_dir.exists():
        try:
            md_count = sum(1 for _ in kb_dir.rglob('*.md'))
        except Exception:
            pass
    status['checks']['knowledge_base'] = {
        'exists': kb_dir.exists(),
        'md_files': md_count,
    }

    return jsonify(status)

# ── ASR 状态面板 API ──
_asr_download_job = {
    'state': 'idle', 'phase': 'idle', 'message': '尚未开始',
    'started_at': None, 'finished_at': None, 'initial_files': 0,
    'initial_bytes': 0, 'model_dir': '',
}
_asr_download_lock = threading.Lock()


def _asr_model_dir(asr_cfg: dict) -> Path:
    configured = str(asr_cfg.get('funasr_model_dir', '') or '').strip()
    if configured:
        candidate = Path(configured).expanduser()
        return candidate if candidate.is_absolute() else BASE_DIR / candidate
    # Frozen application payloads are read-only on many machines. Keep
    # downloadable ASR models in the current user's writable data directory.
    return (Path(USER_DATA_DIR) / 'models' / 'asr') if getattr(sys, 'frozen', False) else BASE_DIR / 'model' / 'asr'


def _asr_disk_usage(path: Path) -> tuple[int, int]:
    if not path.exists():
        return 0, 0
    count = total = 0
    try:
        for item in path.rglob('*'):
            if item.is_file() and not item.is_symlink():
                try:
                    count += 1
                    total += item.stat().st_size
                except OSError:
                    pass
    except OSError:
        pass
    return count, total


def _asr_status_payload() -> dict:
    import importlib.util as _iu
    import shutil
    cfg = read_json(CONFIG_FILE, {})
    asr_cfg = cfg.get('asr', {}) if isinstance(cfg.get('asr'), dict) else {}
    model_dir = _asr_model_dir(asr_cfg)
    files, bytes_ = _asr_disk_usage(model_dir)
    job = dict(_asr_download_job)
    if job.get('started_at') and job.get('state') == 'running':
        job['elapsed_seconds'] = max(0, time.time() - job['started_at'])
    elif job.get('started_at') and job.get('finished_at'):
        job['elapsed_seconds'] = max(0, job['finished_at'] - job['started_at'])
    if job.get('started_at'):
        job['downloaded_files'] = max(0, files - int(job.get('initial_files') or 0))
        job['downloaded_bytes'] = max(0, bytes_ - int(job.get('initial_bytes') or 0))
    return {
        'enabled': bool(asr_cfg.get('enabled', False)), 'backend': asr_cfg.get('backend', 'funasr'),
        'configured': bool(asr_cfg.get('enabled', False)), 'model_dir': str(model_dir),
        'model_files': files, 'model_bytes': bytes_, 'job': job,
        'dependencies': {
            'ffmpeg': bool(asr_cfg.get('ffmpeg_path')) or shutil.which('ffmpeg') is not None,
            'funasr': _iu.find_spec('funasr') is not None,
            'faster_whisper': _iu.find_spec('faster_whisper') is not None,
            'whisper': _iu.find_spec('whisper') is not None,
            'torch': _iu.find_spec('torch') is not None,
            'torchaudio': _iu.find_spec('torchaudio') is not None,
        },
        'config': {
            'whisper_model': asr_cfg.get('whisper_model', 'base'),
            'speaker_separation': asr_cfg.get('speaker_separation', True),
            'funasr_vad': asr_cfg.get('funasr_vad_enabled', True),
            'funasr_punc': asr_cfg.get('funasr_punc_enabled', True), 'device': asr_cfg.get('device', 'cpu'),
        },
    }


@app.route('/api/asr/status')
def api_asr_status():
    """ASR 引擎状态：模型加载、ffmpeg 可用性、配置信息。"""
    status = _asr_status_payload()

    # 尝试检测 ASR 引擎实例状态
    try:
        from xingye_bot.asr_engine import get_asr_engine
        engine = get_asr_engine()
        status['engine_loaded'] = engine is not None
        if engine:
            status['engine_model'] = getattr(engine, 'model', None) is not None
    except Exception:
        status['engine_loaded'] = False

    return jsonify(status)


@app.route('/api/asr/download', methods=['POST'])
def api_asr_download():
    """Start a real model load/download task. The UI polls status for facts."""
    cfg = read_json(CONFIG_FILE, {})
    asr_cfg = cfg.get('asr', {}) if isinstance(cfg.get('asr'), dict) else {}
    backend = str(asr_cfg.get('backend', 'funasr')).lower()
    try:
        import importlib.util as _import_util
        installed = (
            _import_util.find_spec('funasr') is not None
            if backend == 'funasr'
            else _import_util.find_spec('whisper') is not None
        )
    except (ImportError, ModuleNotFoundError, ValueError):
        installed = False
    if not installed:
        return jsonify(
            ok=False,
            message=f'ASR runtime for {backend} is not included in this release; model download was not started.',
            status=_asr_status_payload(),
        ), 409
    if not _asr_download_lock.acquire(blocking=False):
        return jsonify(ok=False, message='已有 ASR 下载或加载任务正在运行', status=_asr_status_payload()), 409

    def worker():
        global _asr_download_job
        try:
            cfg = read_json(CONFIG_FILE, {})
            asr_cfg = dict(cfg.get('asr', {}) if isinstance(cfg.get('asr'), dict) else {})
            model_dir = _asr_model_dir(asr_cfg)
            model_dir.mkdir(parents=True, exist_ok=True)
            backend = str(asr_cfg.get('backend', 'funasr')).lower()
            before_files, before_bytes = _asr_disk_usage(model_dir)
            _asr_download_job = {
                'state': 'running', 'phase': 'preparing',
                'message': f'正在准备 {backend} 模型下载', 'started_at': time.time(),
                'finished_at': None, 'initial_files': before_files,
                'initial_bytes': before_bytes, 'model_dir': str(model_dir),
            }
            log_line(f'[ASR] 开始下载或加载 {backend} 模型，目录: {model_dir}')
            if backend == 'funasr':
                from xingye_bot.asr_engine import ASREngine
                asr_cfg['enabled'] = True
                asr_cfg['funasr_model_dir'] = str(model_dir)
                cfg.setdefault('asr', {}).update(asr_cfg)
                if not write_json(CONFIG_FILE, cfg):
                    raise RuntimeError('Unable to save the ASR model path')
                _asr_download_job.update(phase='downloading', message='FunASR 正在下载或读取模型文件')
                ASREngine(asr_cfg)._load_funasr_model()
            elif backend == 'whisper':
                import whisper
                _asr_download_job.update(phase='downloading', message='Whisper 正在下载或读取模型文件')
                whisper.load_model(asr_cfg.get('whisper_model', 'base'),
                                   device=asr_cfg.get('device', 'cpu'), download_root=str(model_dir))
            else:
                raise ValueError(f'不支持的 ASR 后端: {backend}')
            files, bytes_ = _asr_disk_usage(model_dir)
            weight_names = {'model.pt', 'pytorch_model.bin'}
            has_weight = any(
                item.is_file() and (item.name in weight_names or item.suffix == '.safetensors')
                for item in model_dir.rglob('*')
            )
            if not has_weight:
                raise RuntimeError('模型加载结束，但未在模型目录发现可用权重文件')
            _asr_download_job.update(
                state='success', phase='completed', message='模型已下载并加载完成',
                finished_at=time.time(), completed_files=files, completed_bytes=bytes_,
            )
            log_line(f'[ASR] 模型下载/加载完成: {model_dir}')
        except Exception as exc:
            _asr_download_job.update(
                state='failed', phase='failed', message=redact_sensitive_text(str(exc))[:500],
                finished_at=time.time(),
            )
            log_line(f'[ASR] 模型下载/加载失败: {redact_sensitive_text(str(exc))}')
        finally:
            _asr_download_lock.release()

    threading.Thread(target=worker, daemon=True).start()
    return jsonify(ok=True, message='已开始真实的模型下载或加载任务', status=_asr_status_payload())

# ── 全局代理配置 API ──
@app.route('/api/network/proxy', methods=['GET', 'POST'])
def api_network_proxy():
    """获取或更新全局代理配置。"""
    if request.method == 'GET':
        _cfg = read_json(CONFIG_FILE, {})
        nc = _cfg.get('network', {})
        proxy_cfg = nc.get('proxy', {}) if isinstance(nc, dict) else {}
        return jsonify({
            'enabled': bool(proxy_cfg.get('enabled', False)),
            'url': proxy_cfg.get('url', ''),
            'env_http_proxy': os.getenv('HTTP_PROXY', ''),
            'env_https_proxy': os.getenv('HTTPS_PROXY', ''),
        })

    # POST: 保存代理配置
    try:
        _cfg = read_json(CONFIG_FILE, {})
        body = request.get_json(force=True) or {}
        enabled = bool(body.get('enabled', False))
        url = str(body.get('url', '')).strip()

        _cfg.setdefault('network', {})
        _cfg['network']['proxy'] = {'enabled': enabled, 'url': url}

        from core.config import save_config as _sc
        if _sc(_cfg):
            return jsonify({'ok': True, 'message': '代理配置已保存'})
        return jsonify({'ok': False, 'message': '配置保存失败'}), 500
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 400

@app.route('/api/network/proxy/test', methods=['POST'])
def api_network_proxy_test():
    """测试代理连通性。"""
    try:
        body = request.get_json(force=True) or {}
        test_url = str(body.get('url', '')).strip()

        if not test_url:
            from services.proxy_config import get_proxy_url
            proxy_url = get_proxy_url()
        else:
            proxy_url = test_url

        if not proxy_url:
            return jsonify({'ok': False, 'message': '未配置代理地址'})

        import urllib.request
        proxy_handler = urllib.request.ProxyHandler({
            'http': proxy_url,
            'https': proxy_url,
        })
        opener = urllib.request.build_opener(proxy_handler)
        start = time.time()
        try:
            resp = opener.open('https://www.baidu.com', timeout=10)
            elapsed = round(time.time() - start, 3)
            return jsonify({
                'ok': True,
                'message': f'代理连通 (百度返回 {resp.status}, 耗时 {elapsed}s)',
                'elapsed': elapsed,
                'status_code': resp.status,
            })
        except Exception as e:
            elapsed = round(time.time() - start, 3)
            return jsonify({
                'ok': False,
                'message': f'代理不通: {e}',
                'elapsed': elapsed,
            })
    except Exception as e:
        return jsonify({'ok': False, 'message': str(e)}), 400


# ── 面板认证检查（免责声明 + 首次设置 + 登录）──
@app.before_request
def _check_auth():
    def _auth_response(message: str, *, status: int = 401):
        """Keep API clients on JSON instead of redirecting them to an HTML page."""
        if request.path.startswith('/api/'):
            return jsonify(ok=False, message=message, auth_required=True), status
        return None

    if app.testing:
        return None
    # 0. 健康检查 / 部署状态 / ASR状态 — 免登录直接放行（供 Docker / 监控使用）
    _health_paths = ('/api/health', '/deploy_status', '/api/asr/status')
    if request.path in _health_paths:
        return None

    # 1. Every browser session must explicitly acknowledge the disclaimer.
    # BILI_DISCLAIMER_SKIP is only for the terminal launcher prompt; it must
    # never silently waive the browser acknowledgement.
    if not session.get('disclaimer_agreed'):
        if request.endpoint in ('disclaimer_page', 'api_disclaimer_confirm', 'static', 'app_icon'):
            return None
        if request.path.startswith('/api/disclaimer'):
            return None
        if request.path == '/disclaimer':
            return None
        api_response = _auth_response('请先确认免责声明')
        if api_response:
            return api_response
        from urllib.parse import quote as _url_quote
        return redirect('/disclaimer?next=' + _url_quote(request.full_path.rstrip('?'), safe='/?:=&'))

    # 2. 检查面板是否已配置（首次使用）
    config = read_json(CONFIG_FILE, {})
    web_cfg = config.get('web', {})
    has_credentials = bool(web_cfg.get('username')) and bool(web_cfg.get('password'))
    if not has_credentials:
        allowed = ('setup_page', 'api_auth_setup', 'api_auth_logout', 'static', 'app_icon')
        if request.endpoint in allowed:
            return None
        if request.path in ('/setup', '/api/auth/setup', '/api/auth/logout'):
            return None
        api_response = _auth_response('面板尚未完成首次配置')
        if api_response:
            return api_response
        return redirect('/setup')

    # 3. 检查登录状态。已登录会话不应继续停留在登录页，否则用户手动
    # 改回根路径时看起来像是绕过了密码，实际上只是仍持有有效会话。
    if session.get('panel_authenticated'):
        if request.endpoint in ('login_page', 'setup_page', 'forgot_password_page'):
            return redirect('/')
        return None
    allowed = (
        'login_page', 'forgot_password_page', 'api_auth_login', 'api_auth_setup',
        'api_auth_logout', 'api_auth_recovery_question', 'api_auth_reset_password',
        'api_health', 'static', 'app_icon',
    )
    if request.endpoint in allowed:
        return None
    if request.path in (
        '/login', '/forgot-password', '/api/auth/login', '/api/auth/logout',
        '/api/auth/status', '/api/auth/recovery-question', '/api/auth/reset-password',
        '/api/health',
    ):
        return None
    api_response = _auth_response('登录状态已失效，请重新登录')
    if api_response:
        return api_response
    from urllib.parse import quote as _url_quote
    return redirect('/login?next=' + _url_quote(request.full_path.rstrip('?'), safe='/?:=&'))


# ═══════════════════════════════════════════
#  启动
# ═══════════════════════════════════════════
def main():
    # 冻结窗口版（console=False）下 sys.stdout/stderr 为 None，
    # 任何 print/flush 都会抛 AttributeError；重定向到空设备兜底。
    if sys.stdout is None:
        sys.stdout = open(os.devnull, 'w', encoding='utf-8')
    if sys.stderr is None:
        sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    port = get_web_port()
    host = os.getenv('WEB_HOST', '0.0.0.0')
    account_label = ""

    if _ensure_recovery_file():
        print(f"[Account] 忘记账号或密码时，请查看: {_recovery_file_path()}", flush=True)

    if is_our_panel(port):
        url = panel_url(port)
        print(f"[Web] 网页端已在运行，正在打开 {url}", flush=True)
        if os.getenv("BILI_WEB_AUTO_OPEN", "1") != "0":
            import webbrowser
            webbrowser.open(url)
        return
    if is_port_open(port):
        fallback_port = find_available_port(port + 1)
        print(f"[Web] 端口 {port} 已被其他程序占用，自动改用 {fallback_port}。", flush=True)
        port = fallback_port

    # ── 免责声明确认（从bat启动时BILI_DISCLAIMER_SKIP=1可跳过）──
    if not os.getenv('BILI_DISCLAIMER_SKIP'):
        if sys.stdin.isatty():
            _disclaimer_confirm_terminal()
        else:
            print("[Disclaimer] 非交互环境，自动确认免责声明。", flush=True)
    # 终端已确认免责声明，直接标记 session 跳过网页端再次确认
    with app.test_request_context():
        session['disclaimer_agreed'] = True

    banner = f"""
╔══════════════════════════════════════════════╗
║     B站 AI 管理系统 · Web 控制面板{account_label}        ║
╠══════════════════════════════════════════════╣
║   本地: http://127.0.0.1:{port}              ║
║   局域网: http://0.0.0.0:{port}             ║
║   数据: {DATA_DIR}
╚══════════════════════════════════════════════╝
"""
    print(banner, flush=True)
    print("(Disclaimer) This project is for learning purposes only. Any consequences are solely your own responsibility.", flush=True)
    log_line(f"[Web] Panel started (port: {port})")
    # New videos cache their CC timeline during normal learning. Historical
    # repair remains available through its explicit API, but must not launch
    # network work and flood the log merely because the panel was opened.
    if os.getenv("BILI_TIMELINE_BACKFILL", "0") == "1":
        # Delay this background repair until the panel is listening.  It only
        # runs while the bot is idle and spaces requests by at least 20 seconds.
        def _backfill_scored_timelines_after_start():
            time.sleep(8.0)
            _start_scored_timeline_backfill()

        threading.Thread(target=_backfill_scored_timelines_after_start, daemon=True).start()
    if os.getenv("BILI_WEB_AUTO_OPEN", "1") != "0":
        threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    if os.getenv("BILI_BOT_AUTO_START", "0") == "1":
        auto_mode = os.getenv("BILI_BOT_AUTO_START_MODE", "current").strip().lower()
        if auto_mode not in ("smart", "current"):
            auto_mode = "current"

        def _auto_start_bot():
            time.sleep(1.0)
            ok, message = start_bot_process(auto_mode)
            log_line(f"[AUTO] {message}" if ok else f"[AUTO] 机器人启动失败: {message}")

        threading.Thread(target=_auto_start_bot, daemon=True).start()
    def _exit_web_from_tray() -> None:
        stop_bot_process()
        os._exit(0)

    global _system_tray
    tray = SystemTray(panel_url(port), on_exit=_exit_web_from_tray)
    _system_tray = tray
    tray_enabled = os.getenv("BILI_TRAY_DISABLED", "0") != "1"
    if tray_enabled and tray.start():
        print("[Web] 系统托盘图标已启动（右键可显示网页或退出）", flush=True)
    elif tray_enabled and os.name == "nt":
        print("[Web] 系统托盘不可用：请安装 pystray 后重试", flush=True)
    if tray_enabled:
        def _dispatch_local_reminders() -> None:
            from services.reminders import take_due
            while True:
                time.sleep(10)
                for reminder in take_due():
                    content = str(reminder.get("content") or "你有一条待办提醒")
                    log_line(f"[REMINDER] 到点提醒: {content}")
                    tray.notify("BiliLearn 提醒", content)

        threading.Thread(target=_dispatch_local_reminders, daemon=True).start()
    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    finally:
        tray.stop()
        _system_tray = None
if __name__ == '__main__':
    main()
