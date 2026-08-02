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
import ast
import inspect
import re
import traceback
from datetime import datetime
from typing import Any

from colorama import Fore, Style


def _extract_text_tool_call(content: str, allowed_names: set[str]) -> tuple[str, dict] | None:
    """Read a tool call emitted as plain text by imperfect OpenAI-compatible gateways."""
    text = (content or "").strip()
    if not text:
        return None
    candidates = [text]
    start = text.find("{")
    if start >= 0:
        candidates.append(text[start:])
    if re.search(r'"?name"?\s*:', text):
        candidates.append("{" + text.strip().strip(",") + "}")

    for candidate in candidates:
        data = None
        try:
            value, _ = json.JSONDecoder().raw_decode(candidate.lstrip())
            data = value if isinstance(value, dict) else None
        except json.JSONDecodeError:
            try:
                value = ast.literal_eval(candidate)
                data = value if isinstance(value, dict) else None
            except (SyntaxError, ValueError, TypeError):
                continue
        if not data:
            continue
        name = str(data.get("name") or data.get("tool_name") or "").strip()
        if name not in allowed_names:
            continue
        arguments = data.get("arguments", data.get("args", {}))
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                try:
                    arguments = ast.literal_eval(arguments)
                except (SyntaxError, ValueError):
                    arguments = {}
        return name, arguments if isinstance(arguments, dict) else {}
    return None


# 全局 429 冷却：收到 429 后 60 秒内不再调用 AI，避免连锁限流
_ai_429_cooldown_until = 0.0

def _is_fast_fail_error(error: Exception) -> bool:
    text = str(error).lower()
    return any(marker in text for marker in (
        "plugin_error",
        "empty response after retry",
        "rate limit reached",
        "429",
        "too many requests",
        "http 402",
        "insufficient balance",
        "insufficient quota",
        "quota exceeded",
        "api key 未配置",
        "all connection attempts failed",
        "connection refused",
        "actively refused",
        "failed to establish a new connection",
    ))


