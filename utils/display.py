"""utils/display.py — 显示/日志工具函数"""
from colorama import Fore, Style
import re
import sys

_SENSITIVE = re.compile(r"(?i)(SESSDATA|bili_jct|DedeUserID|access_token|refresh_token|api[_ -]?key|authorization|password)(\s*:\s*Bearer\s+|\s*[=:]\s*[\"']?|\s+Bearer\s+)([^,\s\"'};]+)")

def redact_sensitive_text(value):
    return _SENSITIVE.sub(lambda m: f"{m.group(1)}{m.group(2)}***", str(value or ""))


def mask_secret(value):
    if not value:
        return "(未配置)"
    if len(value) <= 12:
        return "*" * len(value)
    return f"{value[:6]}...{value[-4:]}"


_HELP_GROUP = "1056941856"

# [D] 常见技术错误 -> 小白话 + 建议。按顺序匹配，命中即止。
_ERROR_TRANSLATIONS = [
    ((r"content-encoding.{0,4}br|Can not decode content-encoding", re.I),
     "B站返回了压缩数据但本地解压失败，多半是网络不稳或节点波动，程序会自动重试，不用处理"),
    ((r"\b412\b|\u98ce\u63a7|risk.?control", re.I),
     "B站暂时限制了请求频率（风控），属于正常保护机制，稍等几分钟会自动恢复"),
    ((r"\b352\b|\u98ce\u63a7", re.I),
     "B站风控拦截，请求太频繁了，程序会放慢节奏自动恢复"),
    ((r"\b40[13]\b|invalid.{0,12}(api.?key|token)|\u9274\u6743\u5931\u8d25|unauthorized", re.I),
     "AI 或 B站的密钥没有通过验证：请检查 API Key 是否填对、是否过期或欠费"),
    ((r"\b402\b|insufficient.{0,8}balance|\u4f59\u989d\u4e0d\u8db3|quota", re.I),
     "AI 账户余额/额度不足，请去对应平台充值后再启动"),
    ((r"\b404\b|not found", re.I),
     "请求的内容不存在（可能已删除或链接失效），程序会自动跳过"),
    ((r"\b429\b|rate.?limit|too many requests", re.I),
     "请求太频繁被限流了，程序会自动等待后重试"),
    ((r"timed?\s?out|timeout|connection.{0,10}(reset|refused|aborted)|networkerror|max retries", re.I),
     "网络连接不稳定或超时，请检查网络后稍候，程序会自动重试"),
    ((r"cookie|sessdata|\u767b\u5f55.{0,6}(\u8fc7\u671f|\u5931\u6548)|\u672a\u767b\u5f55", re.I),
     "登录状态可能过期了，请到面板里重新扫码登录B站"),
    ((r"attribute-?8|\u5173\u6ce8\u63a5\u53e3\u5df2\u8c03\u7528\u4f46\u672a\u751f\u6548", re.I),
     "关注操作被B站暂时限制了（像是风控），过一阵再试通常就好了"),
    ((r"dns|getaddrinfo", re.I),
     "域名解析失败，请检查网络或 DNS 设置（可尝试切换网络）"),
    ((r"ssl|certificate", re.I),
     "安全证书校验失败，通常是网络代理或时间不准导致的"),
]

# [D] 同一错误的"翻译提示"60 秒内只输出一次，避免高频错误刷屏
_hint_dedup = {}
_HINT_COOLDOWN = 60.0


def _humanize_hint(msg, level):
    """Return (plain-language explanation or None, is_known)."""
    text = str(msg or "")
    for (pattern, flags), explanation in _ERROR_TRANSLATIONS:
        try:
            if re.search(pattern, text, flags):
                return explanation, True
        except re.error:
            continue
    return None, False


def _maybe_print_hint(msg, level, printer):
    if level not in ("WARN", "ERROR"):
        return
    explanation, known = _humanize_hint(msg, level)
    import time as _t
    key = explanation if known else "__unknown__"
    now = _t.time()
    if now - _hint_dedup.get(key, 0.0) < _HINT_COOLDOWN:
        return
    _hint_dedup[key] = now
    if known:
        printer(f"{Fore.YELLOW}[HELP] [INFO  ] \u8bf4\u660e: {explanation}{Style.RESET_ALL}")
    else:
        printer(f"{Fore.YELLOW}[HELP] [INFO  ] \u8bf4\u660e: \u8fd9\u662f\u4e2a\u6bd4\u8f83\u5c11\u89c1\u7684\u95ee\u9898\uff0c\u7a0b\u5e8f\u4f1a\u7ee7\u7eed\u5c1d\u8bd5\u81ea\u52a8\u5904\u7406\u3002\u5982\u679c\u53cd\u590d\u51fa\u73b0\u6216\u6709\u7591\u95ee\uff0c\u53ef\u4ee5\u52a0QQ\u7fa4 {_HELP_GROUP} \u54a8\u8be2\u5927\u4f6c~{Style.RESET_ALL}")


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

    def _safe_print(line):
        try:
            print(line)
        except UnicodeEncodeError:
            encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
            safe = line.encode(encoding, errors="replace").decode(encoding, errors="replace")
            try:
                print(safe)
            except UnicodeEncodeError:
                sys.stdout.buffer.write((safe + "\n").encode(encoding, errors="replace"))

    # [D] 错误自动翻译成小白话；未知错误提示加群求助
    try:
        _maybe_print_hint(msg, level, _safe_print)
    except Exception:
        pass

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
