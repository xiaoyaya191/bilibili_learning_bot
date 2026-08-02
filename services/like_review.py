"""Persistent review inbox for AI-proposed actions.

The legacy LikeReviewInbox name remains as a compatibility wrapper. Review
records contain only the minimum action payload and never credentials.
"""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path

_LOCK = threading.RLock()

ACTION_TYPES = {
    "video_like": {"label": "视频点赞", "scope": "platform", "default": True},
    "follow_up": {"label": "关注 UP 主", "scope": "platform", "default": True},
    "unfollow_user": {"label": "取消关注用户", "scope": "platform", "default": True},
    "send_danmaku": {"label": "发送弹幕", "scope": "platform", "default": True},
    "public_comment": {"label": "公开评论/回复", "scope": "platform", "default": True, "disabled": True},
    "private_reply": {"label": "私信回复", "scope": "platform", "default": True},
    "coin": {"label": "投币", "scope": "platform", "default": True},
    "favorite": {"label": "收藏视频", "scope": "platform", "default": True},
    "knowledge_write": {"label": "写入知识库", "scope": "local", "default": False},
    "file_export": {"label": "生成或导出文件", "scope": "local", "default": False},
}


def default_review_settings() -> dict:
    return {
        "enabled": True,
        "desktop_notification": True,
        "action_types": {key: bool(meta["default"]) for key, meta in ACTION_TYPES.items()},
    }


def review_settings(config: dict | None) -> dict:
    result = default_review_settings()
    source = (config or {}).get("approval_review", {})
    if isinstance(source, dict):
        result["enabled"] = source.get("enabled", True) is not False
        result["desktop_notification"] = source.get("desktop_notification", True) is not False
        selected = source.get("action_types", {})
        if isinstance(selected, dict):
            for key in ACTION_TYPES:
                if key in selected:
                    result["action_types"][key] = bool(selected[key])
    return result


def requires_review(config: dict | None, action_type: str) -> bool:
    settings = review_settings(config)
    return bool(settings["enabled"] and settings["action_types"].get(action_type, False))


