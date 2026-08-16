from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime
from typing import Any


def _run_async_safe(coro):
    """在子线程中安全运行异步协程（Windows兼容）"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        # 已有运行中的loop，创建新loop在新线程中执行
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(asyncio.run, coro)
            future.result(timeout=60)
    else:
        asyncio.run(coro)


class BackgroundService:
    def __init__(self, runtime):
        self.runtime = runtime
        self.thread: threading.Thread | None = None
        self.stop_flag = threading.Event()
        self.started_at = ""

    def start(self) -> dict[str, Any]:
        if self.thread and self.thread.is_alive():
            return self.status()
        self.stop_flag.clear()
        self.started_at = datetime.now().isoformat(timespec="seconds")
        print("[background] 启动后台任务", flush=True)
        self.thread = threading.Thread(target=self._loop, name="bilibili-learning-bot-background", daemon=True)
        self.thread.start()
        return self.status()

    def stop(self) -> dict[str, Any]:
        self.stop_flag.set()
        print("[background] 请求停止后台任务", flush=True)
        return self.status()

    def status(self) -> dict[str, Any]:
        return {
            "running": bool(self.thread and self.thread.is_alive()),
            "stop_requested": self.stop_flag.is_set(),
            "started_at": self.started_at,
        }

    def _loop(self) -> None:
        last_cookie_check = 0.0
        last_plan_check = 0.0
        last_comment_check = 0.0
        while not self.stop_flag.is_set():
            now = time.time()
            try:
                if now - last_cookie_check > 6 * 3600:
                    try:
                        asyncio.run(self._cookie_check())
                    except Exception as exc:
                        print(f"[background] cookie检查异常: {exc!r}", flush=True)
                    last_cookie_check = now
                if now - last_plan_check > 60:
                    try:
                        asyncio.run(self.runtime.proactive.execute_due_once())
                    except Exception as exc:
                        print(f"[background] 计划执行异常: {exc!r}", flush=True)
                    last_plan_check = now
                interval = max(60, int(getattr(self.runtime.settings, "comment_poll_interval", 300)))
                if now - last_comment_check > interval:
                    try:
                        _run_async_safe(self.runtime.proactive.poll_comments(limit=getattr(self.runtime.settings, "max_replies_per_check", 3)))
                    except Exception as exc:
                        print(f"[background] 评论轮询异常: {exc!r}", flush=True)
                    last_comment_check = now
            except Exception as exc:
                print(f"[background] 后台任务出错: {exc!r}", flush=True)
                self.runtime.proactive.record("background.error", {"error": repr(exc)}, executed=False)
            self.stop_flag.wait(5)

    async def _cookie_check(self) -> None:
        status = await self.runtime.bili.status()
        if status.get("refresh_needed") and status.get("refresh_available"):
            await self.runtime.bili.refresh()
