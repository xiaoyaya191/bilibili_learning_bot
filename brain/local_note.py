"""Local evidence-note fallback used when the configured AI is unavailable."""

from __future__ import annotations

import re


def build_local_subtitle_note(
    subtitle_text: str,
    video_desc: str = "",
    *,
    excerpt_chars: int = 1800,
) -> str:
    """Preserve representative source excerpts without presenting them as AI output."""
    clean = re.sub(r"\s+", " ", subtitle_text or "").strip()
    if not clean:
        return ""

    excerpt_chars = max(300, int(excerpt_chars))
    if len(clean) <= excerpt_chars:
        excerpts = [("完整字幕", clean)]
    else:
        part_size = max(100, excerpt_chars // 3)
        starts = (0, max(0, len(clean) // 2 - part_size // 2), max(0, len(clean) - part_size))
        labels = ("开头摘录", "中段摘录", "结尾摘录")
        excerpts = [(label, clean[start:start + part_size]) for label, start in zip(labels, starts)]

    parts = [
        "> [!WARNING] 本条为 AI 服务不可用时生成的本地降级归档，以下内容是原始字幕摘录，不是 AI 总结或事实核验结果。",
    ]
    if video_desc:
        parts.extend(("", "### 视频简介（原始材料）", "", video_desc.strip()[:1000]))
    parts.extend(("", "### 原始字幕摘录"))
    for label, excerpt in excerpts:
        parts.extend(("", f"#### {label}", "", excerpt))
    parts.extend(("", "### 后续处理", "", "AI 服务恢复后，可在知识库重温功能中重新总结和分类本条记录。"))
    return "\n".join(parts).strip()
