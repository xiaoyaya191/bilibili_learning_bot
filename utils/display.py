"""utils/display.py — 显示/日志工具函数"""
from colorama import Fore, Style
import re
import sys
import os

_SENSITIVE = re.compile(r"(?i)(SESSDATA|bili_jct|DedeUserID|access_token|refresh_token|api[_ -]?key|authorization|password)(\s*:\s*Bearer\s+|\s*[=:]\s*[\"']?|\s+Bearer\s+)([^,\s\"'};]+)")

def redact_sensitive_text(value):
    return _SENSITIVE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", str(value or ""))


def mask_secret(value):
    if not value:
        return "(未配置)"
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


def _append_console_log(text: str) -> None:
    """把控制台日志同时写入 DATA_DIR/bot_console.log，方便 Termux/后台排错。"""
    try:
        from core.user_data import DATA_DIR
        path = os.path.join(DATA_DIR, "bot_console.log")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        if os.path.exists(path) and os.path.getsize(path) > 5 * 1024 * 1024:
            with open(path, "r", encoding="utf-8", errors="replace") as source:
                tail = source.read()[-1024 * 1024:]
            with open(path, "w", encoding="utf-8") as target:
                target.write(tail)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text + "\n")
    except Exception:
        pass


def log(msg, level="INFO"):
    # 安静模式：隐藏INFO/SCAN/DM级别的例行输出
    try:
        from core.globals import QUIET_MODE as _quiet
        if _quiet and level in ("INFO", "SCAN", "DM"):
            return
    except ImportError:
        pass
    colors = {
        "INFO": Fore.WHITE, "SUCCESS": Fore.GREEN, "WARN": Fore.YELLOW, "ERROR": Fore.RED,
        "SCAN": Fore.CYAN, "EYE": Fore.MAGENTA, "BRAIN": Fore.BLUE, "ACT": Fore.GREEN,
        "MEM": Fore.LIGHTBLUE_EX, "NOTE": Fore.WHITE, "COIN": Fore.YELLOW, "DIAG": Fore.LIGHTBLACK_EX,
        "LEARN": Fore.LIGHTMAGENTA_EX, "ENERGY": Fore.LIGHTCYAN_EX, "LOGIN": Fore.LIGHTYELLOW_EX,
        "CONFIG": Fore.LIGHTGREEN_EX, "KB": Fore.LIGHTMAGENTA_EX, "INTEREST": Fore.LIGHTYELLOW_EX,
        "COMMENT": Fore.LIGHTCYAN_EX, "EVOLVE": Fore.LIGHTMAGENTA_EX, "SUBTITLE": Fore.CYAN
    }
    icons = {
        "SCAN": "[SCAN]", "EYE": "[EYE]", "BRAIN": "[BRAIN]", "ACT": "[FAST]", "MEM": "[MEM]", "NOTE": "[NOTE]",
        "WARN": "[WARN]", "ERROR": "[ERROR]", "SUCCESS": "[OK]", "COIN": "[COIN]", "INFO": "[INFO]", "DIAG": "[DIAG]",
        "LEARN": "[LEARN]", "ENERGY": "[FAST]", "LOGIN": "[LOGIN]", "CONFIG": "[CONFIG]", "KB": "[KB]",
        "INTEREST": "[TARGET]", "COMMENT": "[MSG]", "DM": "[DM]", "EVOLVE": "[EVOLVE]", "SUBTITLE": "[SUB]"
    }

    color = colors.get(level, Fore.WHITE)
    icon = icons.get(level, '[INFO]')

    # [FIX] Windows GBK终端无法打印emoji，用ASCII标签替代
    text = f"{icon} [{level:<7}] {redact_sensitive_text(msg)}"
    _append_console_log(text)
    try:
        print(f"{color}{text}{Style.RESET_ALL}")
    except UnicodeEncodeError:
        # Some embedded/background Windows processes still expose a GBK stream.
        # Replace only unsupported glyphs so logging can never abort real work.
        encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_text = text.encode(encoding, errors="replace").decode(encoding, errors="replace")
        try:
            print(safe_text)
        except UnicodeEncodeError:
            sys.stdout.buffer.write((safe_text + "\n").encode(encoding, errors="replace"))
