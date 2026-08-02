"""brain/monitor.py — 实时监听模式

独立于视频刷取的监听引擎，专门盯私信+评论并AI回复。
不消耗精力、不刷视频，只做消息监听和回复。
"""
import asyncio
import json
import os
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from colorama import Fore, Style

from core.config import config, DATA_DIR, COOKIE_FILE, COMMENT_LOG_FILE, PRIVATE_MESSAGE_LOG_FILE
from api.client import BiliClient
from api.auth import is_bili_logged_in
from api.throttle import _bili_throttle, _bili_trigger_cooldown
from bilibili_api import session as bili_session
from bilibili_api import video as bili_video
from brain.comment import CommentInteractionManager, _reply_comment_like_probability
from brain.private_msg import PrivateMessageManager
from utils.display import log
from utils.lock import _acquire_bot_lock, _release_bot_lock

# 监听配置
MONITOR_CONFIG_FILE = os.path.join(DATA_DIR, "monitor_config.json")
MONITOR_AT_STATE_FILE = os.path.join(DATA_DIR, "monitor_at_state.json")

# Shared default for the web panel and CLI. Keep the old three-item default
# recognizable so existing installations gain the complete preset library.
DEFAULT_TEXT_EMOTICONS = [
    "[doge_金箍]", "[笑哭]", "[蹲蹲]", "[星星眼]", "[微笑]", "[吃瓜]", "[OK]", "[打call]",
    "[调皮]", "[歪嘴]", "[呲牙]", "[喜极而泣]", "[滑稽]", "[辣眼睛]", "[大哭]", "[doge]",
    "[妙啊]", "[藏狐]", "[嗑瓜子]", "[脱单doge]", "[笑]", "[给心心]", "[脸红]", "[嘟嘟]",
    "[惊讶]", "[偷笑]", "[疑惑]", "[嫌弃]", "[害羞]", "[酸了]", "[喜欢]", "[哦呼]",
    "[捂脸]", "[阴险]", "[呆]", "[抠鼻]", "[大笑]", "[惊喜]", "[点赞]", "[无语]",
    "[热]", "[冷]", "[疼]", "[委屈]", "[傲娇]", "[灵魂出窍]", "[尴尬]", "[鼓掌]",
    "[生病]", "[生气]", "[捂眼]", "[嘘声]", "[思考]", "[再见]", "[翻白眼]", "[抓狂]",
    "[猴哥]", "[黑眼圈_金箍]", "[撇嘴]", "[口罩]", "[难过]", "[墨镜]", "[奋斗]", "[哈欠]",
]
_LEGACY_DEFAULT_TEXT_EMOTICONS = ("[doge]", "[妙啊]", "[支持]")

# 默认配置
DEFAULT_MONITOR_CONFIG = {
    "comment_check_interval": 5,
    "private_msg_check_interval": 5,
    "auto_reply": True,
    "max_replies_per_check": 5,
    "at_mentions_enabled": True,
    "process_existing_at_mentions": False,
    "enabled": True,
    "text_emoticons": DEFAULT_TEXT_EMOTICONS,
}