class ActionReviewInbox:
    def __init__(self, data_dir):
        data_dir = Path(data_dir)
        self.path = data_dir / "approval_review_inbox.json"
        self.legacy_path = data_dir / "like_review_inbox.json"
        self.audit_path = data_dir / "approval_review_audit.jsonl"

    def _read(self) -> list[dict]:
        try:
            rows = json.loads(self.path.read_text(encoding="utf-8"))
            return rows if isinstance(rows, list) else []
        except Exception:
            rows = []
        if not self.path.exists() and self.legacy_path.exists():
            try:
                legacy = json.loads(self.legacy_path.read_text(encoding="utf-8"))
                for row in legacy if isinstance(legacy, list) else []:
                    row = dict(row)
                    row.setdefault("action_type", "video_like")
                    row.setdefault("payload", {"bvid": row.get("bvid", "")})
                    row.setdefault("summary", row.get("reason", ""))
                    row.setdefault("scope", "platform")
                    rows.append(row)
                if rows:
                    self._write(rows)
            except Exception:
                pass
        return rows

    def _write(self, rows: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def _current_account_uid(self) -> str:
        try:
            cookies = json.loads((self.path.parent / "bilibili_cookies.json").read_text(encoding="utf-8"))
            return str((cookies or {}).get("DedeUserID") or "").strip()
        except (OSError, json.JSONDecodeError, AttributeError):
            return ""

    def _audit(self, event: str, row: dict, **details) -> dict:
        """Append an immutable, credential-free history entry for one review."""
        entry = {
            "time": datetime.now().isoformat(timespec="seconds"),
            "event": event,
            "item_id": row.get("id", ""),
            "action_type": row.get("action_type", ""),
            "action_label": row.get("action_label", ""),
            "title": str(row.get("title") or "")[:180],
            "status": row.get("status", ""),
        }
        for key, value in details.items():
            if value not in (None, ""):
                entry[key] = value
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return entry

    def audit(self, limit: int = 200) -> list[dict]:
        try:
            lines = self.audit_path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return []
        entries = []
        for line in lines[-max(1, min(int(limit), 1000)):]:
            try:
                item = json.loads(line)
                if isinstance(item, dict):
                    entries.append(item)
            except json.JSONDecodeError:
                continue
        return list(reversed(entries))

    def clear_audit(self) -> int:
        """Clear execution history without changing pending or decided review items."""
        with _LOCK:
            try:
                count = len(self.audit_path.read_text(encoding="utf-8").splitlines())
            except OSError:
                count = 0
            try:
                self.audit_path.parent.mkdir(parents=True, exist_ok=True)
                self.audit_path.write_text("", encoding="utf-8")
            except OSError:
                return 0
        return count

    def propose(self, action_type: str, title: str, summary: str = "", payload: dict | None = None,
                metadata: dict | None = None, dedupe_key: str = "") -> dict | None:
        if action_type not in ACTION_TYPES:
            raise ValueError(f"未知审核行为: {action_type}")
        payload = dict(payload or {})
        metadata = dict(metadata or {})
        dedupe_key = dedupe_key or f"{action_type}:{json.dumps(payload, ensure_ascii=False, sort_keys=True)}"
        with _LOCK:
            rows = self._read()
            if any(row.get("dedupe_key") == dedupe_key and row.get("status") == "pending" for row in rows):
                return None
            row = {
                "id": uuid.uuid4().hex,
                "action_type": action_type,
                "action_label": ACTION_TYPES[action_type]["label"],
                "scope": ACTION_TYPES[action_type]["scope"],
                "title": str(title or ACTION_TYPES[action_type]["label"])[:180],
                "summary": str(summary or "")[:500],
                "payload": payload,
                "metadata": metadata,
                "account_uid": self._current_account_uid(),
                "dedupe_key": dedupe_key,
                "status": "pending",
                "created_at": datetime.now().isoformat(timespec="seconds"),
            }
            rows.append(row)
            self._write(rows)
            try:
                config = json.loads((self.path.parent / "config.json").read_text(encoding="utf-8"))
                notify_enabled = (config.get("approval_review") or {}).get("desktop_notification", True)
                if notify_enabled is not False:
                    from utils.desktop_notifications import enqueue
                    enqueue(self.path.parent, "BiliLearn approval needed", f"{row['action_label']}: {row['title']}")
            except (OSError, json.JSONDecodeError):
                pass
            return row

    def cancel_pending_for_account_switch(self, previous_uid: str, next_uid: str) -> int:
        """Never let an action proposed for one account run on another."""
        with _LOCK:
            rows = self._read()
            cancelled = 0
            for row in rows:
                if row.get("status") != "pending":
                    continue
                row["status"] = "cancelled_account_switch"
                row["cancelled_at"] = datetime.now().isoformat(timespec="seconds")
                row["cancelled_reason"] = "Bilibili account changed"
                self._audit(
                    "cancelled_account_switch", row,
                    previous_uid=str(previous_uid), next_uid=str(next_uid),
                )
                cancelled += 1
            if cancelled:
                self._write(rows)
            return cancelled

    def list(self, status: str = "", action_type: str = "") -> list[dict]:
        with _LOCK:
            rows = list(reversed(self._read()))
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if action_type:
            rows = [row for row in rows if row.get("action_type") == action_type]
        return rows

    def decide(self, item_id: str, status: str) -> dict | None:
        with _LOCK:
            rows = self._read()
            for row in rows:
                if row.get("id") == item_id and row.get("status") == "pending":
                    row["status"] = status
                    row["decided_at"] = datetime.now().isoformat(timespec="seconds")
                    self._write(rows)
                    self._audit(status, row, decision_at=row["decided_at"])
                    return dict(row)
        return None

    def update(self, item_id: str, **fields) -> dict | None:
        with _LOCK:
            rows = self._read()
            for row in rows:
                if row.get("id") == item_id:
                    row.update(fields)
                    self._write(rows)
                    status = fields.get("status")
                    if status in {"executed", "failed"}:
                        self._audit(
                            status,
                            row,
                            execution=fields.get("execution"),
                            error=fields.get("error"),
                        )
                    return dict(row)
        return None


class LikeReviewInbox(ActionReviewInbox):
    """Compatibility facade used by the existing video loop."""

    def propose(self, bvid, title, up_name, score, reason, url=""):
        return super().propose(
            "video_like",
            title,
            reason,
            payload={"bvid": str(bvid)},
            metadata={"up_name": up_name, "score": score, "url": url},
            dedupe_key=f"video_like:{bvid}",
        )
