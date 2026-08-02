"""Local, auditable research records for video-based studies."""
from __future__ import annotations

import csv
import io
import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.RLock()
_TS = re.compile(r"(?:Screenshot|Content)-\[(\d{1,2}):(\d{2})\]")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class ResearchArchive:
    def __init__(self, data_dir: Path):
        self.path = Path(data_dir) / "research_archive.json"

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"schema_version": 1, "projects": [], "records": []}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            data.setdefault("projects", [])
            data.setdefault("records", [])
            return data
        except (OSError, json.JSONDecodeError):
            return {"schema_version": 1, "projects": [], "records": []}

    def _write(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def projects(self) -> list[dict[str, Any]]:
        with _LOCK:
            return self._read()["projects"]

    def create_project(self, name: str, description: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        name = (name or "").strip()
        if not name:
            raise ValueError("项目名称不能为空")
        with _LOCK:
            data = self._read()
            project = {"id": uuid.uuid4().hex, "name": name, "description": (description or "").strip(),
                       "tags": [str(x).strip() for x in (tags or []) if str(x).strip()], "created_at": _now()}
            data["projects"].append(project)
            self._write(data)
            return project

    def save_visual_note(self, result: dict[str, Any], subtitles: str = "", project_id: str = "") -> dict[str, Any]:
        markdown = result.get("markdown") or ""
        evidence = []
        seen = set()
        for minute, second in _TS.findall(markdown):
            seconds = int(minute) * 60 + int(second)
            if seconds not in seen:
                seen.add(seconds)
                source_url = result.get("url", "")
                separator = "&" if "?" in source_url else "?"
                evidence.append({"timestamp_seconds": seconds, "timestamp": f"{int(minute):02d}:{int(second):02d}",
                                 "source_url": f"{source_url}{separator}t={seconds}" if source_url else "",
                                 "screenshot_marker": f"Screenshot-[{int(minute):02d}:{int(second):02d}]",
                                 "material_type": "原始视频画面"})
        record = {"id": uuid.uuid4().hex, "project_id": project_id, "created_at": _now(),
                  "source": {"platform": "bilibili", "title": result.get("title", ""), "author": result.get("up_name", ""),
                             "url": result.get("url", ""), "accessed_at": _now()},
                  "materials": {"original_subtitles": subtitles, "ai_generated_note": markdown,
                                "notice": "原始字幕和视频画面属于原始材料；图文笔记、摘要和结论均为 AI 生成或 AI 推断，必须回查证据后引用。"},
                  "evidence": evidence, "tags": [], "conclusions": []}
        with _LOCK:
            data = self._read()
            data["records"].append(record)
            self._write(data)
        return record

    def records(self, query: str = "", project_id: str = "") -> list[dict[str, Any]]:
        query = query.strip().lower()
        with _LOCK:
            rows = self._read()["records"]
        def match(row: dict[str, Any]) -> bool:
            if project_id and row.get("project_id") != project_id:
                return False
            blob = json.dumps(row.get("source", {}), ensure_ascii=False).lower() + " " + " ".join(row.get("tags", []))
            return not query or query in blob
        return [r for r in reversed(rows) if match(r)]

    def assign_project(self, record_id: str, project_id: str) -> bool:
        with _LOCK:
            data = self._read()
            for row in data["records"]:
                if row.get("id") == record_id:
                    row["project_id"] = project_id
                    self._write(data)
                    return True
        return False

    def export(self, fmt: str, query: str = "", project_id: str = "") -> tuple[str, str]:
        rows = self.records(query, project_id)
        if fmt == "json":
            return json.dumps({"exported_at": _now(), "records": rows}, ensure_ascii=False, indent=2), "application/json"
        out = io.StringIO()
        writer = csv.DictWriter(out, fieldnames=["record_id", "project_id", "title", "author", "url", "accessed_at", "evidence_count", "ai_notice"])
        writer.writeheader()
        for row in rows:
            source = row.get("source", {})
            writer.writerow({"record_id": row["id"], "project_id": row.get("project_id", ""), "title": source.get("title", ""),
                             "author": source.get("author", ""), "url": source.get("url", ""), "accessed_at": source.get("accessed_at", ""),
                             "evidence_count": len(row.get("evidence", [])), "ai_notice": row.get("materials", {}).get("notice", "")})
        return out.getvalue(), "text/csv; charset=utf-8"
