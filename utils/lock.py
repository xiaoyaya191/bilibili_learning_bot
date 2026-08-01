"""utils/lock.py — 单实例锁，防止多个 bot 进程同时运行"""
import os
import atexit

from colorama import Fore, Style
from core.config import DATA_DIR


_BOT_LOCK_FILE = None  # 延迟初始化，等 DATA_DIR 定义后再设
_bot_lock_acquired = False


def _acquire_bot_lock() -> bool:
    """获取 bot 单实例锁。成功返回 True，失败（已有实例运行）返回 False。"""
    global _BOT_LOCK_FILE, _bot_lock_acquired
    if _BOT_LOCK_FILE is None:
        _BOT_LOCK_FILE = os.path.join(DATA_DIR, "bot.lock")
    
    # 确  保 Data 目录存在
    os.makedirs(DATA_DIR, exist_ok=True)
    
    if os.path.exists(_BOT_LOCK_FILE):
        try:
            with open(_BOT_LOCK_FILE, 'r') as f:
                old_pid = int(f.read().strip())
            # 检查旧进程是否还活着（发 signal 0）
            os.kill(old_pid, 0)
            # 旧进程仍在运行
            print(f"{Fore.RED}[LOCK] ❌ 已有 bot 实例正在运行 (PID: {old_pid})！"
                  f"\n[LOCK] 请先停止旧实例或删除锁文件：{_BOT_LOCK_FILE}{Style.RESET_ALL}")
            return False
        except (ValueError, ProcessLookupError, OSError):
            # 旧进程已不存在或 PID 无效，清理过期锁文件
            print(f"{Fore.YELLOW}[LOCK] ⚠ 清理过期锁文件 (旧进程已不存在){Style.RESET_ALL}")
            try:
                os.remove(_BOT_LOCK_FILE)
            except OSError:
                pass
    
    # 写入当前进程 PID
    try:
        with open(_BOT_LOCK_FILE, 'w') as f:
            f.write(str(os.getpid()))
        _bot_lock_acquired = True
        # 注册退出时清理
        atexit.register(_release_bot_lock)
        return True
    except OSError as e:
        print(f"{Fore.RED}[LOCK] ❌ 无法创建锁文件: {e}{Style.RESET_ALL}")
        return False


def _release_bot_lock():
    """释放 bot 单实例锁（删除锁文件）。"""
    global _bot_lock_acquired, _BOT_LOCK_FILE
    if _bot_lock_acquired and _BOT_LOCK_FILE and os.path.exists(_BOT_LOCK_FILE):
        try:
            os.remove(_BOT_LOCK_FILE)
            _bot_lock_acquired = False
        except OSError:
            pass
