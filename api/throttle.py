"""bili/throttle.py — B站 API 节流器（防止 -799 限流风暴）"""
import time
import random
import asyncio

from core.config import config
from utils.display import log

# ── 全局节流变量 ──
_last_bili_api_call = 0.0
_BILI_API_MIN_GAP = float(config.get("speed", {}).get("api_min_gap", 0.3))
_BILI_GLOBAL_COOLDOWN_UNTIL = 0.0  # 全局冷却截止时间戳，命中 -799 后所有 API 暂停
_bili_first_call_in_session = True


def reset_throttle_session():
    """新 session 开始时重置首调标记。"""
    global _bili_first_call_in_session
    _bili_first_call_in_session = True


async def _bili_throttle(label=""):
    """调用 B站 API 前执行。两重保护 + 智能节流：
    1. 全局冷却期内直接等待（-799 触发后 90~180s）
    2. 正常间隔 _BILI_API_MIN_GAP + 随机抖动（避免可预测的固定频率）
    3. [SPEED] 新 session 首次调用跳过间隔
    """
    global _last_bili_api_call, _BILI_GLOBAL_COOLDOWN_UNTIL, _bili_first_call_in_session

    # ── 第一重：全局冷却 ──
    now = time.time()
    if now < _BILI_GLOBAL_COOLDOWN_UNTIL:
        remain = _BILI_GLOBAL_COOLDOWN_UNTIL - now
        if remain > 2:
            log(f"🔒 全局限流冷却中，{remain:.0f}s 后恢复...", "COOL")
        await asyncio.sleep(remain + 0.5)
        _BILI_GLOBAL_COOLDOWN_UNTIL = 0.0
        now = time.time()

    # [SPEED] 智能节流：session 首次调用免等待（模拟首次打开App的即时请求）
    if _bili_first_call_in_session:
        _bili_first_call_in_session = False
        _last_bili_api_call = now
        return

    # ── 第二重：间隔 + 随机抖动 ──
    jitter = random.uniform(0, min(1.0, _BILI_API_MIN_GAP))
    gap = (_BILI_API_MIN_GAP + jitter) - (now - _last_bili_api_call)
    if gap > 0.01:
        await asyncio.sleep(gap)
    _last_bili_api_call = time.time()


def _bili_trigger_cooldown():
    """任一 API 命中 -799 后调用：启动全局冷却 90~180s，所有 B站 API 统一暂停重试。"""
    global _BILI_GLOBAL_COOLDOWN_UNTIL
    now = time.time()
    if now >= _BILI_GLOBAL_COOLDOWN_UNTIL:  # 已有冷却则不重复
        duration = random.uniform(90, 180)
        _BILI_GLOBAL_COOLDOWN_UNTIL = now + duration
        log(f"🔒 -799 限流命中！全局冷却 {duration:.0f}s，期间暂停所有B站API调用", "COOL")
