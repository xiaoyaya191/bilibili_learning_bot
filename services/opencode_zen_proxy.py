#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OpenCode Zen 免费模型反代
将 OpenAI 兼容请求转发到 OpenCode zen 免费 API
"""

import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

try:
    import aiohttp
    from aiohttp import web
except ImportError:
    print("缺少依赖：pip install aiohttp")
    sys.exit(1)

# ========== 配置 ==========
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "18508"))

# OpenCode Zen API 配置
ZEN_BASE_URL = "https://opencode.ai/zen"
ZEN_CHAT_URL = f"{ZEN_BASE_URL}/v1/chat/completions"
ZEN_MODELS_URL = f"{ZEN_BASE_URL}/v1/models"

# 允许的免费模型
FREE_MODELS = {
    "deepseek-v4-flash-free",
    "mimo-v2.5-free",
    "ling-3.0-flash-free",
    "nemotron-3-ultra-free",
    "north-mini-code-free",
    "laguna-s-2.1-free"
}


def log(service: str, msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{service}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log", "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def print_banner() -> None:
    print("""
══════════════════════════════════════════════════════════
  OpenCode Zen 免费模型反代 (Python)
══════════════════════════════════════════════════════════

  配置地址:
    http://0.0.0.0:{port}/v1

  客户端填写:
    Base URL:   http://0.0.0.0:{port}/v1
    API Key:    任意值
    Model:      deepseek-v4-pro / kimi-k2.6 / minimax-m2.7 等

  免费模型:
    deepseek-v4-flash-free DeepSeek V4 Flash (免费)
    mimo-v2.5-free        Mimo V2.5 (免费)
    ling-3.0-flash-free   Ling 3.0 Flash (免费)
    nemotron-3-ultra-free Nemotron 3 Ultra (免费)
    north-mini-code-free  North Mini Code (免费)
    laguna-s-2.1-free     Laguna S 2.1 (免费)

  环境变量:
    HOST              监听地址（默认 0.0.0.0）
    PORT              监听端口（默认 18508）

