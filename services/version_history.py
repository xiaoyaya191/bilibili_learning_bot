"""知识笔记多版本记录工具。"""
from __future__ import annotations

import difflib
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any


def save_note_version(note_path: str | os.PathLike[str], content: str, cfg: dict[str, Any] | None = None) -> dict[str, str]:
    """在正式写入前保存一份历史版本，并可生成 diff。"""
    opts = (cfg or {}).get("version_history", {}) if isinstance(cfg, dict) else {}
    if not opts.get("enabled", False):
        return {}

    path = Path(note_path)
    max_versions = max(1, int(opts.get("max_versions", 5) or 5))
    versions_dir = path.parent / ".versions" / path.stem
    versions_dir.mkdir(parents=True, exist_ok=True)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    result: dict[str, str] = {}

    if path.exists():
        old_text = path.read_text(encoding="utf-8", errors="replace")
        old_version = versions_dir / f"{ts}_previous.md"
        shutil.copy2(path, old_version)
        result["previous"] = str(old_version)

        if opts.get("diff_on_regenerate", True):
            diff_text = "\n".join(difflib.unified_diff(
                old_text.splitlines(),
                content.splitlines(),
                fromfile="previous",
                tofile="new",
                lineterm="",
            ))
            diff_path = versions_dir / f"{ts}.diff"
            diff_path.write_text(diff_text, encoding="utf-8")
            result["diff"] = str(diff_path)
    else:
        new_version = versions_dir / f"{ts}_initial.md"
        new_version.write_text(content, encoding="utf-8")
        result["initial"] = str(new_version)

    versions = sorted(versions_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in versions[max_versions:]:
        try:
            old.unlink()
        except Exception:
            pass

    return result
