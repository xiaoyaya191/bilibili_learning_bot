# -*- coding: utf-8 -*-
"""内置 Agent 工具集：B站 / 知识库 / 记忆 / 系统。

写操作全部走 xingye_bot/bilibili_ops 的安全层（dry_run、审核队列、
涉政过滤、全局开关），Agent 无法绕过 —— 这是安全底线。
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from agent.registry import tool

_CLIENT = None
_OPS = None


def _data_dir() -> Path:
    from core.user_data import DATA_DIR
    return DATA_DIR


def _get_client():
    """面板进程自己的 BiliClient（凭证从磁盘读，与 bot 进程互不干扰）。"""
    global _CLIENT
    if _CLIENT is None:
        from api.client import BiliClient
        _CLIENT = BiliClient()
    return _CLIENT


def _get_ops():
    global _OPS
    if _OPS is None:
        from xingye_bot.bilibili_ops import BilibiliAccount
        _OPS = BilibiliAccount()
    return _OPS


# ═══════════════ 只读工具 ═══════════════

@tool(
    name="get_my_status",
    description="查看我的B站账号状态：登录态、昵称、精力/预算（今日已投币）、运行统计。",
    parameters={"type": "object", "properties": {}, "required": []},
    risk="read", category="builtin:bili",
)
async def get_my_status() -> dict:
    out = {}
    try:
        st = await _get_ops().status()
        out["account"] = {
            "logged_in": bool(st.get("logged_in")),
            "username": st.get("username") or st.get("uname") or "",
            "mid": st.get("mid") or st.get("uid"),
            "coins": st.get("coins") or st.get("money"),
        }
    except Exception as exc:
        out["account"] = {"error": str(exc)[:120]}
    try:
        from services.coin_budget import coins_today
        out["budget"] = {"coins_today": coins_today()}
    except Exception:
        out["budget"] = {"coins_today": "unknown"}
    return {"ok": True, **out}


@tool(
    name="get_recommendations",
    description="获取B站推荐视频流（默认10条）。返回标题/UP主/时长/播放量等。用于发现感兴趣的内容。",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "数量 1-20，默认 10"}},
        "required": [],
    },
    risk="read", category="builtin:bili",
)
async def get_recommendations(limit: int = 10) -> dict:
    limit = max(1, min(int(limit), 20))
    items = await _get_ops().recommended_videos(limit=limit)
    return {"ok": True, "count": len(items), "videos": items}


@tool(
    name="search_videos",
    description="按关键词搜索B站视频，返回最相关的结果（标题/UP主/简介片段/链接）。",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "搜索关键词"},
            "limit": {"type": "integer", "description": "数量 1-15，默认 8"},
        },
        "required": ["keyword"],
    },
    risk="read", category="builtin:bili",
)
async def search_videos(keyword: str, limit: int = 8) -> dict:
    limit = max(1, min(int(limit), 15))
    res = await _get_client().search_bilibili(keyword, limit=limit)
    if isinstance(res, dict):
        items = res.get("result") or res.get("data") or res.get("videos") or []
    else:
        items = res or []
    return {"ok": True, "count": len(items), "results": items}


@tool(
    name="get_video_info",
    description="获取视频详情：标题、简介、UP主、播放/点赞/投币/收藏/弹幕数、时长、标签。输入 BV号。",
    parameters={
        "type": "object",
        "properties": {"bvid": {"type": "string", "description": "视频BV号，如 BV1xx411c7mD"}},
        "required": ["bvid"],
    },
    risk="read", category="builtin:bili",
)
async def get_video_info(bvid: str) -> dict:
    meta = await _get_client()._get_video_meta(bvid)
    keep = ("bvid", "aid", "title", "desc", "owner", "duration",
            "stat", "data", "tname", "pubdate", "tags")
    info = {k: v for k, v in meta.items() if k in keep} if meta else {}
    return {"ok": bool(info), "video": info or meta}


@tool(
    name="get_video_comments",
    description="获取视频热门评论（默认10条），了解大家怎么看这个视频。",
    parameters={
        "type": "object",
        "properties": {
            "bvid": {"type": "string"},
            "limit": {"type": "integer", "description": "1-20，默认 10"},
        },
        "required": ["bvid"],
    },
    risk="read", category="builtin:bili",
)
async def get_video_comments(bvid: str, limit: int = 10) -> dict:
    limit = max(1, min(int(limit), 20))
    meta = await _get_client()._get_video_meta(bvid)
    aid = meta.get("aid")
    if not aid:
        return {"ok": False, "error": "找不到视频 aid"}
    items = await _get_client().get_hot_comments(aid, limit=limit)
    return {"ok": True, "count": len(items), "comments": items}


@tool(
    name="get_video_danmakus",
    description="获取视频弹幕（默认40条），感受观众实时反应。",
    parameters={
        "type": "object",
        "properties": {
            "bvid": {"type": "string"},
            "limit": {"type": "integer", "description": "1-100，默认 40"},
        },
        "required": ["bvid"],
    },
    risk="read", category="builtin:bili",
)
async def get_video_danmakus(bvid: str, limit: int = 40) -> dict:
    limit = max(1, min(int(limit), 100))
    items = await _get_client().get_danmakus(bvid, limit=limit)
    return {"ok": True, "count": len(items), "danmakus": items}


@tool(
    name="get_up_info",
    description="获取UP主主页信息：粉丝数、投稿数、签名等。输入 UID。",
    parameters={
        "type": "object",
        "properties": {"uid": {"type": "integer", "description": "UP主 UID"}},
        "required": ["uid"],
    },
    risk="read", category="builtin:bili",
)
async def get_up_info(uid: int) -> dict:
    info = await _get_client().get_up_info(int(uid))
    return {"ok": True, "up": info}


@tool(
    name="get_up_videos",
    description="获取UP主最近的投稿列表（默认10条），评估TA的内容质量。",
    parameters={
        "type": "object",
        "properties": {
            "uid": {"type": "integer"},
            "limit": {"type": "integer", "description": "1-20，默认 10"},
        },
        "required": ["uid"],
    },
    risk="read", category="builtin:bili",
)
async def get_up_videos(uid: int, limit: int = 10) -> dict:
    limit = max(1, min(int(limit), 20))
    items = await _get_client().get_up_videos(int(uid), limit=limit)
    return {"ok": True, "count": len(items), "videos": items}


@tool(
    name="check_mentions",
    description="查看谁回复/AT了我的评论和动态（默认20条），用于互动与回复。",
    parameters={
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "1-50，默认 20"}},
        "required": [],
    },
    risk="read", category="builtin:bili",
)
async def check_mentions(limit: int = 20) -> dict:
    limit = max(1, min(int(limit), 50))
    items = await _get_ops().recent_replies_to_me(limit=limit)
    return {"ok": True, "count": len(items), "mentions": items}


@tool(
    name="kb_search",
    description="在本地知识库（过往学习归档的视频笔记）中按关键词搜索，返回命中的文件与片段。",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string"},
            "limit": {"type": "integer", "description": "最多返回条数，默认 5"},
        },
        "required": ["keyword"],
    },
    risk="read", category="builtin:kb",
)
async def kb_search(keyword: str, limit: int = 5) -> dict:
    from core.user_data import KNOWLEDGE_BASE_DIR
    hits = []
    if KNOWLEDGE_BASE_DIR.exists():
        for f in sorted(KNOWLEDGE_BASE_DIR.rglob("*.md"))[:400]:
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            idx = text.find(keyword)
            if idx >= 0:
                start = max(0, idx - 60)
                hits.append({
                    "file": f.name,
                    "snippet": text[start: idx + len(keyword) + 160].replace("\n", " "),
                })
                if len(hits) >= max(1, min(int(limit), 20)):
                    break
    return {"ok": True, "keyword": keyword, "hits": hits}


@tool(
    name="memory_search",
    description="在长期记忆（MemoryBank）中搜索过往记忆条目。",
    parameters={
        "type": "object",
        "properties": {
            "keyword": {"type": "string", "description": "为空则返回最近记忆"},
            "limit": {"type": "integer", "description": "默认 10"},
        },
        "required": [],
    },
    risk="read", category="builtin:memory",
)
async def memory_search(keyword: str = "", limit: int = 10) -> dict:
    from xingye_bot.memory import MemoryBank
    bank = MemoryBank()
    try:
        items = bank.list_permanent(limit=200)
    except Exception:
        items = []
    if keyword:
        items = [m for m in items if keyword in json.dumps(m, ensure_ascii=False)]
    return {"ok": True, "count": len(items[: int(limit)]), "memories": items[: int(limit)]}


# ═══════════════ 写操作工具（走安全层）═══════════════

@tool(
    name="video_interact",
    description="对视频执行互动：like点赞 / coin投1枚币 / favorite收藏进默认收藏夹 / comment发评论(text)。受面板安全策略与审核队列约束。",
    parameters={
        "type": "object",
        "properties": {
            "bvid": {"type": "string"},
            "action": {"type": "string", "enum": ["like", "coin", "favorite", "comment"],
                       "description": "互动类型"},
            "text": {"type": "string", "description": "评论内容（action=comment 时必填）"},
        },
        "required": ["bvid", "action"],
    },
    risk="write", category="builtin:bili",
)
async def video_interact(bvid: str, action: str, text: str = "", dry_run: bool = False, allow_write: bool = True) -> dict:
    res = await _get_ops().video_action(
        bvid=bvid, action=action, text=text,
        dry_run=not allow_write or bool(dry_run),
        allow_comment=allow_write, allow_like=allow_write,
        allow_coin=allow_write, allow_favorite=allow_write,
    )
    return {"ok": bool(res.get("executed")), "detail": res}


@tool(
    name="reply_comment",
    description="回复一条评论（oid=视频aid, root=根评论rpid, parent=被回复评论rpid, text=回复内容）。受安全策略约束。",
    parameters={
        "type": "object",
        "properties": {
            "oid": {"type": "integer", "description": "视频 aid"},
            "root": {"type": "integer", "description": "根评论 rpid"},
            "parent": {"type": "integer", "description": "被回复评论 rpid"},
            "text": {"type": "string"},
        },
        "required": ["oid", "root", "parent", "text"],
    },
    risk="write", category="builtin:bili",
)
async def reply_comment(oid: int, root: int, parent: int, text: str, allow_write: bool = True) -> dict:
    res = await _get_ops().send_comment_reply(
        int(oid), int(root), int(parent), text,
        dry_run=not allow_write, allow_comment=allow_write,
    )
    return {"ok": bool(res.get("executed")), "detail": res}


@tool(
    name="follow_up",
    description="关注一位UP主（uid）。取关用 unfollow。",
    parameters={
        "type": "object",
        "properties": {"uid": {"type": "integer"}},
        "required": ["uid"],
    },
    risk="write", category="builtin:bili",
)
async def follow_up(uid: int) -> dict:
    res = await _get_client().follow_up(int(uid))
    return {"ok": True, "detail": res}


@tool(
    name="kb_add",
    description="把一段学到的知识写入知识库存档，需要标题和内容。",
    parameters={
        "type": "object",
        "properties": {
            "title": {"type": "string", "description": "笔记标题"},
            "content": {"type": "string", "description": "笔记正文（markdown）"},
        },
        "required": ["title", "content"],
    },
    risk="write", category="builtin:kb",
)
async def kb_add(title: str, content: str) -> dict:
    from core.user_data import KNOWLEDGE_BASE_DIR
    KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    safe = "".join(c for c in title if c not in '\\/:*?"<>|').strip()[:60] or "笔记"
    f = KNOWLEDGE_BASE_DIR / ("Agent-" + time.strftime("%Y%m%d-%H%M%S-") + safe + ".md")
    f.write_text(
        "# " + title + "\n\n> 由 Agent 模式归档于 " + time.strftime("%Y-%m-%d %H:%M")
        + "\n\n" + content + "\n",
        encoding="utf-8",
    )
    return {"ok": True, "file": f.name}


@tool(
    name="memory_write",
    description="写入一条长期记忆（事实/偏好/经验教训），供以后的所有会话使用。",
    parameters={
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "记忆内容，一句话说清楚"},
            "kind": {"type": "string", "enum": ["fact", "preference", "lesson"],
                     "description": "事实/偏好/经验教训"},
        },
        "required": ["content"],
    },
    risk="write", category="builtin:memory",
)
async def memory_write(content: str, kind: str = "fact") -> dict:
    from xingye_bot.memory import MemoryBank
    bank = MemoryBank()
    for meth, kwargs in (
        ("add_permanent", {"text": content}),
        ("add", {"content": content}),
        ("save", {"content": content}),
    ):
        fn = getattr(bank, meth, None)
        if fn:
            fn(**kwargs)
            return {"ok": True, "via": meth}
    return {"ok": False, "error": "MemoryBank 无可用写入方法"}


@tool(
    name="finish",
    description="任务完成时必须调用：提交最终总结（做了什么/学到什么/结论），会话即结束。",
    parameters={
        "type": "object",
        "properties": {
            "summary": {"type": "string", "description": "本次任务的完整总结"},
            "outcome": {"type": "string", "enum": ["done", "partial", "blocked"],
                        "description": "done=完成 partial=部分 blocked=受阻"},
        },
        "required": ["summary"],
    },
    risk="read", category="builtin:system",
)
async def finish(summary: str, outcome: str = "done") -> dict:
    return {"ok": True, "finished": True, "summary": summary, "outcome": outcome}


BUILTIN_TOOLS_LOADED = True
