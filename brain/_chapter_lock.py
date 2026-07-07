"""章节锁定 + 内容追加算法。

用于长视频笔记：先锁定章节大纲，再逐章追加内容，避免一次性总结导致细节丢失。
"""
from __future__ import annotations

import math
from typing import Any, Awaitable, Callable


AiCall = Callable[..., Awaitable[Any]]


def _estimate_minutes(text: str) -> float:
    """按字幕文本长度粗略估算视频时长，缺少真实 duration 时作为 fallback。"""
    clean = (text or "").strip()
    if not clean:
        return 0.0
    return max(1.0, len(clean) / 420.0)


def should_use_chapter_lock(subtitle_text: str, cfg: dict[str, Any]) -> bool:
    opts = cfg.get("chapter_lock", {}) if isinstance(cfg, dict) else {}
    if not opts.get("enabled", True):
        return False
    min_minutes = float(opts.get("min_duration_minutes", 15) or 15)
    return _estimate_minutes(subtitle_text) >= min_minutes


def _chunk_text(text: str, max_chunks: int) -> list[str]:
    text = (text or "").strip()
    if not text:
        return []
    max_chunks = max(1, min(int(max_chunks or 8), 20))
    chunk_size = max(1800, math.ceil(len(text) / max_chunks))
    chunks = []
    for start in range(0, len(text), chunk_size):
        part = text[start:start + chunk_size].strip()
        if part:
            chunks.append(part)
    return chunks[:max_chunks]


async def generate_chapter_locked_note(
    *,
    ai_call: AiCall,
    model: str,
    system_prompt: str,
    title: str,
    up: str,
    url: str,
    subtitle_text: str,
    video_desc: str = "",
    cfg: dict[str, Any] | None = None,
) -> str:
    """生成章节锁定笔记。ai_call 兼容 AgentBrain._call_ai_with_retry。"""
    opts = (cfg or {}).get("chapter_lock", {}) if isinstance(cfg, dict) else {}
    max_chapters = int(opts.get("max_chapters_per_video", 12) or 12)
    strategy = opts.get("chapter_strategy", "ai_split")
    chunks = _chunk_text(subtitle_text, max_chapters)
    if not chunks:
        return ""

    outline_prompt = f"""请为以下视频字幕生成锁定章节大纲。

要求：
1. 只输出 Markdown 章节大纲。
2. 每章包含：章节标题、估计时间段、核心问题。
3. 后续内容只能按此大纲追加，不要反复改写章节结构。
4. 章节数不超过 {max_chapters}。
5. 切分策略：{strategy}。

视频标题：{title}
UP主：{up}
链接：{url}
{('简介：' + video_desc) if video_desc else ''}

字幕节选：
{subtitle_text[:8000]}"""

    outline_resp = await ai_call(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": outline_prompt},
        ],
    )
    outline = (outline_resp.choices[0].message.content or "").strip()

    note_parts = [
        "## 🎯 长视频章节锁定笔记\n",
        "> 本笔记采用“章节锁定 + 内容追加”流程生成：先固定章节大纲，再逐章补充知识点，减少长视频信息遗漏。\n",
        "### 锁定章节大纲\n",
        outline,
        "\n---\n",
        "## 📌 逐章内容追加\n",
    ]

    for idx, chunk in enumerate(chunks, start=1):
        append_prompt = f"""已有锁定章节大纲如下，请不要改写大纲结构，只基于当前字幕片段追加本章内容。

【锁定大纲】
{outline}

【当前字幕片段 {idx}/{len(chunks)}】
{chunk}

请输出：
- 本片段对应章节
- 核心知识点
- 关键论据/案例/数据
- 可执行启发
- 必要的时间线提示（如能从文本判断）

注意：只追加新内容，不要重写前文。"""
        resp = await ai_call(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": append_prompt},
            ],
        )
        content = (resp.choices[0].message.content or "").strip()
        note_parts.append(f"\n### 追加片段 {idx}/{len(chunks)}\n\n{content}\n")

    return "\n".join(note_parts).strip()
