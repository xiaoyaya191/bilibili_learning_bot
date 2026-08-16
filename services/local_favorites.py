"""Shared local video-favorite storage for the bot, Web panel, and CLI."""

import json
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path

from core.user_data import DATA_DIR


_LOCK = threading.RLock()


def _path(data_dir=None) -> Path:
    return Path(data_dir or DATA_DIR) / "video_favorites.json"


def read_library(data_dir=None) -> dict:
    path = _path(data_dir)
    with _LOCK:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    folders = data.get("folders") if isinstance(data, dict) else []
    items = data.get("items") if isinstance(data, dict) else []
    return {
        "folders": [item for item in folders or [] if isinstance(item, dict)],
        "items": [item for item in items or [] if isinstance(item, dict)],
    }


def write_library(data: dict, data_dir=None) -> None:
    path = _path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "folders": list(data.get("folders") or []),
        "items": list(data.get("items") or []),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _LOCK:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)


def new_folder(name: str) -> dict:
    return {
        "id": uuid.uuid4().hex[:12],
        "name": str(name or "").strip()[:60],
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "managed_by": "local_ai_and_user",
    }


def add_video(folder_name: str, video: dict, *, source="AI 自动精选", data_dir=None) -> dict:
    """Create the folder when needed and add one deduplicated local video card."""
    bvid = str(video.get("bvid") or "").strip()
    if not bvid.startswith("BV"):
        return {"added": False, "reason": "invalid_bvid"}
    with _LOCK:
        library = read_library(data_dir)
        folder = next(
            (item for item in library["folders"] if str(item.get("name") or "").casefold() == folder_name.casefold()),
            None,
        )
        if folder is None:
            folder = new_folder(folder_name)
            library["folders"].append(folder)
        existing = next(
            (
                item for item in library["items"]
                if str(item.get("folder_id")) == str(folder["id"])
                and str(item.get("bvid")) == bvid
            ),
            None,
        )
        if existing is not None:
            return {"added": False, "reason": "duplicate", "folder": folder}
        item = {
            "folder_id": folder["id"],
            "bvid": bvid,
            "added_at": datetime.now().isoformat(timespec="seconds"),
            "source": str(source or "AI 自动精选")[:40],
            "title": str(video.get("title") or "")[:200],
            "up": str(video.get("up") or "")[:100],
            "cover": str(video.get("cover") or video.get("pic") or "")[:1000],
            "duration": video.get("duration") or 0,
            "score": video.get("score") or 0,
            "category": str(video.get("category") or "")[:80],
            "interest_reason": str(video.get("interest_reason") or "")[:500],
            "url": f"https://www.bilibili.com/video/{bvid}",
        }
        library["items"].append(item)
        write_library(library, data_dir)
        return {"added": True, "folder": folder, "item": item}


def auto_collect_video(config: dict, video: dict, *, interested: bool, data_dir=None) -> dict:
    settings = config.get("local_favorites", {}) if isinstance(config, dict) else {}
    if not settings.get("auto_collect_enabled", True):
        return {"added": False, "reason": "disabled"}
    score = float(video.get("score") or 0)
    if score < float(settings.get("min_score", 8.0)):
        return {"added": False, "reason": "score"}
    if settings.get("require_interest_match", True) and not interested:
        return {"added": False, "reason": "interest"}
    folder_name = str(settings.get("folder_name") or "AI 精选").strip() or "AI 精选"
    return add_video(folder_name, video, source="AI 自动精选", data_dir=data_dir)


def backfill_from_history(config: dict, history: dict, *, data_dir=None) -> int:
    """Import eligible legacy rows whose score and view metadata were split."""
    rows = history.get("videos", []) if isinstance(history, dict) else []
    merged = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        bvid = str(row.get("bvid") or "").strip()
        if not bvid.startswith("BV"):
            continue
        card = merged.setdefault(bvid, {"bvid": bvid, "score": 0})
        for key in ("title", "up", "pic", "cover", "duration", "category", "interest_reason"):
            if row.get(key) not in (None, ""):
                card[key] = row[key]
        try:
            card["score"] = max(float(card.get("score") or 0), float(row.get("score") or 0))
        except (TypeError, ValueError):
            pass
        result = str(row.get("result") or "")
        if any(word in result for word in ("跳过", "不匹配", "拦截")):
            card["rejected"] = True
        if row.get("action") in {"like", "fav"}:
            card["interaction_interest"] = True

    added = 0
    for card in merged.values():
        interested = bool(card.get("interest_reason") or card.get("interaction_interest"))
        if card.get("rejected"):
            interested = False
        result = auto_collect_video(config, card, interested=interested, data_dir=data_dir)
        added += int(bool(result.get("added")))
    return added


# ── AI 自动归类（复用知识库分类体系，只取分类结果不写知识库）──
async def classify_favorite_item(item: dict, *, data_dir=None) -> str:
    """对单个收藏夹视频做 AI 归类，返回分类路径（如 '编程/Web开发'）。

    复用知识库 KnowledgeBaseClassifier._find_best_category（纯 AI 判断），
    只取分类字符串，不往知识库 file_index 写记录。
    """
    bvid = str(item.get("bvid") or "").strip()
    title = str(item.get("title") or "").strip()
    if not bvid.startswith("BV") or not title:
        return str(item.get("ai_category") or "未分类")
    try:
        from knowledge.classifier import KnowledgeBaseClassifier
        classifier = KnowledgeBaseClassifier()
        existing = classifier._get_all_categories()
        ai_result = await classifier._find_best_category(title, "", existing)
        selected = str(ai_result.get("selected_category") or "未分类").strip()
        if ai_result.get("is_new"):
            selected = selected or "未分类"
        if float(ai_result.get("confidence") or 0) < 0.3:
            selected = "未分类"
        return selected[:120] or "未分类"
    except Exception:
        return str(item.get("ai_category") or "未分类")


async def classify_all_favorites(data_dir=None) -> dict:
    """批量对收藏夹里所有未归类（或缺归类）视频做 AI 归类，写回本地收藏库。"""
    library = read_library(data_dir)
    updated = 0
    for item in library.get("items") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("ai_category") or "").strip():
            continue
        category = await classify_favorite_item(item, data_dir=data_dir)
        item["ai_category"] = category
        item["ai_category_at"] = datetime.now().isoformat(timespec="seconds")
        updated += 1
    if updated:
        write_library(library, data_dir)
    return {"ok": True, "updated": updated, "total": len(library.get("items") or [])}
