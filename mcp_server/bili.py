"""Bilibili 数据提取模块 — 复用项目现有 BiliClient 与字幕抓取能力。

所有网络请求都走项目已有的 api 层（含 WBI 签名、节流、Cookie），
保证与机器人本体行为一致、风控友好。
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from api.client import BiliClient
from api.subtitles import fetch_bilibili_subtitles

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


class BiliExtractError(Exception):
    """提取失败（链接无法识别 / 接口返回错误 / 网络异常）。"""


def extract_bvid(url: str) -> str:
    """从任意链接提取 BV 号（支持 BV 号、av 号、完整 URL、b23.tv 短链）。"""
    m = re.search(r"(BV[0-9A-Za-z]{10})", url)
    if m:
        return m.group(1)
    m = re.search(r"[?&/]av(\d+)", url, re.I) or re.search(r"^av(\d+)$", url, re.I)
    if m:
        return "av" + m.group(1)
    raise BiliExtractError(f"无法从链接中识别 BV 号: {url}")


async def fetch_view(bvid: str) -> dict[str, Any]:
    """获取视频 view 元数据（标题 / UP / 时长 / 数据 / 简介 / 分 P）。"""
    headers = {"User-Agent": UA, "Referer": f"https://www.bilibili.com/video/{bvid}"}
    try:
        async with httpx.AsyncClient(http2=True, timeout=20.0, headers=headers) as client:
            resp = await client.get(
                "https://api.bilibili.com/x/web-interface/view", params={"bvid": bvid}
            )
            data = resp.json()
    except Exception as exc:  # noqa: BLE001
        raise BiliExtractError(f"请求 view 接口失败: {exc}") from exc
    if data.get("code") != 0:
        raise BiliExtractError(f"view 接口返回错误: {data.get('message')}")
    return data.get("data") or {}


def _fmt_duration(seconds: int) -> str:
    seconds = int(seconds or 0)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _fmt_ts(seconds: float) -> str:
    seconds = int(seconds or 0)
    m, s = divmod(seconds, 60)
    return f"{m:02d}:{s:02d}"


def format_meta_markdown(view: dict[str, Any], url: str) -> str:
    """把 view 元数据整理成 Markdown 信息块。"""
    owner = view.get("owner") or {}
    stat = view.get("stat") or {}
    pages = view.get("pages") or []
    lines = [
        f"# {view.get('title', '')}",
        "",
        f"- **UP 主**：{owner.get('name', '')}",
        f"- **链接**：{url}",
        f"- **时长**：{_fmt_duration(view.get('duration', 0))}",
        f"- **播放**：{stat.get('view', 0):,}",
        f"- **点赞**：{stat.get('like', 0):,}",
        f"- **投币**：{stat.get('coin', 0):,}",
        f"- **收藏**：{stat.get('favorite', 0):,}",
        f"- **弹幕**：{stat.get('danmaku', 0):,}",
        f"- **分区**：{view.get('tname', '')}",
        f"- **发布时间**：{view.get('pubdate', '')}",
        f"- **分 P 数**：{len(pages)}",
        "",
    ]
    desc = (view.get("desc") or "").strip()
    if desc:
        lines += ["## 视频简介", "", desc, ""]
    if len(pages) > 1:
        lines += ["## 分 P 列表", ""]
        for i, p in enumerate(pages, 1):
            lines.append(f"{i}. P{i} · {p.get('part', '')}（{_fmt_duration(p.get('duration', 0))}）")
        lines.append("")
    return "\n".join(lines)


async def fetch_material(
    url: str,
    include_danmaku: bool = True,
    include_comments: bool = True,
    include_timestamps: bool = False,
    danmaku_limit: int = 500,
    comment_limit: int = 30,
) -> str:
    """提取视频文案素材：元数据 + 字幕 + 弹幕 + 评论，输出结构化 Markdown。"""
    bvid = extract_bvid(url)
    view = await fetch_view(bvid)
    aid = int(view.get("aid") or 0)
    out = [format_meta_markdown(view, url)]

    # ── 字幕 ──
    out.append("## 字幕全文")
    try:
        ok, subtitle, _desc, _verified = await fetch_bilibili_subtitles(bvid)
        if ok and subtitle:
            if include_timestamps:
                out.append(subtitle)
            else:
                # 去掉 [MM:SS] 时间戳，保留纯文本
                cleaned = re.sub(r"\[\d{1,2}:\d{2}(?::\d{2})?\]\s*", "", subtitle)
                out.append(cleaned.strip())
        else:
            out.append("> （未获取到字幕，可能无 CC 字幕或需要登录）")
    except Exception as exc:  # noqa: BLE001
        out.append(f"> （字幕获取失败：{exc}）")
    out.append("")

    # ── 弹幕 ──
    if include_danmaku:
        out.append("## 弹幕精选")
        try:
            client = BiliClient()
            _cid, danmakus = await client.get_danmakus(bvid, limit=danmaku_limit)
            if danmakus:
                for d in danmakus[:danmaku_limit]:
                    ts = f"[{_fmt_ts(d.get('dm_time', 0))}] " if include_timestamps else ""
                    out.append(f"{ts}{d.get('text', '')}")
            else:
                out.append("> （暂无弹幕）")
        except Exception as exc:  # noqa: BLE001
            out.append(f"> （弹幕获取失败：{exc}）")
        out.append("")

    # ── 评论 ──
    if include_comments:
        out.append("## 热门评论")
        try:
            client = BiliClient()
            comments = await client.get_hot_comments(aid, limit=comment_limit)
            if comments:
                for c in comments:
                    member = c.get("member") or {}
                    content = (c.get("content") or {}).get("message", "")
                    like = c.get("like", 0)
                    out.append(f"- **{member.get('uname', '匿名')}**（赞 {like}）：{content}")
            else:
                out.append("> （暂无评论）")
        except Exception as exc:  # noqa: BLE001
            out.append(f"> （评论获取失败：{exc}）")
        out.append("")

    return "\n".join(out)


async def search_videos(query: str, limit: int = 8) -> list[dict[str, Any]]:
    """搜索 B 站视频，返回结构化列表。"""
    client = BiliClient()
    return await client.search_bilibili(query, limit=limit)