def _live_config() -> dict:
    """实时读取 API 配置（绕过 import * 导致的模块级变量缓存问题）。
    每次调用都从 config 字典重新读取，确保用户通过菜单修改后即时生效。"""
    try:
        # Each long-running worker has its own Python memory.  Read the
        # encrypted config on every request so a provider/model change made in
        # the CLI or web panel applies without a process restart.
        from core.config import load_config
        _cfg = load_config()
    except Exception:
        return {}

    api = _cfg.get("api", {})

    def _or_env(cfg_key, env_name):
        return api.get(cfg_key, "") or os.getenv(env_name, "")

    vision_api_key = api.get("vision_api_key", "")
    vision_base_url = api.get("vision_base_url", "")
    # 脱敏占位符视为未配置（防 '[已隐藏]' 当真实 key 发送导致 ascii 崩溃）
    if vision_api_key == "[已隐藏]":
        vision_api_key = ""

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
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
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

    # 代理支持：读取 network.proxy 配置
    import httpx as _httpx
    _proxy_url = ""
    try:
        from services.proxy_config import get_proxy_url
        _proxy_url = get_proxy_url()
    except Exception:
        pass
    _http_client = _httpx.Client(proxy=_proxy_url) if _proxy_url else None

    client = OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=float(timeout),
        max_retries=0,
        http_client=_http_client,
    )
    create_kwargs = {
        "model": _model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        create_kwargs["tools"] = tools
        create_kwargs["tool_choice"] = tool_choice
    return client.chat.completions.create(**create_kwargs)


async def _call_ai_via_httpx(
    messages: list[dict],
    *,
    model: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
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
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    # 手动序列化 JSON 为 UTF-8 字节
    body_bytes = json.dumps(payload, ensure_ascii=False).encode('utf-8')
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json; charset=utf-8",
        "Content-Length": str(len(body_bytes)),
    }

    # 代理支持
    _proxy_url = ""
    try:
        from services.proxy_config import get_proxy_url
        _proxy_url = get_proxy_url()
    except Exception:
        pass

    async with httpx.AsyncClient(timeout=float(timeout), proxy=_proxy_url or None) as client:
        resp = await client.post(url, headers=headers, content=body_bytes)
        resp.raise_for_status()
        data = resp.json()

    # 构造兼容 OpenAI 响应对象
    class _Msg:
        def __init__(self, d):
            self.content = d.get("content", "")
            self.tool_calls = d.get("tool_calls", None)

    class _Choice:
        def __init__(self, d):
            self.message = _Msg(d.get("message", {}))

    class _Resp:
        def __init__(self, d):
            self.choices = [_Choice(c) for c in d.get("choices", [])]

    return _Resp(data)


async def call_ai_raw(
    messages: list[dict],
    *,
    model: str = "",
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    verbose: bool = True,
    tools: list[dict] | None = None,
    tool_choice: str = "auto",
) -> Any:
    """
    统一 AI 调用入口（返回原始 OpenAI 响应对象）。

    - 支持 Function Calling (tools / tool_choice 参数)
    - 主通道: openai 库
    - 备用通道: httpx 直连
    - 最多重试 3 次
    - 返回 OpenAI response 对象（含 choices[0].message.content 和 tool_calls）
    """
    live = _live_config()
    api_key = live.get("api_key", "")
    if not api_key:
        raise RuntimeError("API Key 未配置，请在用户数据目录的 config.json 中设置 unified_api_key")

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
                    tools=tools,
                    tool_choice=tool_choice,
                )

                content = resp.choices[0].message.content or ""
                tool_calls = getattr(resp.choices[0].message, 'tool_calls', None)
                if content.strip() or tool_calls:
                    return resp
                else:
                    last_error = RuntimeError("AI 返回了空内容")
                    continue

            except Exception as e:
                last_error = e
                # 429 限流时启动全局冷却，避免连锁限流
                if "429" in str(e) or "too many requests" in str(e).lower():
                    import time
                    _ai_429_cooldown_until = time.time() + 60  # 60 秒冷却
                    if verbose:
                        print(f"{Fore.YELLOW}[AI] 网关限流 429，启动 60 秒冷却...{Style.RESET_ALL}")
                if _is_fast_fail_error(e):
                    raise
                err_msg = str(e).lower()
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
    import time
    # 全局 429 冷却期间直接返回空
    if time.time() < _ai_429_cooldown_until:
        if verbose:
            remaining = int(_ai_429_cooldown_until - time.time())
            print(f"{Fore.YELLOW}[AI] 429 冷却中，剩余 {remaining} 秒，跳过本次调用{Style.RESET_ALL}")
        return ""
    
    try:
        resp = await call_ai_raw(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            verbose=verbose,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        # 3 次都失败，优雅返回空字符串，不抛异常
        if verbose:
            print(f"{Fore.YELLOW}[AI] 3 次重试均失败，放弃本次调用: {str(e)[:80]}{Style.RESET_ALL}")
        return ""


async def call_ai_with_tools(
    messages: list[dict],
    tools: list[dict],
    *,
    model: str = "",
    temperature: float = 0.3,
    max_tokens: int = 4096,
    timeout: float = 120.0,
    verbose: bool = True,
    max_tool_rounds: int = 3,
    tool_handler: Any = None,
) -> str:
    """
    Function Calling 执行循环。

    将 tools 定义和 messages 发送给 LLM，模型可选择调用工具。
    工具调用结果追加到 messages 后再次发送，最多 max_tool_rounds 轮。

    Args:
        messages: 对话消息列表
        tools: OpenAI 兼容 tools 定义列表
        tool_handler: 可调用对象，接收 (tool_name, tool_args) → 返回工具执行结果字符串
        max_tool_rounds: 最大工具调用轮数
    返回: 最终 AI 回答文本
    """
    if tool_handler is None:
        return await call_ai(
            messages=messages, model=model, temperature=temperature,
            max_tokens=max_tokens, timeout=timeout, verbose=verbose,
        )

    live = _live_config()
    api_key = live.get("api_key", "")
    if not api_key:
        raise RuntimeError("API Key 未配置，请在用户数据目录的 config.json 中设置 unified_api_key")
    _model = model or live.get("model_brain", "")
    if not _model:
        raise RuntimeError("未配置 model_brain，请在配置菜单中设置 AI 模型")

    # 直接用 openai 库执行 Function Calling 循环（httpx 通道不支持 tool_calls 复杂结构）
    from openai import OpenAI
    import httpx as _httpx
    _proxy_url = ""
    try:
        from services.proxy_config import get_proxy_url
        _proxy_url = get_proxy_url()
    except Exception:
        pass
    _http_client = _httpx.Client(proxy=_proxy_url) if _proxy_url else None
    client = OpenAI(api_key=api_key, base_url=live.get("base_url", ""), timeout=float(timeout),
                    http_client=_http_client)
    allowed_tool_names = {str(tool.get("function", {}).get("name", "")) for tool in tools}

    async def execute_tool(tool_name: str, tool_args: dict) -> str:
        try:
            tool_result = tool_handler(tool_name, tool_args)
            if inspect.isawaitable(tool_result):
                tool_result = await tool_result
            if not isinstance(tool_result, str):
                return json.dumps(tool_result, ensure_ascii=False)
            return tool_result
        except Exception as exc:
            return f"工具执行错误: {exc}"

    for _round in range(max_tool_rounds):
        try:
            resp = client.chat.completions.create(
                model=_model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                tools=tools,
                tool_choice="auto",
            )
        except Exception as e:
            if verbose:
                print(f"{Fore.YELLOW}[AI-tools] 第{_round+1}轮调用失败: {e}{Style.RESET_ALL}")
            break

        choice = resp.choices[0]
        msg = choice.message

        # Some gateways serialize function calls into normal message text.
        if not msg.tool_calls:
            text_call = _extract_text_tool_call(msg.content or "", allowed_tool_names)
            if not text_call:
                return msg.content or ""
            tool_name, tool_args = text_call
            tool_result = await execute_tool(tool_name, tool_args)
            messages.append({"role": "assistant", "content": msg.content or ""})
            messages.append({
                "role": "user",
                "content": f"工具 {tool_name} 已执行，结果如下：\n{tool_result}\n\n请继续完成任务；完成时调用 finalize 工具。",
            })
            if verbose:
                print(f"{Fore.CYAN}[AI-tools] 兼容文本工具调用 {tool_name} → {tool_result[:80]}...{Style.RESET_ALL}")
            continue

        # 有 tool_calls → 执行工具并追加结果
        messages.append(msg.model_dump())

        for tc in msg.tool_calls:
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}
            tool_result = await execute_tool(tool_name, tool_args)

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })

            if verbose:
                print(f"{Fore.CYAN}[AI-tools] 调用 {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:120]}) → {tool_result[:80]}...{Style.RESET_ALL}")

    # 最后一轮：不再传 tools，让模型基于工具结果生成最终回答
    try:
        resp = client.chat.completions.create(
            model=_model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
    except Exception as e:
        if verbose:
            print(f"{Fore.YELLOW}[AI-tools] 最终回答生成失败: {e}{Style.RESET_ALL}")
        return ""


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
    print(f"{color}[{timestamp}][{level}] {msg}{Style.RESET_ALL}")
