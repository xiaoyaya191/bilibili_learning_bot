from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta
from typing import Any

from .bilibili_ops import BilibiliAccount
from .settings import BotSettings
from .state import JsonStore, now_iso


def _parse_hhmm(value: str, fallback: time) -> time:
    try:
        hh, mm = value.split(":", 1)
        return time(int(hh), int(mm))
    except Exception as e:
        print(f"[proactive] 时间解析失败 '{value}': {e}")
        return fallback


class ProactivePlanner:
    def __init__(self, settings: BotSettings):
        self.settings = settings
        self.store = JsonStore("web_proactive_plan.json", {"date": "", "items": []})
        self.log = JsonStore("web_activity_log.json", {"items": []})
        self.bili = BilibiliAccount()

    def today_plan(self, regenerate: bool = False) -> dict[str, Any]:
        data = self.store.read()
        today = date.today().isoformat()
        if data.get("date") == today and data.get("items") and not regenerate:
            return data
        start_sleep = _parse_hhmm(self.settings.sleep_start, time(2, 0))
        end_sleep = _parse_hhmm(self.settings.sleep_end, time(8, 0))
        items = []
        for idx in range(max(1, self.settings.proactive_times_count)):
            dt = self._random_awake_datetime(start_sleep, end_sleep)
            items.append({
                "id": f"{today}-{idx + 1}",
                "type": "watch_and_comment",
                "scheduled_at": dt.isoformat(timespec="minutes"),
                "status": "planned",
                "video_count": self.settings.proactive_video_count,
                "comment_count": self.settings.proactive_comment_count,
            })
        data = {"date": today, "items": sorted(items, key=lambda item: item["scheduled_at"])}
        self.store.write(data)
        return data

    def _random_awake_datetime(self, sleep_start: time, sleep_end: time) -> datetime:
        base = datetime.combine(date.today(), time(0, 0))
        while True:
            candidate = base + timedelta(minutes=random.randint(0, 23 * 60 + 59))
            t = candidate.time()
            if sleep_start <= sleep_end:
                asleep = sleep_start <= t <= sleep_end
            else:
                asleep = t >= sleep_start or t <= sleep_end
            if not asleep:
                return candidate

    def record(self, action: str, payload: dict[str, Any], executed: bool) -> dict[str, Any]:
        data = self.log.read()
        item = {"action": action, "payload": payload, "executed": executed, "created_at": now_iso()}
        data.setdefault("items", []).insert(0, item)
        data["items"] = data["items"][:300]
        self.log.write(data)
        return item

    def logs(self) -> dict[str, Any]:
        return self.log.read()

    async def dry_run_recommendations(self) -> dict[str, Any]:
        videos = await self.bili.recommended_videos(self.settings.proactive_video_count)
        slim = [
            {
                "bvid": item.get("bvid"),
                "title": item.get("title"),
                "up": item.get("owner", {}).get("name"),
                "duration": item.get("duration"),
            }
            for item in videos
        ]
        self.record("proactive.recommendations", {"videos": slim}, executed=False)
        return {"executed": False, "videos": slim}

    async def poll_comments(self, limit: int = 20) -> dict[str, Any]:
        replies = await self.bili.recent_replies_to_me(limit=limit)
        slim = []
        for item in replies:
            user = item.get("user") or {}
            item_source = item.get("item") or {}
            slim.append({
                "id": item.get("id") or item.get("reply_id"),
                "user_id": str(user.get("mid") or ""),
                "user_name": user.get("nickname") or user.get("name") or "",
                "text": item_source.get("source_content") or item_source.get("content") or item.get("content") or "",
                "title": item_source.get("title") or "",
                "uri": item_source.get("uri") or item.get("uri") or "",
                "raw": item,
            })
        self.record("comment.poll", {"count": len(slim), "items": slim[:5]}, executed=False)
        return {"executed": False, "count": len(slim), "items": slim}

    async def dynamic_idea_plan(self) -> dict[str, Any]:
        topics = [
            "今天看过的视频里最值得记住的一点",
            "对近期评论区气氛的一点观察",
            "把一个知识点讲给路人听",
            "给明天的自己留一句提醒",
        ]
        item = {
            "type": "dynamic_idea",
            "topic": random.choice(topics),
            "source": "proactive-plan",
            "created_at": now_iso(),
        }
        self.record("dynamic.idea", item, executed=False)
        return {"executed": False, "idea": item}

    async def execute_due_once(self) -> dict[str, Any]:
        plan = self.today_plan()
        now = datetime.now()
        due = []
        for item in plan.get("items", []):
            try:
                scheduled = datetime.fromisoformat(item["scheduled_at"])
            except Exception:
                continue
            if item.get("status") == "planned" and scheduled <= now:
                due.append(item)

        results = []
        for item in due:
            try:
                if not self.settings.enable_proactive:
                    result = {"executed": False, "reason": "enable_proactive 未开启"}
                else:
                    result = await self.dry_run_recommendations()
                item["status"] = "done"
                item["finished_at"] = now_iso()
                results.append({"plan": item, "result": result})
                self.record("proactive.execute_due", {"plan": item, "result": result}, executed=False)
            except Exception as exc:
                item["status"] = "failed"
                item["error"] = repr(exc)
                results.append({"plan": item, "error": repr(exc)})
                self.record("proactive.execute_due.failed", {"plan": item, "error": repr(exc)}, executed=False)
        self.store.write(plan)
        return {"executed": False, "due_count": len(due), "results": results}
