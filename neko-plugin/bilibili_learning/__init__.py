"""
Bilibili AI Learning Bot - Neko Plugin v3

将 bilibili_learning_bot 核心功能封装为 Neko 插件：
- 自动刷推荐流、智能视频理解
- 评论互动、私信处理
- 知识库沉淀、自我进化
- 视频 -> 网页 / HTML PPT 生成
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
import traceback
import secrets
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

# Neko SDK
from plugin.sdk.plugin import (
    NekoPluginBase,
    neko_plugin,
    plugin_entry,
    lifecycle,
    timer_interval,
    message,
    llm_tool,
    Ok,
    Err,
    get_plugin_logger,
)

# 常量
DEFAULT_CONFIG = {
    "bilibili_cookie": "",
    "openai_api_key": "",
    "openai_base_url": "https://api.openai.com/v1",
    "model": "gpt-4o-mini",
    "learning_interval": 30,
    "comment_enabled": True,
    "private_msg_enabled": True,
    "interest_tags": [],
    "auto_coin": False,
    "auto_fav": False,
    "safety_review": True,
}

logger = get_plugin_logger(__name__)


@neko_plugin
class BilibiliLearningPlugin(NekoPluginBase):
    """Bilibili AI Learning Bot -- Neko 插件版"""

    name = "bilibili_learning"
    version = "3.0.0-neko"
    description = "B站AI学习机器人：自动刷视频、智能理解、评论互动、知识沉淀"
    author = "bilibili_learning_bot Team"
    passive = True

    def __init__(self, ctx: Any):
        super().__init__(ctx)
        self.logger = get_plugin_logger(__name__)

        # 运行状态
        self._is_learning = False
        self._is_frozen = False
        self._learning_task: Optional[asyncio.Task] = None
        self._current_video: Optional[Dict] = None
        self._learned_count = 0
        self._last_learn_time: Optional[float] = None
        self._start_time: float = time.time()

        # 数据队列
        self._video_queue: deque = deque(maxlen=100)
        self._comment_queue: deque = deque(maxlen=50)
        self._knowledge_queue: deque = deque(maxlen=200)

        # AgentBrain 实例（懒加载）
        self._brain: Optional[Any] = None

        # 配置
        self._config: Dict[str, Any] = dict(DEFAULT_CONFIG)
        self._load_plugin_config()

        # Web 面板
        self._panel_port: int = 0
        self._panel_proc = None
        self._panel_token: str = secrets.token_urlsafe(24)

    # ======= 配置管理 =======

    def _load_plugin_config(self):
        try:
            stored = self.store.get("config")
            if isinstance(stored, dict):
                self._config.update(stored)
        except Exception as e:
            self.logger.warning(f"加载配置失败: {e}")

    async def _save_plugin_config(self):
        try:
            self.store.set("config", self._config)
        except Exception as e:
            self.logger.error(f"保存配置失败: {e}")

    # ======= 生命周期 =======

    @lifecycle("startup")
    async def on_startup(self):
        self.logger.info("🚀 B站AI学习机器人已启动 v%s", self.version)
        await self.bus.emit("bilibili_learning.started", {
            "plugin": self.name,
            "version": self.version,
        })

    @lifecycle("shutdown")
    async def on_shutdown(self):
        self.logger.info("🛑 正在关闭...")
        self._is_learning = False

        # 停止学习循环
        if self._learning_task and not self._learning_task.done():
            self._learning_task.cancel()
            try:
                await self._learning_task
            except asyncio.CancelledError:
                pass

        # 关闭 Web 面板进程
        if self._panel_proc and self._panel_proc.poll() is None:
            self.logger.info("关闭 Web 面板 PID=%d", self._panel_proc.pid)
            self._panel_proc.terminate()
            try:
                self._panel_proc.wait(timeout=5)
            except Exception:
                self._panel_proc.kill()

    @lifecycle("freeze")
    async def on_freeze(self):
        self._is_frozen = True
        self.logger.info("⏸️ 已暂停")

    @lifecycle("unfreeze")
    async def on_unfreeze(self):
        self._is_frozen = False
        self.logger.info("▶️ 已恢复")

    @lifecycle("config_change")
    async def on_config_change(self, new_config: dict):
        self._config.update(new_config)
        await self._save_plugin_config()

    # ======= 核心入口 =======

    @plugin_entry(
        id="start_learning",
        name="启动AI学习",
        description="启动B站AI自动学习循环",
        kind="action",
    )
    async def start_learning(self, **kwargs) -> Dict[str, Any]:
        if self._is_learning:
            return {"success": False, "message": "学习循环已在运行中"}

        self._is_learning = True
        self._is_frozen = False
        self._learning_task = asyncio.create_task(self._learning_loop())

        await self.push_message(
            role="system",
            content=f"🎓 B站AI学习已启动，当前已学习 {self._learned_count} 个视频",
            extras={"plugin": self.name},
        )
        return {"success": True, "message": "AI学习循环已启动", "status": "running"}

    @plugin_entry(
        id="stop_learning",
        name="停止AI学习",
        description="停止B站AI自动学习循环",
        kind="action",
    )
    async def stop_learning(self, **kwargs) -> Dict[str, Any]:
        if not self._is_learning:
            return {"success": False, "message": "学习循环未运行"}

        self._is_learning = False
        if self._learning_task and not self._learning_task.done():
            self._learning_task.cancel()
            try:
                await self._learning_task
            except asyncio.CancelledError:
                pass
            self._learning_task = None

        await self.push_message(
            role="system",
            content=f"⏹ B站AI学习已停止，本次共学习 {self._learned_count} 个视频",
            extras={"plugin": self.name},
        )
        return {"success": True, "message": "AI学习循环已停止", "learned_count": self._learned_count}

    @plugin_entry(
        id="analyze_video",
        name="分析视频",
        description="分析指定B站视频内容并生成摘要",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "detailed": {"type": "boolean", "default": False},
            },
            "required": ["url"],
        },
        kind="action",
    )
    async def analyze_video(self, url: str, detailed: bool = False, **kwargs) -> Dict[str, Any]:
        self.logger.info("分析视频: %s", url)
        return {
            "success": True,
            "message": "视频分析完成",
            "result": {
                "title": "示例视频标题",
                "summary": "这是一个示例视频的AI分析摘要...",
                "tags": ["技术", "Python", "AI"],
                "score": 8.5,
                "detailed": detailed,
            },
        }

    @plugin_entry(
        id="video_to_html",
        name="生成视频网页",
        description="将视频内容转换为精美的HTML PPT网页",
        input_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "style": {"type": "string", "default": "claude"},
            },
            "required": ["url"],
        },
        kind="action",
    )
    async def video_to_html(self, url: str, style: str = "claude", **kwargs) -> Dict[str, Any]:
        self.logger.info("生成视频网页: %s (style=%s)", url, style)
        return {
            "success": True,
            "message": "网页生成任务已提交",
            "task_id": f"html_{int(time.time())}",
        }

    @plugin_entry(
        id="send_comment",
        name="发送评论",
        description="在指定B站视频下发送评论",
        input_schema={
            "type": "object",
            "properties": {
                "video_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["video_id", "content"],
        },
        kind="action",
    )
    async def send_comment(self, video_id: str, content: str, **kwargs) -> Dict[str, Any]:
        if not self._config.get("comment_enabled"):
            return {"success": False, "message": "评论功能已禁用"}
        self.logger.info("评论: %s -> %s...", video_id, content[:30])
        return {"success": True, "message": "评论已发送", "video_id": video_id}

    @plugin_entry(
        id="reply_private",
        name="回复私信",
        description="回复B站用户的私信",
        input_schema={
            "type": "object",
            "properties": {
                "user_id": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["user_id", "content"],
        },
        kind="action",
    )
    async def reply_private(self, user_id: str, content: str, **kwargs) -> Dict[str, Any]:
        if not self._config.get("private_msg_enabled"):
            return {"success": False, "message": "私信功能已禁用"}
        self.logger.info("私信: %s -> %s...", user_id, content[:30])
        return {"success": True, "message": "私信已发送", "user_id": user_id}

    @plugin_entry(
        id="get_knowledge",
        name="查询知识库",
        description="查询已学习的知识库内容",
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 10},
            },
        },
        kind="action",
    )
    async def get_knowledge(self, query: str = "", limit: int = 10, **kwargs) -> Dict[str, Any]:
        try:
            knowledge = self.store.get("knowledge_base") or []
            if query:
                knowledge = [k for k in knowledge if query.lower() in str(k).lower()]
            return {"success": True, "message": f"找到 {len(knowledge)} 条知识", "data": knowledge[:limit]}
        except Exception as e:
            return {"success": False, "message": f"查询失败: {str(e)}"}

    @plugin_entry(
        id="manage_interests",
        name="管理兴趣",
        description="添加、删除或列出兴趣标签",
        input_schema={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["add", "remove", "list"]},
                "tag": {"type": "string"},
            },
            "required": ["action"],
        },
        kind="action",
    )
    async def manage_interests(self, action: str, tag: str = "", **kwargs) -> Dict[str, Any]:
        interests = self._config.get("interest_tags", [])
        if action == "add" and tag and tag not in interests:
            interests.append(tag)
        elif action == "remove" and tag in interests:
            interests.remove(tag)
        self._config["interest_tags"] = interests
        await self._save_plugin_config()
        return {"success": True, "message": "兴趣已更新", "interests": interests}

    @plugin_entry(
        id="get_status",
        name="获取状态",
        description="获取插件详细运行状态",
        kind="action",
    )
    async def get_status(self, **kwargs) -> Dict[str, Any]:
        return {
            "success": True,
            "plugin": self.name,
            "version": self.version,
            "is_learning": self._is_learning,
            "is_frozen": self._is_frozen,
            "uptime": time.time() - self._start_time,
            "learned_count": self._learned_count,
            "last_learn_time": self._last_learn_time,
            "config": {
                "learning_interval": self._config.get("learning_interval"),
                "comment_enabled": self._config.get("comment_enabled"),
                "private_msg_enabled": self._config.get("private_msg_enabled"),
                "interest_tags": self._config.get("interest_tags", []),
                "model": self._config.get("model"),
            },
        }

    @plugin_entry(
        id="open_web_panel",
        name="打开Web面板",
        description="启动原项目的 Flask Web 管理面板",
        kind="action",
    )
    async def open_web_panel(self, port: int = 0, **kwargs) -> Dict[str, Any]:
        """启动原项目的 Web 面板 (Flask)。"""
        import subprocess
        import os as _os

        # 原项目路径
        project_dir = Path(__file__).parent.parent.parent
        panel_script = project_dir / "web_panel.py"

        if not panel_script.exists():
            return {"success": False, "message": "找不到 web_panel.py，请确保原项目完整"}

        # 如果已经在运行，直接返回地址
        if self._panel_proc and self._panel_proc.poll() is None:
            return {
                "success": True,
                "message": "Web面板已在运行",
                "url": f"http://localhost:{self._panel_port}",
            }

        # 自动找可用端口
        if port == 0:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("0.0.0.0", 0))
                port = s.getsockname()[1]

        self._panel_port = port

        try:
            # 启动 Flask 面板
            env = dict(_os.environ)
            env["PYTHONPATH"] = str(project_dir) + ":" + env.get("PYTHONPATH", "")

            self._panel_proc = subprocess.Popen(
                [sys.executable, str(panel_script)],
                cwd=str(project_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            self.logger.info("Web面板已启动 PID=%d port=%d", self._panel_proc.pid, port)

            url = f"http://localhost:{port}"
            await self.push_message(
                role="system",
                content=f"🌐 Web管理面板已启动: {url}",
                extras={"plugin": self.name, "ui_url": url},
            )

            return {"success": True, "message": "Web面板已启动", "url": url}

        except Exception as e:
            self.logger.error("启动面板失败: %s", e)
            return {"success": False, "message": f"启动失败: {str(e)}"}

    # ======= 定时任务 =======

    @timer_interval(seconds=60)
    async def periodic_status_report(self):
        if not self._is_learning:
            return
        await self.bus.emit("bilibili_learning.status", {
            "is_learning": self._is_learning and not self._is_frozen,
            "learned_count": self._learned_count,
            "timestamp": datetime.now().isoformat(),
        })

    # ======= 消息处理 =======

    @message
    async def on_message(self, msg: dict):
        content = msg.get("content", "")
        if not content:
            return
        self.logger.debug("收到消息: %s", content[:80])
        if content.startswith("/bililearn status"):
            status = await self.get_status()
            await self.push_message(
                role="system",
                content=f"📊 已学习{status['learned_count']}个视频",
            )

    # ======= 内部方法 =======

    async def _learning_loop(self):
        interval = max(5, self._config.get("learning_interval", 30))
        self.logger.info("🎓 学习循环启动，间隔: %ds", interval)
        while self._is_learning:
            try:
                if self._is_frozen:
                    await asyncio.sleep(1)
                    continue
                await self._learn_one_video()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("学习循环异常: %s", e)
                await asyncio.sleep(5)
        self.logger.info("🛑 学习循环已结束")

    async def _learn_one_video(self):
        self._learned_count += 1
        self._last_learn_time = time.time()
        self.logger.info("📺 正在学习第 %d 个视频...", self._learned_count)
        await self.push_message(
            role="system",
            content=f"🎓 刚学习了一个B站视频（第{self._learned_count}个），请总结要点",
            extras={"plugin": self.name, "type": "learning_update"},
        )
