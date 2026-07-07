"""Markdown → Markmap 思维导图 HTML 导出。"""
from __future__ import annotations

import asyncio
import html
import json
import os
import re
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = BASE_DIR / "MindMaps"


def _sanitize_filename(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|]+', "_", name or "mindmap")
    return name.strip(" .")[:120] or "mindmap"


def _trim_markdown(markdown: str, max_depth: int = 3, include_images: bool = True, max_images: int = 16) -> str:
    """抽取适合思维导图的层级结构。

    - 保留 #~###### 标题（受 max_depth 限制）
    - 保留要点列表（含内联图片）
    - include_images=True 时，把正文中独立的图片行作为「当前标题」的子节点保留，
      实现文字+图片结合的导图节点（上限 max_images 张，避免 base64 过大拖慢渲染）
    """
    lines = []
    max_depth = max(1, int(max_depth or 3))
    cur_depth = None
    img_count = 0
    MAX_LINES = 800
    for line in (markdown or "").splitlines():
        if len(lines) >= MAX_LINES:
            break
        m = re.match(r'^(#{1,6})\s+(.+)$', line)
        if m:
            depth = len(m.group(1))
            if depth <= max_depth:
                lines.append(f"{'#' * depth} {m.group(2).strip()}")
                cur_depth = depth
            else:
                cur_depth = None
            continue
        # 保留要点列表（含其中的内联图片）
        if line.strip().startswith(("- ", "* ")):
            lines.append(line)
            continue
        # 保留独立图片：作为当前标题的子节点（文字 + 图片结合）
        if include_images and img_count < max_images:
            im = re.match(r'^\s*!\[([^\]]*)\]\((data:[^)\s]+|[^)\s]+)\)', line)
            if im:
                alt = (im.group(1) or "图").strip() or "图"
                url = im.group(2)
                lines.append(f"  - ![ {alt} ]({url})")
                img_count += 1
                continue
    if not lines:
        return "# 知识笔记\n\n- 暂无可用于生成思维导图的标题层级"
    return "\n".join(lines)


async def _ai_outline_async(markdown: str, prompt: str) -> str | None:
    """可选：用配置的提示词把笔记转换为更利于思维导图的大纲（标题层级）。"""
    try:
        from xingye_bot.llm import ModelClient
        from xingye_bot.settings import load_settings
        from xingye_bot.state import BotState
        client = ModelClient(load_settings(), BotState())
        system = (
            "你负责把知识笔记转换为思维导图大纲，只输出 Markdown 标题层级（#/##/###）和要点列表。\n"
            "要求：保留核心知识与逻辑结构，剔除冗余铺垫；不要输出代码块以外的解释文字。\n"
            f"用户附加要求：{prompt}"
        )
        resp = await client.chat(
            [{"role": "system", "content": system}, {"role": "user", "content": markdown[:6000]}],
            model_role="chat", purpose="mindmap_outline",
        )
        if isinstance(resp, str) and resp.strip():
            return resp
        if hasattr(resp, "choices"):
            return resp.choices[0].message.content
    except Exception:
        return None
    return None


def _maybe_ai_outline(markdown: str, prompt: str | None) -> str:
    """在同步/异步上下文中安全地尝试 AI 大纲增强；失败或不可用时回退原始 markdown。"""
    if not prompt:
        return markdown
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            return markdown  # 已在异步循环中，避免嵌套事件循环
    except RuntimeError:
        pass
    try:
        return asyncio.run(_ai_outline_async(markdown, prompt)) or markdown
    except Exception:
        return markdown


def markdown_to_mindmap_html(markdown: str, title: str = "知识思维导图", theme: str = "default", max_depth: int = 3, include_images: bool = True) -> str:
    md = _trim_markdown(markdown, max_depth=max_depth, include_images=include_images)
    safe_title = html.escape(title or "知识思维导图")
    md_json = json.dumps(md, ensure_ascii=False)
    dark = theme == "dark"
    bg = "#0d1117" if dark else "#ffffff"
    fg = "#e6edf3" if dark else "#1f2328"
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{safe_title}</title>
<style>
html,body,#mindmap{{margin:0;width:100%;height:100%;background:{bg};color:{fg};font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;}}
.toolbar{{position:fixed;z-index:10;left:16px;top:16px;background:rgba(127,127,127,.12);backdrop-filter:blur(12px);border:1px solid rgba(127,127,127,.22);border-radius:12px;padding:10px 14px;}}
.toolbar h1{{font-size:15px;margin:0 0 4px 0;}}
.toolbar p{{font-size:12px;margin:0;opacity:.72;}}
/* 导图节点中的图片（文字 + 图片结合） */
foreignObject img{{max-width:200px;max-height:150px;border-radius:8px;display:block;margin:4px 0;box-shadow:0 1px 6px rgba(0,0,0,.15);}}
.markmap-node foreignObject{{overflow:hidden}}
</style>
</head>
<body>
<div class="toolbar"><h1>{safe_title}</h1><p>由 bilibili_learning_bot 自动生成</p></div>
<svg id="mindmap"></svg>
<script src="https://cdn.jsdelivr.net/npm/d3@7"></script>
<script src="https://cdn.jsdelivr.net/npm/markmap-view"></script>
<script src="https://cdn.jsdelivr.net/npm/markmap-lib"></script>
<script>
const markdown = {md_json};
const transformer = new markmap.Transformer();
const {{ root }} = transformer.transform(markdown);
const mm = markmap.Markmap.create('#mindmap', {{ autoFit: true, duration: 500 }}, root);
// 图片异步加载完成后重新自适应，避免文字+图片节点溢出
document.querySelectorAll('foreignObject img').forEach(function(img){{
  img.addEventListener('load', function(){{ try{{ mm.fit(); }}catch(e){{}} }});
}});
</script>
</body>
</html>"""


def export_mindmap(markdown_path: str | os.PathLike[str], output_dir: str | os.PathLike[str] | None = None, cfg: dict[str, Any] | None = None) -> str:
    path = Path(markdown_path)
    if not path.exists():
        raise FileNotFoundError(str(path))
    opts = (cfg or {}).get("mindmap", {}) if isinstance(cfg, dict) else {}
    out_dir = Path(output_dir or opts.get("output_dir") or DEFAULT_OUTPUT_DIR)
    if not out_dir.is_absolute():
        out_dir = BASE_DIR / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = path.read_text(encoding="utf-8", errors="replace")
    # 可选 AI 大纲增强（受 mindmap.prompt 驱动）
    markdown = _maybe_ai_outline(markdown, opts.get("prompt"))
    title = path.stem
    theme = opts.get("theme", "default")
    max_depth = int(opts.get("max_depth", 3) or 3)
    include_images = bool(opts.get("include_images", True))
    html_text = markdown_to_mindmap_html(markdown, title=title, theme=theme, max_depth=max_depth, include_images=include_images)
    out_path = out_dir / f"{_sanitize_filename(title)}.mindmap.html"
    out_path.write_text(html_text, encoding="utf-8")
    return str(out_path)
