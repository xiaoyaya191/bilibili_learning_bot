"""
_services_ai.py — services/ 共享的 AI 调用层

模仿 brain/_brain_ai.py 的 Claude 风格调用：
- _live_config(): 实时读取配置（避免 import * 缓存问题）
- _call_ai(): openai 库（主） + httpx 直连（备）
- 简单重试 + 优雅降级

所有 services/ 下的模块统一使用此文件调用 LLM。
"""

from __future__ import annotations

import json
import os
import asyncio
import traceback
from datetime import datetime
from typing import Any

from colorama import Fore, Style


def _live_config() -> dict:
    """实时读取 API 配置（绕过 import * 导致的模块级变量缓存问题）。
    每次调用都从 config 字典重新读取，确保用户通过菜单修改后即时生效。"""
    try:
        from core.config import config as _cfg
    except Exception:
        return {}

    api = _cfg.get("api", {})

    def _or_env(cfg_key, env_name):
        return api.get(cfg_key, "") or os.getenv(env_name, "")

    vision_api_key = api.get("vision_api_key", "")
    vision_base_url = api.get("vision_base_url", "")

    return {
        "api_key": _or_env("unified_api_key", "BILI_AI_API_KEY"),
        "base_url": _or_env("unified_base_url", "BILI_AI_BASE_URL"),
        "model_brain": _or_env("model_brain", "BILI_AI_MODEL_BRAIN"),
        "vision_api_key": vision_api_key if vision_api_key else _or_env("unified_api_key", "BILI_AI_API_KEY"),
        "vision_base_url": vision_base_url if vision_base_url else _or_env("unified_base_url", "BILI_AI_BASE_URL"),
    }


async def _call_ai_via_openai(
    messages: list[dict],
    *,
    model: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> Any:
    """通过 openai 库调用（主通道）。"""
    from openai import OpenAI

    live = _live_config()
    api_key = live.get("api_key", "")
    base_url = live.get("base_url", "")
    _model = model or live.get("model_brain", "")

    if not api_key:
        raise RuntimeError("API Key 未配置")
    if not base_url or "://" not in str(base_url):
        raise RuntimeError(f"API地址无效: '{base_url}'")

    client = OpenAI(api_key=api_key, base_url=base_url, timeout=float(timeout))
    return client.chat.completions.create(
        model=_model,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )


async def _call_ai_via_httpx(
    messages: list[dict],
    *,
    model: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
) -> Any:
    """通过 httpx 直接 POST（备用通道）。
    [FIX] 手动序列化 JSON 为 UTF-8 字节，避免 Windows 下 httpx 内部
    JSON 编码器误用 ASCII 编码导致 UnicodeEncodeError。
    """
    import httpx

    live = _live_config()
    api_key = live.get("api_key", "")
    base_url = live.get("base_url", "")
    _model = model or live.get("model_brain", "")

    if not api_key:
        raise RuntimeError("API Key 未配置")
    if not base_url or "://" not in str(base_url):
        raise RuntimeError(f"API地址无效: '{base_url}'")

    url = f"{base_url.rstrip('/')}/chat/completions"
    payload = {
        "model": _model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # 手动序列化 JSON 为 UTF-8 字节
    body_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body_bytes)),
    }

    async with httpx.AsyncClient(timeout=float(timeout)) as client:
        resp = await client.post(url, headers=headers, content=body_bytes)
        resp.raise_for_status()
        data = resp.json()

    # 构造兼容 OpenAI 响应对象
    class _Msg:
        def __init__(self, d):
            self.content = d.get("content", "")

    class _Choice:
        def __init__(self, d):
            self.message = _Msg(d.get("message", {}))

    class _Resp:
        def __init__(self, d):
            self.choices = [_Choice(c) for c in d.get("choices", [])]

    return _Resp(data)


async def call_ai(
    messages: list[dict],
    *,
    model: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    verbose: bool = True,
) -> str:
    """
    Claude 风格统一 AI 调用入口。

    - 主通道: openai 库
    - 备用通道: httpx 直连
    - 最多重试 3 次
    - 返回 response.choices[0].message.content 字符串

    所有 services/ 模块统一使用此函数。
    """
    live = _live_config()
    api_key = live.get("api_key", "")
    if not api_key:
        raise RuntimeError("API Key 未配置，请在 Data/config.json 中设置 unified_api_key")

    _model = model or live.get("model_brain", "")
    if not _model:
        raise RuntimeError("未配置 model_brain，请在配置菜单中设置 AI 模型")

    backends = [
        ("openai", _call_ai_via_openai),
        ("httpx", _call_ai_via_httpx),
    ]

    last_error = None
    max_attempts = 3

    for attempt in range(max_attempts):
        for backend_name, backend_fn in backends:
            try:
                if verbose and attempt > 0:
                    print(f"{Fore.CYAN}[AI] 重试 (第{attempt+1}次) via {backend_name}...{Style.RESET_ALL}")

                resp = await backend_fn(
                    messages=messages,
                    model=_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )

                content = resp.choices[0].message.content or ""
                if content.strip():
                    return content
                else:
                    last_error = RuntimeError("AI 返回了空内容")
                    continue

            except Exception as e:
                last_error = e
                err_msg = str(e).lower()
                # 模型不可用 → 直接换后端，不重试
                if any(kw in err_msg for kw in
                       ['model_not_found', '无可用渠道', 'model is not found', 'unsupported model']):
                    if verbose:
                        print(f"{Fore.YELLOW}[AI] 模型不可用 via {backend_name}，切换后端...{Style.RESET_ALL}")
                    break
                continue

        if attempt < max_attempts - 1:
            wait = (attempt + 1) * 2.0
            short_err = str(last_error)[:120] if last_error else "未知错误"
            if verbose:
                print(f"{Fore.YELLOW}[AI] 调用异常({short_err})，等待{wait:.0f}秒后重试...{Style.RESET_ALL}")
            await asyncio.sleep(wait)

    raise last_error or RuntimeError("AI 调用全部失败")


def log(msg: str, level: str = "INFO"):
    """彩色日志输出（简化版，不依赖 core.config.log）"""
    colors = {
        "INFO": Fore.WHITE,
        "SUCCESS": Fore.GREEN,
        "WARN": Fore.YELLOW,
        "ERROR": Fore.RED,
        "DEBUG": Fore.CYAN,
    }
    timestamp = datetime.now().strftime("%H:%M:%S")
    color = colors.get(level, Fore.WHITE)
    print(f"{color}[{timestamp}][{level}] {msg}{Style.RESET_MAX}")
