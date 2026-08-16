"""BiliLearn MCP Server — stdio 传输，注册 3 个工具。

协议纪律：stdout 仅供 MCP JSON-RPC 通信，日志一律走 stderr。
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from mcp_server import bili as bili_mod
from mcp_server import script as script_mod
from mcp_server import kb as kb_mod

logger = logging.getLogger(__name__)

server = Server("bili-learn-mcp")

TOOL_MATERIAL = "bili_video_material"
TOOL_SEARCH = "bili_search_videos"
TOOL_SCRIPT = "bili_video_to_script"
TOOL_KB_STATS = "kb_stats"
TOOL_KB_LIST = "kb_list"
TOOL_KB_READ = "kb_read"
TOOL_KB_SEARCH = "kb_search"
TOOL_KB_EXPORT = "kb_export"


@server.list_tools()
async def list_tools() -> list[Tool]:
    return [
        Tool(
            name=TOOL_MATERIAL,
            description=(
                "提取 Bilibili 视频的文案素材：元数据（标题/UP/时长/数据/简介/分P）+ "
                "字幕全文 + 弹幕精选 + 热门评论，输出结构化 Markdown。"
                "适合写视频文案、做二创、总结视频内容。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Bilibili 视频链接，支持 BV 号、av 号、完整 URL",
                    },
                    "include_danmaku": {
                        "type": "boolean",
                        "description": "是否包含弹幕精选，默认 true",
                    },
                    "include_comments": {
                        "type": "boolean",
                        "description": "是否包含热门评论，默认 true",
                    },
                    "include_timestamps": {
                        "type": "boolean",
                        "description": "字幕/弹幕是否保留时间戳，默认 false",
                    },
                    "danmaku_limit": {
                        "type": "integer",
                        "description": "弹幕条数上限，默认 500",
                    },
                    "comment_limit": {
                        "type": "integer",
                        "description": "评论条数上限，默认 30",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name=TOOL_SEARCH,
            description=(
                "搜索 Bilibili 视频，返回结构化列表（标题/BV/UP/播放量/时长/简介）。"
                "适合找参考视频、找选题素材。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "搜索关键词"},
                    "limit": {
                        "type": "integer",
                        "description": "最多返回条数，默认 8",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name=TOOL_SCRIPT,
            description=(
                "根据 Bilibili 视频素材，用项目配置的 AI 一键生成视频文案/口播稿。"
                "支持多种风格：口播/解说/种草/盘点/故事/干货。"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "Bilibili 视频链接",
                    },
                    "style": {
                        "type": "string",
                        "enum": ["口播", "解说", "种草", "盘点", "故事", "干货"],
                        "description": "文案风格，默认口播",
                    },
                    "target_words": {
                        "type": "integer",
                        "description": "目标字数，默认 800",
                    },
                    "extra_hint": {
                        "type": "string",
                        "description": "额外要求（目标受众/平台/语气等），可选",
                    },
                },
                "required": ["url"],
            },
        ),
        Tool(
            name=TOOL_KB_STATS,
            description="获取B站学习知识库统计：总条目数、全部分类及每类数量、根目录路径",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name=TOOL_KB_LIST,
            description="分页列出知识库学习笔记条目",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "模糊匹配标题/UP主/bvid，可选",
                    },
                    "category": {
                        "type": "string",
                        "description": "分类路径前缀过滤，可选",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "每页条数，默认 50",
                    },
                    "offset": {
                        "type": "integer",
                        "description": "分页偏移，默认 0",
                    },
                },
            },
        ),
        Tool(
            name=TOOL_KB_READ,
            description="读取一篇知识笔记的完整 Markdown 内容",
            inputSchema={
                "type": "object",
                "properties": {
                    "rel_path": {
                        "type": "string",
                        "description": "条目的 rel_path 或 bvid",
                    },
                },
                "required": ["rel_path"],
            },
        ),
        Tool(
            name=TOOL_KB_SEARCH,
            description="全文搜索知识库，返回命中摘录",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "搜索关键词",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "最多返回条数，默认 20",
                    },
                },
                "required": ["query"],
            },
        ),
        Tool(
            name=TOOL_KB_EXPORT,
            description=(
                "导出知识库到本地文件：单条(md/json)或全库zip，供其他工具/Agent 使用"
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "enum": ["entry", "all"],
                        "description": "导出范围，默认 all",
                    },
                    "rel_path": {
                        "type": "string",
                        "description": "target=entry 时必填，条目的 rel_path 或 bvid",
                    },
                    "fmt": {
                        "type": "string",
                        "enum": ["zip", "md", "json"],
                        "description": "导出格式，默认 zip（entry 支持 md/json）",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "本地保存路径（父目录不存在会自动创建）",
                    },
                },
                "required": ["output_path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    try:
        if name == TOOL_MATERIAL:
            markdown = await bili_mod.fetch_material(
                arguments.get("url", ""),
                include_danmaku=bool(arguments.get("include_danmaku", True)),
                include_comments=bool(arguments.get("include_comments", True)),
                include_timestamps=bool(arguments.get("include_timestamps", False)),
                danmaku_limit=int(arguments.get("danmaku_limit", 500)),
                comment_limit=int(arguments.get("comment_limit", 30)),
            )
            return [TextContent(type="text", text=markdown)]

        if name == TOOL_SEARCH:
            videos = await bili_mod.search_videos(
                arguments.get("query", ""),
                limit=int(arguments.get("limit", 8)),
            )
            if not videos:
                return [TextContent(type="text", text="未找到相关视频。")]
            lines = ["# B站搜索结果", ""]
            for v in videos:
                lines.append(
                    f"## {v.get('title', '')}\n"
                    f"- **BV**：{v.get('bvid', '')}\n"
                    f"- **UP 主**：{v.get('author', '')}\n"
                    f"- **播放**：{v.get('play', 0):,} · **时长**：{v.get('duration', '')}\n"
                    f"- **简介**：{v.get('description', '')}\n"
                    f"- **链接**：https://www.bilibili.com/video/{v.get('bvid', '')}\n"
                )
            return [TextContent(type="text", text="\n".join(lines))]

        if name == TOOL_SCRIPT:
            script = await script_mod.generate_script(
                arguments.get("url", ""),
                style=arguments.get("style", "口播"),
                target_words=int(arguments.get("target_words", 800)),
                extra_hint=arguments.get("extra_hint", ""),
            )
            return [TextContent(type="text", text=script)]

        if name == TOOL_KB_STATS:
            stats = kb_mod.kb_stats()
            return [TextContent(type="text", text=json.dumps(stats, ensure_ascii=False))]

        if name == TOOL_KB_LIST:
            listing = kb_mod.kb_list(
                arguments.get("query", ""),
                category=arguments.get("category", ""),
                limit=int(arguments.get("limit", 50)),
                offset=int(arguments.get("offset", 0)),
            )
            return [TextContent(type="text", text=json.dumps(listing, ensure_ascii=False))]

        if name == TOOL_KB_READ:
            content = kb_mod.kb_read(arguments.get("rel_path", ""))
            return [TextContent(type="text", text=content)]

        if name == TOOL_KB_SEARCH:
            found = kb_mod.kb_search(
                arguments.get("query", ""),
                limit=int(arguments.get("limit", 20)),
            )
            return [TextContent(type="text", text=json.dumps(found, ensure_ascii=False))]

        if name == TOOL_KB_EXPORT:
            exported = kb_mod.kb_export(
                arguments.get("target", "all"),
                rel_path=arguments.get("rel_path", ""),
                fmt=arguments.get("fmt", "zip"),
                output_path=arguments.get("output_path", ""),
            )
            return [TextContent(type="text", text=json.dumps(exported, ensure_ascii=False))]

        raise ValueError(f"未知工具: {name}")
    except Exception as exc:  # noqa: BLE001
        logger.error("%s 失败: %s", name, exc)
        return [TextContent(type="text", text=f"{exc}")]


async def _run_server() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        stream=sys.stderr,
    )
    asyncio.run(_run_server())


if __name__ == "__main__":
    main()
