"""brain/_brain_history.py — AgentBrain 互动视频历史 & 回顾复习 mixin"""
from brain._mixin_imports import *

class BrainHistoryMixin:
    """互动视频历史 & 回顾复习"""

    def _load_history_videos(self):
        if os.path.exists(HISTORY_VIDEOS_FILE):
            try:
                with open(HISTORY_VIDEOS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data.setdefault("videos", [])
                    return data
            except (OSError, json.JSONDecodeError) as e:
                log(f'加载JSON文件失败: {e}', 'DEBUG')
        return {"videos": []}

    def _save_history_videos(self):
        try:
            tmp = HISTORY_VIDEOS_FILE + '.tmp'
            with open(tmp, 'w', encoding='utf-8') as f:
                json.dump(self.history_videos, f, ensure_ascii=False, indent=2)
            os.replace(tmp, HISTORY_VIDEOS_FILE)
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
                             source="推荐流", result="已浏览", interest_reason="", score=None):
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
            entry.update({key: value for key, value in payload.items() if value not in (None, "")})
        self.history_videos["videos"] = videos[-200:]
        self._save_history_videos()

    def get_revisit_candidate(self):
        videos = self.history_videos.get("videos", [])
        if not videos:
            return None
        
        max_per_video = REVISIT_MAX_PER_VIDEO
        per_video_cooldown = REVISIT_PER_VIDEO_COOLDOWN_MINUTES
        min_score = REVISIT_MIN_SCORE
        
        eligible = [v for v in videos if v.get("score", 0) >= min_score]
        if not eligible:
            return None
        
        eligible = [v for v in eligible if v.get("revisit_count", 0) < max_per_video]
        if not eligible:
            return None
        
        now = datetime.now()
        cooldown_ok = []
        for v in eligible:
            last = v.get("last_revisit")
            if last is None:
                cooldown_ok.append(v)
            else:
                try:
                    last_dt = datetime.fromisoformat(last)
                    if (now - last_dt).total_seconds() / 60 >= per_video_cooldown:
                        cooldown_ok.append(v)
                except (ValueError, TypeError):
                    cooldown_ok.append(v)
        
        if not cooldown_ok:
            return None
        
        never = [v for v in cooldown_ok if v.get("last_revisit") is None]
        reviewed = [v for v in cooldown_ok if v.get("last_revisit") is not None]
        
        if never and random.random() < 0.7:
            return max(never, key=lambda v: v.get("score", 0))
        
        weights = [v.get("score", 0) * (1.0 / (1.0 + v.get("revisit_count", 0))) for v in cooldown_ok]
        total_w = sum(weights)
        if total_w <= 0:
            return None
        r = random.random() * total_w
        cum = 0
        for i, w in enumerate(weights):
            cum += w
            if r <= cum:
                return cooldown_ok[i]
        return cooldown_ok[-1]

    def mark_revisited(self, bvid):
        for v in self.history_videos.get("videos", []):
            if v.get("bvid") == bvid:
                v["revisit_count"] = v.get("revisit_count", 0) + 1
                v["last_revisit"] = datetime.now().isoformat()
                self._save_history_videos()
                return
