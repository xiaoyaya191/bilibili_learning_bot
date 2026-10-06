"""Account-isolated, opt-in video review rules and durable task state."""
import json
import re
import sqlite3
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path

from core.user_data import DATA_DIR

DEFAULTS = {
    "enabled": False, "rules_confirmed": False,
    "sources": ["history", "local_favorites"],
    "time_windows": [], "weekdays": list(range(7)),
    "categories": [], "keywords": [], "exclude_keywords": [], "up_names": [],
    "favorite_folders": [], "min_score": 7.5, "min_age_hours": 24,
    "revisit_cooldown_minutes": 60, "per_video_cooldown_minutes": 240,
    "max_per_video": 2, "daily_limit": 3, "order": "oldest",
}
LEGACY_KEYS = {"prob_revisit"}


def validate_settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS) - LEGACY_KEYS:
        raise ValueError("复习设置包含未知字段")
    result = deepcopy(DEFAULTS)
    result.update({key: val for key, val in value.items() if key in DEFAULTS})
    for key in ("enabled", "rules_confirmed"):
        if type(result[key]) is not bool:
            raise ValueError(key + " 必须为开关")
    for key, upper in {"min_score": 10, "min_age_hours": 87600,
                       "revisit_cooldown_minutes": 525600,
                       "per_video_cooldown_minutes": 525600,
                       "max_per_video": 1000, "daily_limit": 1000}.items():
        number = result[key]
        if type(number) not in (int, float) or not 0 <= number <= upper:
            raise ValueError(key + " 超出范围")
        if key not in ("min_score", "min_age_hours") and int(number) != number:
            raise ValueError(key + " 必须为整数")
    for key in ("sources", "categories", "keywords", "exclude_keywords", "up_names", "favorite_folders", "time_windows", "weekdays"):
        items = result[key]
        if not isinstance(items, list) or len(items) > 100:
            raise ValueError(key + " 必须为列表（最多100项）")
        if key == "weekdays":
            if any(type(day) is not int or day not in range(7) for day in items):
                raise ValueError("星期范围为0（周一）到6（周日）")
        elif any(not isinstance(item, str) or not item.strip() or len(item) > 200 for item in items):
            raise ValueError(key + " 列表内容无效")
    if not result["sources"] or set(result["sources"]) - {"history", "liked", "favorited", "local_favorites"}:
        raise ValueError("请选择观看历史、点赞记录、平台收藏记录或本地收藏")
    if result["order"] not in ("oldest", "score", "least_reviewed"):
        raise ValueError("复习排序无效")
    for window in result["time_windows"]:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d-(?:[01]\d|2[0-3]):[0-5]\d", window):
            raise ValueError("时间段格式为 HH:MM-HH:MM")
        if window[:5] == window[6:]:
            raise ValueError("时间段起止不能相同；全天请留空")
    return result


def settings(config_data=None):
    if config_data is None:
        from core.config import load_config
        config_data = load_config()
    return validate_settings(config_data.get("revisit", {}))


def in_schedule(preferences, now):
    if now.weekday() not in preferences["weekdays"]:
        return False
    minute = now.strftime("%H:%M")
    windows = preferences["time_windows"]
    return not windows or any(
        (start <= minute < end if start < end else minute >= start or minute < end)
        for start, end in (window.split("-") for window in windows)
    )


def _date(value):
    try:
        parsed = datetime.fromisoformat(str(value))
        return parsed.astimezone().replace(tzinfo=None) if parsed.tzinfo else parsed
    except (ValueError, TypeError):
        return None


