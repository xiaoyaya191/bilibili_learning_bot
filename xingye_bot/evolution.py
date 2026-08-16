"""真正的进化系统：基于行为反馈自动调整人格参数。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


class EvolutionEngine:
    """基于互动反馈的自动进化系统。"""

    def __init__(self, data_dir=None):
        if data_dir is None:
            try:
                from core.user_data import DATA_DIR
                data_dir = DATA_DIR
            except Exception:
                data_dir = Path(".")
        self.data_dir = Path(data_dir)
        self.log_file = self.data_dir / "evolution_log.json"
        self.state_file = self.data_dir / "evolution_state.json"
        self.state = self._load_state()
        self.logs = self._load_logs()

    def _load_state(self):
        try:
            if self.state_file.exists():
                return json.loads(self.state_file.read_text(encoding="utf-8"))
        except Exception:
            pass
        return {
            "mood": "neutral",  # happy/excited/neutral/sad/frustrated
            "energy": 100,
            "traits": {
                "curiosity": 0.5,
                "caution": 0.3,
                "sociability": 0.5,
                "creativity": 0.4,
            },
            "total_interactions": 0,
            "success_count": 0,
            "fail_count": 0,
        }

    def _load_logs(self):
        try:
            if self.log_file.exists():
                data = json.loads(self.log_file.read_text(encoding="utf-8"))
                return data.get("logs", [])
        except Exception:
            pass
        return []

    def _save(self):
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")
            self.log_file.write_text(json.dumps({"logs": self.logs[-200:], "mood": self.state}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def record_event(self, event_type, success, detail=""):
        """记录一个互动事件并调整状态。"""
        self.state["total_interactions"] += 1
        if success:
            self.state["success_count"] += 1
            self._adjust_mood(1, f"{event_type}成功")
            self.state["traits"]["sociability"] = min(1.0, self.state["traits"]["sociability"] + 0.01)
        else:
            self.state["fail_count"] += 1
            self._adjust_mood(-2, f"{event_type}失败: {detail}")
            self.state["traits"]["caution"] = min(1.0, self.state["traits"]["caution"] + 0.02)

        self.logs.append({
            "time": datetime.now().isoformat(),
            "event": event_type,
            "success": success,
            "detail": detail[:200],
            "mood": self.state["mood"],
        })
        self.logs = self.logs[-200:]
        self._save()

    def _adjust_mood(self, delta, reason):
        """调整心情值。"""
        mood_map = {"frustrated": -2, "sad": -1, "neutral": 0, "happy": 1, "excited": 2}
        reverse_map = {v: k for k, v in mood_map.items()}
        current = mood_map.get(self.state["mood"], 0)
        new_val = max(-2, min(2, current + delta))
        self.state["mood"] = reverse_map.get(new_val, "neutral")
        self.state["energy"] = max(0, min(100, self.state["energy"] + delta))

    def get_mood_prompt(self):
        """生成心情提示词注入到 AI prompt。"""
        mood_desc = {
            "excited": "你现在非常兴奋，回复风格热情洋溢，多用感叹号",
            "happy": "你现在心情不错，回复风格友好愉快",
            "neutral": "你现在心情平静，正常回复即可",
            "sad": "你现在有点低落，回复风格偏沉稳",
            "frustrated": "你现在有点沮丧，回复风格谨慎简短",
        }
        return mood_desc.get(self.state["mood"], "")

    def get_trait_adjustments(self):
        """返回当前 trait 参数，用于调整互动概率。"""
        return self.state["traits"]