══════════════════════════════════════════════════════════
""".format(port=PORT))


async def handle_models(request: web.Request) -> web.Response:
    """获取模型列表"""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(ZEN_MODELS_URL, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # 只返回免费模型
                    filtered_data = [m for m in data.get("data", []) if m["id"] in FREE_MODELS]
                    return web.json_response({
                        "object": "list",
                        "data": filtered_data
                    })
                else:
                    return web.json_response(
                        {"error": f"Upstream returned {resp.status}"},
                        status=resp.status
                    )
    except Exception as e:
        log("models", f"Error: {e}")
        return web.json_response(
            {"error": str(e)},
            status=502
        )


async def handle_chat(request: web.Request) -> web.Response:
    """处理聊天请求"""
    try:
        body = await request.json()
        model = body.get("model", "deepseek-v4-flash-free")
        messages = body.get("messages", [])
        stream = body.get("stream", False)

        # 检查模型是否允许
        if model not in FREE_MODELS:
            return web.json_response(
                {"error": f"Model '{model}' is not available. Available models: {', '.join(sorted(FREE_MODELS))}"},
                status=400
            )

        log("chat", f"Model: {model}, Stream: {stream}, Messages: {len(messages)}")

        # 构建请求
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream"
        }

        payload = {
            "model": model,
            "messages": messages,
            "stream": stream
        }

        # 添加可选参数
        if "temperature" in body:
            payload["temperature"] = body["temperature"]
        if "max_tokens" in body:
            payload["max_tokens"] = body["max_tokens"]
        if "top_p" in body:
            payload["top_p"] = body["top_p"]
        if "tools" in body:
            payload["tools"] = body["tools"]
        if "tool_choice" in body:
            payload["tool_choice"] = body["tool_choice"]

        async with aiohttp.ClientSession() as session:
            async with session.post(
                ZEN_CHAT_URL,
                json=payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=300)
            ) as resp:
                if resp.status == 200:
                    if stream:
                        # 流式响应
                        response = web.StreamResponse(
                            status=200,
                            headers={
                                "Content-Type": "text/event-stream",
                                "Cache-Control": "no-cache",
                                "Connection": "keep-alive"
                            }
                        )
                        await response.prepare(request)

                        async for chunk in resp.content.iter_any():
                            await response.write(chunk)

                        await response.write_eof()
                        return response
                    else:
                        # 非流式响应
                        data = await resp.json()
                        return web.json_response(data)
                else:
                    error_text = await resp.text()
                    log("chat", f"Error {resp.status}: {error_text[:200]}")
                    return web.json_response(
                        {"error": f"Upstream error: {resp.status}", "details": error_text[:500]},
                        status=resp.status
                    )
    except Exception as e:
        log("chat", f"Exception: {e}")
        return web.json_response(
            {"error": str(e)},
            status=500
        )


async def handle_request(request: web.Request) -> web.Response:
    """处理所有请求"""
    path = request.path

    # 健康检查
    if path == "/health":
        return web.json_response({
            "ok": True,
            "provider": "opencode-zen-proxy",
            "base_url": ZEN_BASE_URL,
            "models": sorted(FREE_MODELS)
        })

    # 模型列表
    if path == "/v1/models":
        return await handle_models(request)

    # 聊天请求
    if path == "/v1/chat/completions":
        return await handle_chat(request)

    # 默认响应
    return web.json_response({
        "message": "OpenCode Zen Free Model Proxy",
        "endpoints": {
            "models": "/v1/models",
            "chat": "/v1/chat/completions",
            "health": "/health"
        }
    })


async def main() -> None:
    app = web.Application(client_max_size=64 * 1024 * 1024)
    app.router.add_route("*", "/{tail:.*}", handle_request)

    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, HOST, PORT)
    await site.start()

    log("service", f"listening on http://{HOST}:{PORT}")

    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


def _is_port_in_use(port: int) -> bool:
    """connect-probe: bind-test misjudges on Windows when proxy listens on 0.0.0.0."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(1.0)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False
# 日志目录（供模块导入时使用，避免 NameError）
LOG_DIR = Path.cwd() / "_zen_proxy_logs"


def run_standalone_and_wait():
    """供外部 subprocess 调用的入口：启动 proxy 并阻塞等待。"""
    print_banner()
    asyncio.run(main())


# 供 web 面板调用的启动函数：若端口空闲则在独立进程中启动
def ensure_proxy_running(port: int | None = None) -> dict:
    """确保 OpenCode Zen 免费代理在运行。
    返回: {"running": bool, "port": int, "reason": str}
    """
    import sys
    p = int(port or int(os.environ.get("PORT", "18508")))
    if _is_port_in_use(p):
        return {"running": True, "port": p, "reason": "已有实例在运行"}
    # 用当前 Python 解释器启动一个独立子进程
    py = sys.executable
    script = __file__
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env["PORT"] = str(p)
    try:
        subprocess.Popen(
            [py, script],
            env=env,
            stdout=open(os.path.join(LOG_DIR, "proxy.log"), "w", encoding="utf-8") 
                 if os.path.isdir(LOG_DIR) else subprocess.DEVNULL,
            stderr=subprocess.STDOUT,
            creationflags=0x00000008 | 0x00000200 | 0x08000000,  # DETACHED | NEW_GROUP | NO_WINDOW
        )
        return {"running": True, "port": p, "reason": "已启动"}
    except Exception:
        try:
            # 某些环境不支持 creationflags
            subprocess.Popen([py, script], env=env)
            return {"running": True, "port": p, "reason": "已启动(fallback)"}
        except Exception as exc:
            return {"running": False, "port": p, "reason": str(exc)}


if __name__ == "__main__":
    print_banner()
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nbye.")
