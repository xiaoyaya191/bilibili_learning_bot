# -*- coding: utf-8 -*-
"""
utils/email_verify.py — 邮箱验证码服务（找回密码 / 绑定邮箱）

通过第三方验证码服务（https://code.bxya.app）发送与校验邮箱验证码：
- POST /send-email   {"email": "...", "type": "verification"}
- POST /verify-code  {"email": "...", "code": "123456"}

设计要点：
- 纯标准库实现（urllib + 线程池超时兜底），无第三方依赖；
- 发送侧带“冷却 + 窗口”限流，防止验证码轰炸；
- 所有对外消息对小白友好，并统一附带反馈群提示。
"""

from __future__ import annotations

import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.request import Request, urlopen
from urllib.error import HTTPError
import ssl

# 第三方验证码服务
EMAIL_API_SEND = "https://code.bxya.app/send-email"
EMAIL_API_VERIFY = "https://code.bxya.app/verify-code"
_FEEDBACK_GROUP = "1056941856"

# 限流参数：同一 key（客户端+邮箱）60 秒冷却，10 分钟内最多 5 次
_SEND_COOLDOWN = 60
_SEND_WINDOW = 600
_SEND_MAX = 5

_SEND_ATTEMPTS: dict[str, list[float]] = {}
_SEND_LOCK = threading.Lock()

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def is_valid_email(email: str) -> bool:
    """宽松校验邮箱格式：local@domain.tld"""
    return bool(_EMAIL_RE.match((email or "").strip()))


def mask_email(email: str) -> str:
    """邮箱脱敏展示：791433443@qq.com -> 79****43@qq.com"""
    email = (email or "").strip()
    if "@" not in email:
        return "****"
    local, _, domain = email.partition("@")
    if len(local) <= 2:
        masked = (local[0] + "*") if local else "****"
    else:
        keep = min(2, len(local) - 1)
        masked = local[:keep] + "****" + local[-keep:]
    return f"{masked}@{domain}"


def send_throttled(key: str) -> tuple[bool, int]:
    """发送限流。返回 (是否被限制, 剩余等待秒数)。"""
    now = time.time()
    with _SEND_LOCK:
        recent = [t for t in _SEND_ATTEMPTS.get(key, []) if now - t < _SEND_WINDOW]
        if len(recent) >= _SEND_MAX:
            _SEND_ATTEMPTS[key] = recent
            return True, int(_SEND_WINDOW - (now - recent[0])) + 1
        if recent and now - recent[-1] < _SEND_COOLDOWN:
            return True, int(_SEND_COOLDOWN - (now - recent[-1])) + 1
        recent.append(now)
        _SEND_ATTEMPTS[key] = recent
        return False, 0


def _post_json(url: str, payload: dict, timeout: float = 15.0) -> dict:
    """POST JSON（线程池超时兜底），返回解析后的 dict；失败抛异常。"""

    def _do() -> dict:
        req = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "bilibili_learning_bot/3.1",
            },
        )
        ctx = ssl.create_default_context()
        try:
            with urlopen(req, timeout=timeout, context=ctx) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except HTTPError as exc:
            # 4xx/5xx：验证码错误等服务端业务错误会带 JSON 响应体，
            # 解析出来给用户看；非 JSON（如 Cloudflare 拦截页）则原样抛出。
            body = ""
            try:
                body = exc.read().decode("utf-8", "replace")
            except Exception:
                pass
            try:
                return json.loads(body)
            except Exception:
                raise

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        return pool.submit(_do).result(timeout=timeout + 5)
    finally:
        pool.shutdown(wait=False)


def send_verification_code(email: str) -> tuple[bool, str]:
    """向邮箱发送验证码。返回 (ok, message)。"""
    email = (email or "").strip()
    if not is_valid_email(email):
        return False, "邮箱格式不正确，请检查后重试"
    try:
        data = _post_json(EMAIL_API_SEND, {"email": email, "type": "verification"})
    except Exception as exc:  # 网络错误 / 超时 / 非 2xx
        return False, f"验证码发送失败（网络问题）：{exc}。可稍后重试，仍有问题请加群 {_FEEDBACK_GROUP} 咨询"
    if not isinstance(data, dict) or not data.get("success"):
        msg = ""
        if isinstance(data, dict):
            msg = str(data.get("error") or data.get("message") or "").strip()
        return False, f"验证码发送失败：{msg or '服务暂时不可用'}。请稍后重试，或加群 {_FEEDBACK_GROUP} 咨询"
    return True, "验证码已发送，请到邮箱查收（注意垃圾箱）"


def verify_code(email: str, code: str) -> tuple[bool, str]:
    """校验邮箱验证码。返回 (ok, message)。"""
    email = (email or "").strip()
    code = (code or "").strip()
    if not is_valid_email(email):
        return False, "邮箱格式不正确"
    if not re.fullmatch(r"\d{4,8}", code):
        return False, "请输入收到的验证码（4-8位数字）"
    try:
        data = _post_json(EMAIL_API_VERIFY, {"email": email, "code": code})
    except Exception as exc:
        return False, f"验证码校验失败（网络问题）：{exc}。可稍后重试，仍有问题请加群 {_FEEDBACK_GROUP} 咨询"
    if not isinstance(data, dict) or not data.get("success"):
        detail = ""
        if isinstance(data, dict):
            detail = str(data.get("error") or data.get("message") or "").strip()
        return False, f"验证码错误或已过期（{detail}）" if detail else "验证码错误或已过期，请重新输入"
    return True, "验证通过"