class VideoReview:
    def __init__(self, data_dir=None):
        self.data_dir = Path(data_dir or DATA_DIR)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / "video_review.sqlite3"
        with self.connection() as database:
            database.execute("CREATE TABLE IF NOT EXISTS tasks (id INTEGER PRIMARY KEY, bvid TEXT NOT NULL, video TEXT NOT NULL, status TEXT NOT NULL, manual INTEGER NOT NULL, created TEXT NOT NULL, finished TEXT, score REAL, note TEXT)")
            database.execute("CREATE UNIQUE INDEX IF NOT EXISTS one_active_review ON tasks ((1)) WHERE status IN ('pending','running')")

    @contextmanager
    def connection(self):
        database = sqlite3.connect(self.path, timeout=10)
        database.row_factory = sqlite3.Row
        try:
            with database:
                yield database
        finally:
            database.close()

    def _read(self, name, key):
        path = self.data_dir / name
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return [item for item in data.get(key, []) if isinstance(item, dict)]

    def candidates(self, preferences, now=None):
        now = now or datetime.now()
        history = self._read("history_videos.json", "videos")
        pool = []
        sources = preferences["sources"]
        for item in history:
            action = item.get("action")
            source = "history" if action == "view" else "liked" if action in ("like", "点赞") else "favorited" if action in ("fav", "favorite", "收藏") else None
            if source in sources:
                pool.append(dict(item, review_source=source))
        if "local_favorites" in sources:
            folders = {item.get("id"): item.get("name") for item in self._read("video_favorites.json", "folders")}
            for item in self._read("video_favorites.json", "items"):
                if preferences["favorite_folders"] and folders.get(item.get("folder_id")) not in preferences["favorite_folders"]:
                    continue
                pool.append(dict(item, review_source="local_favorites"))
        with self.connection() as database:
            records = database.execute("SELECT bvid, COUNT(*) AS count, MAX(finished) AS last FROM tasks WHERE status='done' GROUP BY bvid").fetchall()
        reviewed = {item["bvid"]: dict(item) for item in records}
        metadata = {}
        for item in history:
            metadata.setdefault(item.get("bvid"), {}).update({key: value for key, value in item.items() if value not in (None, "")})
        result = {}
        for original in pool:
            bvid = str(original.get("bvid") or "")
            if not re.fullmatch(r"BV[0-9A-Za-z]{8,20}", bvid):
                continue
            item = dict(metadata.get(bvid, {}), **original)
            try:
                score = float(item.get("score") or 0)
            except (ValueError, TypeError):
                score = 0
            category = str(item.get("category") or item.get("tname") or item.get("typename") or "")
            text = str(item.get("title") or "").casefold()
            up = str(item.get("up") or item.get("up_name") or "")
            if score < preferences["min_score"] or (preferences["categories"] and category not in preferences["categories"]):
                continue
            if preferences["up_names"] and up not in preferences["up_names"]:
                continue
            if preferences["keywords"] and not any(word.casefold() in text for word in preferences["keywords"]):
                continue
            if any(word.casefold() in text for word in preferences["exclude_keywords"]):
                continue
            seen = _date(item.get("time") or item.get("added_at") or item.get("created_at"))
            if preferences["min_age_hours"] and (seen is None or now - seen < timedelta(hours=preferences["min_age_hours"])):
                continue
            record = reviewed.get(bvid, {})
            count = max(int(item.get("revisit_count") or 0), record.get("count", 0))
            dates = [date for date in (_date(item.get("last_revisit")), _date(record.get("last"))) if date]
            last = max(dates) if dates else None
            if preferences["max_per_video"] and count >= preferences["max_per_video"]:
                continue
            if last and now - last < timedelta(minutes=preferences["per_video_cooldown_minutes"]):
                continue
            item.update(score=score, category=category, review_count=count, last_review=last.isoformat() if last else None)
            result.setdefault(bvid, item)
        order = preferences["order"]
        return sorted(result.values(), key=lambda item: (
            -item["score"] if order == "score" else item["review_count"] if order == "least_reviewed" else item.get("last_review") or item.get("time") or item.get("added_at") or "",
            item["bvid"],
        ))

    def reserve(self, preferences, *, manual=False, bvid=None, now=None):
        now = now or datetime.now()
        if not manual and not (preferences["enabled"] and preferences["rules_confirmed"] and in_schedule(preferences, now)):
            return None
        candidates = self.candidates(preferences, now)
        if bvid:
            candidates = [item for item in candidates if item["bvid"] == bvid]
        if not candidates:
            return None
        with self.connection() as database:
            database.execute("BEGIN IMMEDIATE")
            if database.execute("SELECT 1 FROM tasks WHERE status IN ('pending','running')").fetchone():
                raise ValueError("已有待执行或正在执行的复习")
            used = database.execute("SELECT COUNT(*) FROM tasks WHERE created>=?", (now.strftime("%Y-%m-%d"),)).fetchone()[0]
            if preferences["daily_limit"] and used >= preferences["daily_limit"]:
                return None
            latest = database.execute("SELECT MAX(created) FROM tasks").fetchone()[0]
            if not manual and latest and now - _date(latest) < timedelta(minutes=preferences["revisit_cooldown_minutes"]):
                return None
            candidate = candidates[0]
            cursor = database.execute("INSERT INTO tasks (bvid,video,status,manual,created) VALUES (?,?,'pending',?,?)", (candidate["bvid"], json.dumps(candidate, ensure_ascii=False), int(manual), now.isoformat()))
            return cursor.lastrowid

    def claim(self, preferences, now=None):
        now = now or datetime.now()

        with self.connection() as database:
            database.execute("BEGIN IMMEDIATE")
            row = database.execute("SELECT * FROM tasks WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
            if not row or (not row["manual"] and not (preferences["enabled"] and preferences["rules_confirmed"] and in_schedule(preferences, now))):
                return None
            if not row["manual"] and row["bvid"] not in {item["bvid"] for item in self.candidates(preferences, now)}:
                database.execute("UPDATE tasks SET status='cancelled',finished=?,note='不再符合当前规则' WHERE id=?", (now.isoformat(), row["id"]))
                return None
            database.execute("UPDATE tasks SET status='running' WHERE id=?", (row["id"],))
            return dict(json.loads(row["video"]), _review_id=row["id"], _is_revisit=True)

    def finish(self, task_id, *, success, interrupted=False, score=None, note="", now=None):
        with self.connection() as database:
            database.execute("UPDATE tasks SET status=?,finished=?,score=?,note=? WHERE id=? AND status='running'", ("pending" if interrupted else "done" if success else "failed", None if interrupted else (now or datetime.now()).isoformat(), score, str(note)[:8000], task_id))

    def recover(self):
        with self.connection() as database:
            database.execute("UPDATE tasks SET status='pending',note='中断后等待恢复' WHERE status='running'")

    def cancel(self, task_id):
        with self.connection() as database:
            cursor = database.execute("UPDATE tasks SET status='cancelled',finished=? WHERE id=? AND status='pending'", (datetime.now().isoformat(), task_id))
            if not cursor.rowcount:
                raise ValueError("只可取消待执行的复习")

    def snapshot(self):
        with self.connection() as database:
            rows = database.execute("SELECT * FROM tasks ORDER BY id DESC LIMIT 100").fetchall()
        return [dict(row, video=json.loads(row["video"])) for row in rows]