def load_monitor_config():
    """加载监听配置，不存在则返回默认值"""
    if os.path.exists(MONITOR_CONFIG_FILE):
        try:
            with open(MONITOR_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if not isinstance(data, dict):
                    data = {}
                merged = {**DEFAULT_MONITOR_CONFIG, **data}
                for key in ("comment_check_interval", "private_msg_check_interval"):
                    try:
                        merged[key] = max(5, int(merged.get(key, 5)))
                    except (TypeError, ValueError):
                        merged[key] = 5
                stored_emoticons = data.get("text_emoticons")
                if not isinstance(stored_emoticons, list) or tuple(stored_emoticons) == _LEGACY_DEFAULT_TEXT_EMOTICONS:
                    merged["text_emoticons"] = list(DEFAULT_TEXT_EMOTICONS)
                else:
                    merged["text_emoticons"] = [
                        str(value).strip()[:40] for value in stored_emoticons if str(value).strip()
                    ][:80]
                return merged
        except (json.JSONDecodeError, OSError):
            pass
    default = DEFAULT_MONITOR_CONFIG.copy()
    default["text_emoticons"] = list(DEFAULT_TEXT_EMOTICONS)
    return default


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
        self._last_at_check = None
        self._rate_limit_until = {"comments": None, "messages": None, "mentions": None}
        self._processed_at_ids = self._load_processed_at_ids()
        self._at_attempts = self._load_at_attempts()
        self._source_routing_migrated_ids = self._load_source_routing_migrated_ids()
        self._has_at_baseline = os.path.exists(MONITOR_AT_STATE_FILE)

    @staticmethod
    def _load_processed_at_ids():
        try:
            with open(MONITOR_AT_STATE_FILE, "r", encoding="utf-8") as source:
                data = json.load(source)
            return {str(value) for value in data.get("processed_ids", [])}
        except (OSError, ValueError, AttributeError):
            return set()

    @staticmethod
    def _load_at_attempts():
        try:
            with open(MONITOR_AT_STATE_FILE, "r", encoding="utf-8") as source:
                data = json.load(source)
            attempts = data.get("attempts", {})
            return {str(key): int(value) for key, value in attempts.items() if int(value) > 0}
        except (OSError, ValueError, TypeError, AttributeError):
            return {}

    @staticmethod
    def _load_source_routing_migrated_ids():
        try:
            with open(MONITOR_AT_STATE_FILE, "r", encoding="utf-8") as source:
                data = json.load(source)
            return {str(value) for value in data.get("source_routing_migrated_ids", [])}
        except (OSError, ValueError, AttributeError):
            return set()

    def _save_at_state(self):
        try:
            with open(MONITOR_AT_STATE_FILE + ".tmp", "w", encoding="utf-8") as target:
                json.dump({
                    "processed_ids": list(self._processed_at_ids)[-1000:],
                    "attempts": dict(list(self._at_attempts.items())[-1000:]),
                    "source_routing_migrated_ids": list(self._source_routing_migrated_ids)[-1000:],
                }, target, ensure_ascii=False)
            os.replace(MONITOR_AT_STATE_FILE + ".tmp", MONITOR_AT_STATE_FILE)
        except OSError:
            pass

    def _mark_at_processed(self, notification_id):
        notification_id = str(notification_id)
        self._processed_at_ids.add(notification_id)
        self._at_attempts.pop(notification_id, None)
        self._save_at_state()

    def _record_at_attempt(self, notification_id):
        key = str(notification_id)
        self._at_attempts[key] = self._at_attempts.get(key, 0) + 1
        self._save_at_state()
        return self._at_attempts[key]

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
                    comments_due = self._should_check_comments(now)
                    mentions_due = self._should_check_mentions(now)
                    # Both sources can describe the same reply. Process them
                    # in one ordered task so a successful reply is visible to
                    # the @-notification deduplication before it can send.
                    if comments_due and mentions_due:
                        tasks.append(self._check_comment_channels())
                    elif comments_due:
                        tasks.append(self._check_comments())
                    elif mentions_due:
                        tasks.append(self._check_mentions())
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
        if self._is_rate_limited("comments", now):
            return False
        if self._last_comment_check is None:
            return True
        elapsed = (now - self._last_comment_check).total_seconds()
        return elapsed >= self.cfg.get("comment_check_interval", 120)

    def _should_check_messages(self, now):
        """判断是否该检查私信"""
        if self._is_rate_limited("messages", now):
            return False
        if self._last_msg_check is None:
            return True
        elapsed = (now - self._last_msg_check).total_seconds()
        return elapsed >= self.cfg.get("private_msg_check_interval", 60)

    def _should_check_mentions(self, now):
        if not self.cfg.get("at_mentions_enabled", True):
            return False
        if self._is_rate_limited("mentions", now):
            return False
        if self._last_at_check is None:
            return True
        elapsed = (now - self._last_at_check).total_seconds()
        return elapsed >= self.cfg.get("comment_check_interval", 5)

    def _is_rate_limited(self, channel, now=None):
        until = self._rate_limit_until.get(channel)
        return bool(until and (now or datetime.now()) < until)

    def _back_off_after_rate_limit(self, channel, exc):
        if "-509" not in str(exc):
            return False
        self._rate_limit_until[channel] = datetime.now() + timedelta(seconds=10)
        log(f"[监听] B站 {channel} 请求频率受限（-509），10 秒后再试", "WARN")
        return True

    @staticmethod
    def _at_items(response):
        data = response.get("data", response) if isinstance(response, dict) else {}
        if not isinstance(data, dict):
            return []
        for key in ("items", "list", "notifications"):
            if isinstance(data.get(key), list):
                return data[key]
        return []

    @staticmethod
    def _at_notification(item):
        detail = item.get("item", {}) if isinstance(item.get("item"), dict) else {}
        user_info = item.get("user", {}) if isinstance(item.get("user"), dict) else {}
        content = str(detail.get("desc") or detail.get("content") or detail.get("title") or item.get("content") or "").strip()
        uri = str(detail.get("uri") or item.get("uri") or "")
        bvid_match = re.search(r"BV[0-9A-Za-z]+", f"{content} {uri}", re.IGNORECASE)
        aid_match = re.search(r"(?:av|aid=)(\d+)", uri, re.IGNORECASE)
        aid = detail.get("subject_id") or detail.get("oid") or item.get("oid") or detail.get("source_id") or detail.get("business_id")
        business = str(detail.get("business") or detail.get("type") or item.get("business") or "").strip().lower()
        source_id = detail.get("source_id")
        business_id = detail.get("business_id")
        # New x/msg/at comment notifications use business_id as a small
        # category number while source_id contains the actual comment rpid.
        # Legacy payloads without a comment business keep business_id routing.
        source_is_comment_rpid = business in {"评论", "comment", "reply"} and str(source_id or "").isdigit()
        # 优先用 source_id（通常是真实评论 rpid），business_id 只是业务类型号（1/12等）
        source_id_is_rpid = str(source_id or "").isdigit() and int(str(source_id or "0")) > 100
        comment_id = (
            detail.get("rpid") or detail.get("reply_id")
            or (source_id if source_id_is_rpid else None)
            or detail.get("target_id")
            or (business_id if str(business_id or "").isdigit() and int(str(business_id or "0")) > 100 else None)
            or source_id
        )
        notification_id = item.get("id") or item.get("item_id") or f"{comment_id}:{item.get('ctime', '')}"
        return {
            "id": str(notification_id), "content": content, "uri": uri,
            "bvid": bvid_match.group(0) if bvid_match else "",
            "aid": aid or (aid_match.group(1) if aid_match else None),
            "comment_id": comment_id,
            "user": user_info.get("nickname") or user_info.get("uname") or "user",
            "user_id": user_info.get("mid") or user_info.get("uid"),
            "root_id": detail.get("root_id") or None,
            "business": detail.get("business") or detail.get("type") or item.get("business"),
            "route_source": "source_id" if source_is_comment_rpid else "rpid_or_business_id",
            "legacy_comment_id": business_id,
            "source_id": source_id,
        }

    def _requeue_source_routing_corrections(self, notifications):
        """Retry the owner's stale source_id-routed comment once after migration."""
        owner_uid = str(config.get("owner_share", {}).get("owner_bili_uid") or "").strip()
        if not owner_uid:
            return
        changed = False
        for notification in notifications:
            notification_id = str(notification.get("id") or "")
            if (
                not notification_id
                or str(notification.get("user_id") or "") != owner_uid
                or notification.get("route_source") != "source_id"
                or str(notification.get("source_id")) == str(notification.get("legacy_comment_id"))
                or notification_id not in self._processed_at_ids
                or notification_id in self._source_routing_migrated_ids
            ):
                continue
            self._processed_at_ids.discard(notification_id)
            self._at_attempts.pop(notification_id, None)
            self._source_routing_migrated_ids.add(notification_id)
            changed = True
            log(
                f"[监听][@] 修正旧通知路由，重新排队 notification={notification_id} "
                f"旧rpid={notification.get('legacy_comment_id')} 新rpid={notification.get('source_id')}",
                "INFO",
            )
        if changed:
            self._save_at_state()

    @staticmethod
    def _asks_about_video(text):
        text = str(text or "")
        return any(token in text for token in (
            "讲了什么", "讲的什么", "总结", "概括", "内容", "说了什么", "重点", "看不懂",
        ))

    async def _generate_at_reply(self, notification):
        """Ground an @ reply in metadata/subtitles when an associated video exists."""
        evidence = {"status": "no associated video"}
        bvid = str(notification.get("bvid") or "")
        try:
            if not bvid and str(notification.get("aid") or "").isdigit():
                info = await bili_video.Video(aid=int(notification["aid"]), credential=self.bili.credential).get_info()
                bvid = str((info or {}).get("bvid") or "")
            if bvid and self.comment_mgr and getattr(self.comment_mgr, "toolbox", None):
                evidence = await self.comment_mgr.toolbox.video_details(bvid)
        except Exception as exc:
            evidence = {"status": "unavailable", "error": str(exc)[:180]}

        from services._services_ai import call_ai
        from utils.helpers import ensure_ai_marker
        prompt = (
            "Reply to this Bilibili @ mention naturally and briefly. Use only the supplied evidence. "
            "Do not say the video was watched or completed; subtitles are evidence of text read, not playback. "
            "If evidence is missing, say that it cannot be confirmed. Reply in the language used by the commenter.\n\n"
            f"Commenter: {notification.get('user')}\n"
            f"Comment: {notification.get('content')}\n"
            f"Evidence: {json.dumps(evidence, ensure_ascii=False)[:7000]}"
        )
        reply = await call_ai(
            [{"role": "system", "content": "You are a concise, factual Bilibili AI comment assistant."},
             {"role": "user", "content": prompt}],
            timeout=60, verbose=False,
        )
        return ensure_ai_marker(str(reply or "").strip())

    async def _check_mentions(self):
        self._last_at_check = datetime.now()
        try:
            response = await bili_session.get_at(self.bili.credential)
            items = [self._at_notification(item) for item in self._at_items(response) if isinstance(item, dict)]
            self._requeue_source_routing_corrections(items)
            if not self._has_at_baseline and not self.cfg.get("process_existing_at_mentions", False):
                for item in items:
                    self._mark_at_processed(item["id"])
                self._has_at_baseline = True
                return 0
            self._has_at_baseline = True
            processed = 0
            for notification in (item for item in items if item["id"] not in self._processed_at_ids):
                if processed >= self.cfg.get("max_replies_per_check", 5):
                    break
                comment_id = notification.get("comment_id")
                is_processed = getattr(self.comment_mgr, "_is_comment_processed", lambda _comment_id: False)
                if comment_id and is_processed(comment_id):
                    log(
                        f"[监听][@] 已由评论通道处理，跳过重复通知 "
                        f"notification={notification['id']} rpid={comment_id}",
                        "INFO",
                    )
                    self._mark_at_processed(notification["id"])
                    processed += 1
                    continue
                log(
                    f"[监听][@] 收到通知 notification={notification['id']} aid={notification.get('aid') or '-'} "
                    f"rpid={comment_id or '-'} root={notification.get('root_id') or '-'} "
                    f"route={notification.get('route_source')} "
                    f"from=@{notification.get('user', '未知')}",
                    "MENTION",
                )
                reply = await self._generate_at_reply(notification)
                attempted = False
                sent = False
                if reply and self.cfg.get("auto_reply", True) and notification.get("aid") and notification.get("comment_id"):
                    attempted = True
                    reply_target = {
                        "id": notification["comment_id"], "aid": notification["aid"],
                        "content": notification["content"], "user": notification["user"],
                        "user_id": notification.get("user_id"),
                        "root_id": notification.get("root_id"), "parent_id": notification["comment_id"],
                        "source": "at_notification",
                    }
                    log(
                        f"[监听][@] 准备回复 aid={reply_target['aid']} rpid={reply_target['id']} "
                        f"root={reply_target.get('root_id') or reply_target['id']} parent={reply_target['id']}",
                        "MENTION",
                    )
                    sent = await self.comment_mgr.reply_to_comment(
                        self.bili, reply_target, reply, is_at_mention=True
                    )
                terminal = bool(getattr(self.comment_mgr, "last_reply_failure", {}).get("terminal"))
                if not attempted or sent or terminal:
                    if comment_id and (sent or terminal):
                        mark_comment_processed = getattr(self.comment_mgr, "_mark_comment_processed", None)
                        if callable(mark_comment_processed):
                            mark_comment_processed(comment_id)
                    self._mark_at_processed(notification["id"])
                    processed += 1
                    if sent:
                        self.stats["total_replies"] += 1
                        await self._maybe_like_at_comment(reply_target)
                    elif terminal:
                        reason = getattr(self.comment_mgr, "last_reply_failure", {}).get("reason", "目标已失效")
                        log(
                            f"[监听][@] 平台拒绝该评论，已停止重试 notification={notification['id']} "
                            f"rpid={comment_id}: {reason}",
                            "WARN",
                        )
                else:
                    attempts = self._record_at_attempt(notification["id"])
                    self.stats["errors"] += 1
                    if attempts >= 3:
                        self._mark_at_processed(notification["id"])
                        processed += 1
                        log(f"mention delivery abandoned after 3 attempts: @{notification['user']}", "WARN")
            self.stats.setdefault("mentions_processed", 0)
            self.stats["mentions_processed"] += processed
            return processed
        except Exception as exc:
            self._back_off_after_rate_limit("mentions", exc)
            self.stats["errors"] += 1
            log(f"mention check failed: {exc}", "WARN")
            return 0

    async def _check_comment_channels(self):
        """Avoid duplicate replies when the reply feed and @ feed overlap."""
        await self._check_comments()
        return await self._check_mentions()

    async def _maybe_like_at_comment(self, comment_data):
        probability = _reply_comment_like_probability()
        roll = random.random()
        if roll >= probability:
            log(
                f"[监听][@] 不点赞原评论 rpid={comment_data['id']} "
                f"(概率 {probability:.0%}，本次 {roll:.0%})",
                "INFO",
            )
            return False
        log(
            f"[监听][@] 选择点赞原评论 rpid={comment_data['id']} "
            f"(概率 {probability:.0%}，本次 {roll:.0%})",
            "MENTION",
        )
        like_comment = getattr(self.comment_mgr, "like_comment", None)
        if not callable(like_comment):
            return False
        liked = await like_comment(self.bili, comment_data)
        if not liked:
            log(f"[监听][@] 原评论点赞未完成 rpid={comment_data['id']}", "WARN")
        return liked

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
            self._back_off_after_rate_limit("comments", e)
            log(f"[监听] 评论检查失败: {e}", "ERROR")
            self.stats["errors"] += 1
            return 0

    async def _check_messages(self):
        """检查并处理新私信"""
        self._last_msg_check = datetime.now()
        started_at = time.monotonic()
        try:
            processed = await self.private_msg_mgr.process_new_messages(
                max_replies=self.cfg.get("max_replies_per_check", 5),
                auto_reply=self.cfg.get("auto_reply", True),
            )
            if processed > 0:
                self.stats["messages_processed"] += processed
                self.stats["total_replies"] += processed
                log(f"[监听] 处理了 {processed} 条私信", "SUCCESS")
            return processed
        except Exception as e:
            self._back_off_after_rate_limit("messages", e)
            elapsed = time.monotonic() - started_at
            error_text = str(e)
            if "curl: (28)" in error_text or "timed out" in error_text.lower():
                log(
                    f"[监听][私信] 拉取超时 elapsed={elapsed:.1f}s；本轮跳过，"
                    f"将在 {self.cfg.get('private_msg_check_interval', 5)}s 后继续检查。"
                    f"底层错误: {error_text[:180]}",
                    "WARN",
                )
            else:
                log(
                    f"[监听][私信] 检查失败 elapsed={elapsed:.1f}s: {error_text[:240]}",
                    "ERROR",
                )
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


async def main():
    """Run the standalone monitor mode for CLI and frozen desktop launches."""
    return await MonitorBot().run()


def configure_monitor_cli():
    """Edit monitor settings or start monitor mode from the command-line menu."""
    cfg = load_monitor_config()
    while True:
        print(f"\n{Fore.CYAN}{'=' * 52}{Style.RESET_ALL}")
        print(f"{Fore.CYAN}实时监听设置{Style.RESET_ALL}")
        print(f"1. 自动回复: {'开启' if cfg.get('auto_reply', True) else '关闭'}")
        print(f"2. 评论/@我检查间隔: {cfg.get('comment_check_interval', 5)} 秒")
        print(f"3. 私信检查间隔: {cfg.get('private_msg_check_interval', 5)} 秒")
        print(f"4. 每轮最大处理数: {cfg.get('max_replies_per_check', 5)}")
        print("5. 启动实时监听")
        print("0. 返回")
        try:
            choice = input("请选择: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice == "0":
            return
        if choice == "1":
            cfg["auto_reply"] = not bool(cfg.get("auto_reply", True))
        elif choice in {"2", "3", "4"}:
            labels = {
                "2": ("comment_check_interval", "评论/@我检查间隔（最少 5 秒）", 5),
                "3": ("private_msg_check_interval", "私信检查间隔（最少 5 秒）", 5),
                "4": ("max_replies_per_check", "每轮最大处理数（1-20）", 1),
            }
            key, label, minimum = labels[choice]
            try:
                value = int(input(f"{label}: ").strip())
            except (ValueError, EOFError, KeyboardInterrupt):
                print(f"{Fore.YELLOW}未修改。{Style.RESET_ALL}")
                continue
            cfg[key] = min(20, max(minimum, value))
        elif choice == "5":
            save_monitor_config(cfg)
            try:
                asyncio.run(main())
            except KeyboardInterrupt:
                print(f"{Fore.YELLOW}监听已停止。{Style.RESET_ALL}")
            return
        else:
            print(f"{Fore.YELLOW}无效选项。{Style.RESET_ALL}")
            continue
        if save_monitor_config(cfg):
            print(f"{Fore.GREEN}监听配置已保存。{Style.RESET_ALL}")


if __name__ == "__main__":
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  📡 实时监听模式{Style.RESET_ALL}")
    print(f"{Fore.CYAN}  不刷视频 · 专盯私信+评论 · 实时AI回复{Style.RESET_ALL}")
    print(f"{Fore.CYAN}{'='*60}{Style.RESET_ALL}")
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}📡 监听模式已中断{Style.RESET_ALL}")
    except Exception as e:
        print(f"{Fore.RED}[ERROR] 监听异常: {e}{Style.RESET_ALL}")
        import traceback
        traceback.print_exc()
    finally:
        _release_bot_lock()
