"""知识库工具模块 — 供 MCP Server 暴露知识库查询/搜索/导出能力。

复用项目现有的 scan_md_files 扫描与知识库目录解析逻辑，
所有路径访问都限制在当前配置的知识库根目录内，防止路径穿越。
"""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any

from core.config import load_config, resolve_knowledge_base_dir
from services.knowledge_tutor import scan_md_files

MAX_SEARCH_FILE_BYTES = 2 * 1024 * 1024  # 超过 2MB 的文件跳过全文搜索


def _kb_dir() -> Path:
    """load_config → resolve_knowledge_base_dir，解析当前知识库根目录。"""
    return Path(resolve_knowledge_base_dir(load_config())).resolve()


def _find_entry(rel_path: str) -> tuple[Path, dict[str, Any]] | None:
    """按 rel_path 精确匹配，或按 bvid 兜底匹配，返回 (文件路径, 条目元数据)。"""
    root = _kb_dir()
    raw = str(rel_path or "").strip().replace("\\", "/")
    if not raw:
        return None
    items = scan_md_files(root)
    for it in items:
        if str(it.get("rel_path", "")).replace("\\", "/") == raw:
            return Path(it["file_path"]), it
    for it in items:
        bvid = str(it.get("bvid") or "")
        if bvid and bvid.lower() == raw.lower():
            return Path(it["file_path"]), it
    return None


def kb_stats() -> dict:
    """知识库统计：总条目数、分类明细、根目录路径。"""
    root = _kb_dir()
    items = scan_md_files(root)
    categories: dict[str, int] = {}
    for it in items:
        cat = str(it.get("category_path") or "未分类")
        categories[cat] = categories.get(cat, 0) + 1
    return {
        "total_files": len(items),
        "categories": categories,
        "kb_dir": str(root),
    }


def kb_list(query: str = "", category: str = "", limit: int = 50, offset: int = 0) -> dict:
    """分页列出知识库条目；query 模糊匹配 title/up_name/bvid，category 前缀匹配。"""
    items = scan_md_files(_kb_dir())
    q = str(query or "").strip().lower()
    cat = str(category or "").strip().replace("\\", "/").rstrip("/")
    if q:
        items = [
            it for it in items
            if q in str(it.get("title", "")).lower()
            or q in str(it.get("up_name", "")).lower()
            or q in str(it.get("bvid", "")).lower()
        ]
    if cat:
        items = [
            it for it in items
            if str(it.get("category_path", "")).replace("\\", "/").startswith(cat)
        ]
    total = len(items)
    start = max(int(offset or 0), 0)
    size = max(int(limit or 0), 0)
    page = [
        {
            "bvid": it.get("bvid", ""),
            "title": it.get("title", ""),
            "rel_path": it.get("rel_path", ""),
            "category_path": it.get("category_path", ""),
            "up_name": it.get("up_name", ""),
            "size_kb": it.get("size_kb", 0),
        }
        for it in items[start:start + size]
    ]
    return {"total": total, "items": page, "offset": start}


def kb_read(rel_path: str = "") -> str:
    """读取一篇知识笔记的完整 Markdown 内容（支持 rel_path 或 bvid）。"""
    root = _kb_dir()
    raw = str(rel_path or "").strip().replace("\\", "/")
    if not raw:
        raise ValueError("rel_path 不能为空：请传入条目的 rel_path 或 bvid")
    target = (root / raw).resolve()
    if not target.is_relative_to(root):
        raise ValueError(f"非法路径（禁止越出知识库目录）: {rel_path}")
    if not target.is_file():
        found = _find_entry(raw)
        if found is None:
            raise FileNotFoundError(f"知识库中不存在: {rel_path}")
        target, _meta = found
    return target.read_text(encoding="utf-8", errors="replace")


def kb_search(query: str, limit: int = 20) -> dict:
    """全文粗排搜索：收集文件内容中包含关键词的行，返回命中摘录。"""
    q = str(query or "").strip().lower()
    if not q:
        return {"total": 0, "results": []}
    hits: list[dict[str, Any]] = []
    for it in scan_md_files(_kb_dir()):
        fp = Path(it.get("file_path") or "")
        try:
            if not fp.is_file() or fp.stat().st_size > MAX_SEARCH_FILE_BYTES:
                continue
            raw = fp.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:8192]:  # 二进制文件跳过
            continue
        text = raw.decode("utf-8", errors="ignore")
        matched = [line for line in text.splitlines() if q in line.lower()]
        if not matched:
            continue
        hits.append(
            {
                "rel_path": it.get("rel_path", ""),
                "title": it.get("title", ""),
                "excerpt": max(matched, key=len).strip()[:200],
                "hit_lines": len(matched),
            }
        )
    hits.sort(key=lambda h: h["hit_lines"], reverse=True)
    for h in hits:
        del h["hit_lines"]
    size = max(int(limit or 0), 0)
    return {"total": len(hits), "results": hits[:size]}


def _export_entry(rel_path: str, fmt: str, out: Path) -> dict:
    raw = str(rel_path or "").strip().replace("\\", "/")
    if not raw:
        return {"ok": False, "error": "target=entry 时 rel_path 必填"}
    if fmt not in ("md", "json"):
        return {"ok": False, "error": f"不支持的格式: {fmt}（单条导出仅支持 md/json）"}
    found = _find_entry(raw)
    if found is None:
        return {"ok": False, "error": f"知识库中不存在: {rel_path}"}
    src, meta = found
    out.parent.mkdir(parents=True, exist_ok=True)
    if fmt == "md":
        shutil.copyfile(src, out)
    else:
        payload = {
            "bvid": meta.get("bvid", ""),
            "title": meta.get("title", ""),
            "rel_path": meta.get("rel_path", ""),
            "category_path": meta.get("category_path", ""),
            "up_name": meta.get("up_name", ""),
            "size_kb": meta.get("size_kb", 0),
            "content": src.read_text(encoding="utf-8", errors="replace"),
        }
        out.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return {"ok": True, "path": str(out), "files": 1, "size_bytes": out.stat().st_size}


def _export_all(fmt: str, out: Path) -> dict:
    if fmt != "zip":
        return {"ok": False, "error": f"不支持的格式: {fmt}（全库导出仅支持 zip）"}
    files = scan_md_files(_kb_dir())
    if not files:
        return {"ok": False, "error": "知识库为空，没有可导出的文件"}
    out.parent.mkdir(parents=True, exist_ok=True)
    added = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for item in files:
            fp = Path(item.get("file_path") or "")
            if not fp.is_file():
                continue
            rel = item.get("rel_path") or fp.name
            arcname = str(Path("知识库") / rel)
            archive.write(str(fp), arcname)
            added += 1
    if added == 0:
        return {"ok": False, "error": "知识库中没有可导出的文件"}
    return {"ok": True, "path": str(out), "files": added, "size_bytes": out.stat().st_size}


def kb_export(
    target: str = "all",
    rel_path: str = "",
    fmt: str = "zip",
    output_path: str = "",
) -> dict:
    """导出知识库到本地文件：单条（md/json）或全库 zip。"""
    try:
        out_raw = str(output_path or "").strip()
        if not out_raw:
            return {"ok": False, "error": "output_path 不能为空"}
        out = Path(out_raw).expanduser()
        mode = str(target or "all").strip().lower()
        f = str(fmt or "zip").strip().lower()
        if mode == "entry":
            return _export_entry(rel_path, f, out)
        if mode == "all":
            return _export_all(f, out)
        return {"ok": False, "error": f"不支持的 target: {target}（仅支持 entry/all）"}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}
