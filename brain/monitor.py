"""brain/monitor.py — 实时监听模式

独立于视频刷取的监听引擎，专门盯私信+评论并AI回复。
不消耗精力、不刷视频，只做消息监听和回复。
"""
import asyncio
import json
import os
import random
import sys
import time
from datetime import datetime
from pathlib import Path

from colorama import Fore, Style

from core.config import config, DATA_DIR, COOKIE_FILE, COMMENT_LOG_FILE, PRIVATE_MESSAGE_LOG_FILE
from api.client import BiliClient
from api.auth import is_bili_logged_in
from api.throttle import _bili_throttle, _bili_trigger_cooldown
from brain.comment import CommentInteractionManager
from brain.private_msg import PrivateMessageManager
from utils.display import log
from utils.lock import _acquire_bot_lock, _release_bot_lock

# 监听配置
MONITOR_CONFIG_FILE = os.path.join(DATA_DIR, "monitor_config.json")

# 默认配置
DEFAULT_MONITOR_CONFIG = {
    "comment_check_interval": 120,
    "private_msg_check_interval": 60,
    "auto_reply": True,
    "max_replies_per_check": 5,
    "enabled": True,
}


def load_monitor_config():
    """加载监听配置，不存在则返回默认值"""
    if os.path.exists(MONITOR_CONFIG_FILE):
        try:
            with open(MONITOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 合并默认值
                merged = {**DEFAULT_MONITOR_CONFIG, **data}
                return merged
        except (json.JSONDecodeError, OSError):
            pass
    return DEFAULT_MONITOR_CONFIG.copy()


def save_monitor_config(cfg):
    """保存监听配置"""
    try:
        os.makedirs(os.path.dirname(MONITOR_CONFIG_FILE), exist_ok=True)
        tmp = MONITOR_CONFIG_FILE + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        os.replace(tmp, MONITOR_CONFIG_FILE)
        return True
    except Exception as e:
        log(f"保存监听配置失败: {e}", "ERROR")
        return False


class MonitorBot:
    """实时监听机器人 — 专门盯私信+评论，不刷视频"""

    def __init__(self):
        self.running = False
        self.start_time = None
        self.stats = {
            "comments_processed": 0,
            "messages_processed": 0,
            "total_replies": 0,
            "errors": 0,
        }
        self.cfg = load_monitor_config()
        self.comment_mgr = None
        self.private_msg_mgr = None
        self.bili = None
        self.uid = 0
        self._last_comment_check = None
        self._last_msg_check = None

    async def initialize(self):
        """初始化登录和管理器"""
        self.bili = BiliClient()
        self.bili.credential = self.bili._load_credential()

        if not self.bili.credential or not os.path.exists(COOKIE_FILE):
            log("[LOCK] 未登录B站，无法启动监听", "ERROR")
            return False

        try:
            with open(COOKIE_FILE, 'r', encoding='utf-8') as f:
                cookies = json.load(f)
            self.uid = int(cookies.get("DedeUserID", 0))
            self.bili.uid = self.uid
        except Exception as e:
            log(f"加载Cookie失败: {e}", "ERROR")
            return False

        log(f"监听模式登录就绪 (UID: {self.uid})", "SUCCESS")

        # 初始化评论管理器
        self.comment_mgr = CommentInteractionManager(
            self.bili.credential, self.uid, since_ts=0
        )
        # 初始化私信管理器
        self.private_msg_mgr = PrivateMessageManager(
            self.bili.credential, self.uid, since_ts=0, previous_seen_at=""
        )

        # 重新加载配置
        self.cfg = load_monitor_config()

        return True

    async def run(self):
        """主监听循环"""
        if not await self.initialize():
            return False

        if not _acquire_bot_lock():
            log("[LOCK] 已有bot实例运行中，监听模式无法启动", "ERROR")
            return False

        self.running = True
        self.start_time = datetime.now()

        log("=" * 60, "INFO")
        log("📡 实时监听模式已启动", "SUCCESS")
        log(f"  评论检查间隔: {self.cfg['comment_check_interval']}秒", "INFO")
        log(f"  私信检查间隔: {self.cfg['private_msg_check_interval']}秒", "INFO")
        log(f"  自动回复: {'开启' if self.cfg['auto_reply'] else '关闭'}", "INFO")
        log(f"  每次最大回复: {self.cfg['max_replies_per_check']}条", "INFO")
        log("=" * 60, "INFO")

        try:
            while self.running:
                self.cfg = load_monitor_config()  # 热加载配置
                now = datetime.now()
                tasks = []

                # 并行检查评论和私信
                if self.cfg.get("enabled", True):
                    if self._should_check_comments(now):
                        tasks.append(self._check_comments())
                    if self._should_check_messages(now):
                        tasks.append(self._check_messages())

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

                # 等待一个最小间隔，避免空转
                await asyncio.sleep(1)

        except asyncio.CancelledError:
            log("📡 监听模式被取消", "INFO")
        except KeyboardInterrupt:
            log("📡 监听模式被中断", "INFO")
        except Exception as e:
            log(f"监听主循环异常: {e}", "ERROR")
            self.stats["errors"] += 1
        finally:
            self.running = False
            _release_bot_lock()
            self._save_stats()
            log("📡 实时监听模式已停止", "INFO")

        return True

    def stop(self):
        """停止监听"""
        self.running = False
        log("正在停止监听...", "INFO")

    def _should_check_comments(self, now):
        """判断是否该检查评论"""
        if self._last_comment_check is None:
            return True
        elapsed = (now - self._last_comment_check).total_seconds()
        return elapsed >= self.cfg.get("comment_check_interval", 120)

    def _should_check_messages(self, now):
        """判断是否该检查私信"""
        if self._last_msg_check is None:
            return True
        elapsed = (now - self._last_msg_check).total_seconds()
        return elapsed >= self.cfg.get("private_msg_check_interval", 60)

    async def _check_comments(self):
        """检查并处理新评论"""
        self._last_comment_check = datetime.now()
        try:
            processed = await self.comment_mgr.process_new_comments(self.bili)
            if processed > 0:
                self.stats["comments_processed"] += processed
                self.stats["total_replies"] += processed
                log(f"[监听] 处理了 {processed} 条评论", "SUCCESS")
            return processed
        except Exception as e:
            log(f"[监听] 评论检查失败: {e}", "ERROR")
            self.stats["errors"] += 1
            return 0

    async def _check_messages(self):
        """检查并处理新私信"""
        self._last_msg_check = datetime.now()
        try:
            processed = await self.private_msg_mgr.process_new_messages()
            if processed > 0:
                self.stats["messages_processed"] += processed
                self.stats["total_replies"] += processed
                log(f"[监听] 处理了 {processed} 条私信", "SUCCESS")
            return processed
        except Exception as e:
            log(f"[监听] 私信检查失败: {e}", "ERROR")
            self.stats["errors"] += 1
            return 0

    def get_status(self):
        """获取当前监听状态"""
        uptime = ""
        if self.start_time and self.running:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            hours = int(elapsed // 3600)
            minutes = int((elapsed % 3600) // 60)
            seconds = int(elapsed % 60)
            uptime = f"{hours}h {minutes}m {seconds}s"

        return {
            "running": self.running,
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "uptime": uptime,
            "uid": self.uid,
            "config": self.cfg,
            "stats": self.stats.copy(),
            "last_comment_check": self._last_comment_check.isoformat() if self._last_comment_check else None,
            "last_msg_check": self._last_msg_check.isoformat() if self._last_msg_check else None,
        }

    def _save_stats(self):
        """保存统计到文件"""
        stats_file = os.path.join(DATA_DIR, "monitor_stats.json")
        try:
            data = {
                "last_stop": datetime.now().isoformat(),
                "stats": self.stats,
                "uptime_seconds": (datetime.now() - self.start_time).total_seconds() if self.start_time else 0,
            }
            tmp = stats_file + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, stats_file)
        except Exception:
            pass


# 全局单例
_monitor_instance = None
_monitor_task = None


def get_monitor():
    """获取全局监听实例"""
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = MonitorBot()
    return _monitor_instance


def is_monitor_running():
    """检查监听是否在运行"""
    m = get_monitor()
    return m.running


if __name__ == "__main__":
    import asyncio
    from colorama import Fore, Style
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  📡 实时监听模式{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  不刷视频 · 专盯私信+评论 · 实时AI回复{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    
    bot = MonitorBot()
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}📡 监听模式已中断{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 监听异常: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
    finally:
        _release_bot_lock()
