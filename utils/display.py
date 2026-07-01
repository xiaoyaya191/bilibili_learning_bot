"""utils/display.py — 显示/日志工具函数"""
from colorama import Fore, Style


def mask_secret(value):
    if not value:
        return "(未配置)"
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


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
    text = f"{icon} [{level:<7}] {msg}"
    try:
        print(f"{color}{text}{Style.RESET_ALL}")
    except UnicodeEncodeError:
        # 如果colorama也有编码问题，降级为纯文本
        print(text)
