"""brain/_brain_history.py — AgentBrain 互动视频历史 & 回顾复习 mixin"""
from brain._mixin_imports import *

class BrainHistoryMixin:
    """互动视频历史 & 回顾复习"""

    def _load_history_videos(self):
        if os.path.exists(HISTORY_VIDEOS_FILE):
            try:
                from utils.storage import JsonStore
                data = JsonStore(HISTORY_VIDEOS_FILE).read()
                data.setdefault("videos", [])
                return data
            except (OSError, json.JSONDecodeError) as e:
                log(f'加载JSON文件失败: {e}', 'DEBUG')
        return {"videos": []}

    def _save_history_videos(self):
        try:
            from utils.storage import JsonStore
            if not JsonStore(HISTORY_VIDEOS_FILE).write(self.history_videos):
                raise OSError("账号数据库保存失败")
        except OSError as e:
            log(f'文件操作失败: {e}', 'DEBUG')

    def add_history_video(self, bvid, title, up, aid, action, score=0, pic=""):
        if score < REVISIT_MIN_SCORE:
            return
        videos = self.history_videos.get("videos", [])
        key = f"{bvid}_{action}"
        if any(f"{v.get('bvid')}_{v.get('action')}" == key for v in videos):
            return
        entry = {
            "bvid": bvid,
            "title": title,
            "up": up,
            "aid": aid,
            "action": action,
            "score": score,
            "pic": str(pic or ""),
            "time": datetime.now().isoformat(),
            "revisit_count": 0,
            "last_revisit": None
        }
        videos.append(entry)
        self.history_videos["videos"] = videos[-200:]
        self._save_history_videos()

    def record_watched_video(self, bvid, title, up, aid, *, pic="", duration=0,
source="推荐流", result="已浏览", interest_reason="", score=None, category=""):
        """Persist a real analysis target for the web viewing-history workspace.

        This is deliberately separate from interaction history: one video can be
        browsed, liked and favorited without creating three visual cards.
        """
        bvid = str(bvid or "").strip()
        if not bvid:
            return
        videos = self.history_videos.get("videos", [])
        entry = next((item for item in videos if item.get("bvid") == bvid and item.get("action") == "view"), None)
        payload = {
            "bvid": bvid,
            "title": str(title or ""),
            "up": str(up or ""),
            "aid": aid or 0,
            "action": "view",
            "pic": str(pic or ""),
            "duration": duration or 0,
            "source": str(source or "推荐流"),
            "category": str(category or ""),
            "result": str(result or "已浏览"),
            "interest_reason": str(interest_reason or ""),
            "score": score,
            "time": datetime.now().isoformat(),
            "revisit_count": 0,
            "last_revisit": None,
        }
        if entry is None:
            videos.append(payload)
        else:
            entry.update({key: value for key, value in payload.items() if value not in (None, "") and key not in ("revisit_count", "last_revisit")})
        self.history_videos["videos"] = videos[-200:]
        self._save_history_videos()

    def get_revisit_candidate(self):
        from services.video_review import VideoReview, in_schedule, settings
        preferences = settings()
        if not preferences["enabled"] or not preferences["rules_confirmed"] or not in_schedule(preferences, datetime.now()):
            return None
        candidates = VideoReview().candidates(preferences)
        return candidates[0] if candidates else None

    def mark_revisited(self, bvid):
        for v in self.history_videos.get("videos", []):
            if v.get("bvid") == bvid:
                v["revisit_count"] = v.get("revisit_count", 0) + 1
                v["last_revisit"] = datetime.now().isoformat()
                self._save_history_videos()
                return
