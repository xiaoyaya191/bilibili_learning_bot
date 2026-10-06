"""Persistent goal-driven learning loop state for BiliLearn 3.1.6."""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from core.user_data import DATA_DIR, KNOWLEDGE_BASE_DIR

_LOCK = threading.RLock()
DB_FILE = DATA_DIR / "learning_state.sqlite3"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


def _row(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


class LearningLoopService:
    """Canonical learning state; Markdown remains the human-readable artifact layer."""

    def __init__(self, db_path: str | Path | None = None, knowledge_dir: str | Path | None = None):
        self.db_path = Path(db_path or DB_FILE)
        self.knowledge_dir = Path(knowledge_dir or KNOWLEDGE_BASE_DIR)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_schema(self) -> None:
        schema = """
        CREATE TABLE IF NOT EXISTS goals (
          id TEXT PRIMARY KEY, topic TEXT NOT NULL, objective TEXT NOT NULL DEFAULT '',
          level TEXT NOT NULL DEFAULT 'foundation', mode TEXT NOT NULL DEFAULT 'learn_companion',
          status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS knowledge_nodes (
          id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, parent_id TEXT, title TEXT NOT NULL,
          description TEXT NOT NULL DEFAULT '', sort_order INTEGER NOT NULL DEFAULT 0,
          mastery REAL NOT NULL DEFAULT 0, confidence REAL NOT NULL DEFAULT 0,
          status TEXT NOT NULL DEFAULT 'gap', source TEXT NOT NULL DEFAULT 'user',
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
          FOREIGN KEY(goal_id) REFERENCES goals(id) ON DELETE CASCADE,
          FOREIGN KEY(parent_id) REFERENCES knowledge_nodes(id) ON DELETE SET NULL
        );
        CREATE TABLE IF NOT EXISTS knowledge_relations (
          id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, from_node_id TEXT NOT NULL,
          to_node_id TEXT NOT NULL, relation TEXT NOT NULL DEFAULT 'prerequisite', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mastery_evidence (
          id TEXT PRIMARY KEY, node_id TEXT NOT NULL, kind TEXT NOT NULL, score REAL NOT NULL,
          weight REAL NOT NULL DEFAULT 1, detail TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
          FOREIGN KEY(node_id) REFERENCES knowledge_nodes(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS search_rounds (
          id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, node_id TEXT, query TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'planned', created_at TEXT NOT NULL, finished_at TEXT
        );
        CREATE TABLE IF NOT EXISTS candidate_videos (
          id TEXT PRIMARY KEY, search_round_id TEXT, goal_id TEXT NOT NULL, node_id TEXT,
          bvid TEXT NOT NULL, title TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '',
          url TEXT NOT NULL DEFAULT '', score REAL NOT NULL DEFAULT 0, reason TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'candidate', created_at TEXT NOT NULL, UNIQUE(goal_id,bvid)
        );
        CREATE TABLE IF NOT EXISTS learning_records (
          id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, node_id TEXT, candidate_id TEXT,
          bvid TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '', note_path TEXT NOT NULL DEFAULT '',
          learned_at TEXT NOT NULL, outcome TEXT NOT NULL DEFAULT 'learned'
        );
        CREATE TABLE IF NOT EXISTS quiz_attempts (
          id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, node_id TEXT, score REAL NOT NULL,
          total INTEGER NOT NULL DEFAULT 0, correct INTEGER NOT NULL DEFAULT 0,
          detail_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS mistakes (
          id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, node_id TEXT, question TEXT NOT NULL,
          answer TEXT NOT NULL DEFAULT '', expected TEXT NOT NULL DEFAULT '',
          resolved INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, resolved_at TEXT
        );
        CREATE TABLE IF NOT EXISTS weaknesses (
          id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, node_id TEXT NOT NULL,
          severity REAL NOT NULL DEFAULT 1, reason TEXT NOT NULL DEFAULT '',
          active INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL, UNIQUE(goal_id,node_id)
        );
        CREATE TABLE IF NOT EXISTS review_tasks (
          id TEXT PRIMARY KEY, goal_id TEXT NOT NULL, node_id TEXT NOT NULL,
          due_at TEXT NOT NULL, interval_days INTEGER NOT NULL DEFAULT 1,
          status TEXT NOT NULL DEFAULT 'pending', reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS app_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_nodes_goal ON knowledge_nodes(goal_id,status,sort_order);
        CREATE INDEX IF NOT EXISTS idx_review_due ON review_tasks(status,due_at);
        """
        with _LOCK, self._connect() as conn:
            conn.executescript(schema)
            conn.execute("UPDATE goals SET status='paused' WHERE mode='companion' AND status='companion_only'")
            conn.execute("UPDATE goals SET mode='learn_companion' WHERE mode!='learn_companion'")
        self._migrate_legacy_once()

    def _migrate_legacy_once(self) -> None:
        with _LOCK, self._connect() as conn:
            if conn.execute("SELECT 1 FROM app_meta WHERE key='legacy_v1'").fetchone():
                return
            state_path = self.db_path.parent / "mini_goal_state.json"
            try:
                state = json.loads(state_path.read_text(encoding="utf-8-sig")) if state_path.exists() else {}
            except Exception:
                state = {}
            if isinstance(state, dict) and state.get("topic"):
                goal_id = _id("goal")
                now = _now()
                conn.execute("INSERT INTO goals VALUES (?,?,?,?,?,?,?,?)", (
                    goal_id, str(state.get("topic"))[:160], str(state.get("category") or "")[:500],
                    "foundation", "learn_companion", "active" if state.get("active") else "paused", now, now))
            conn.execute("INSERT OR REPLACE INTO app_meta(key,value) VALUES('legacy_v1',?)", (_now(),))

    def create_goal(self, topic: str, objective: str = "", level: str = "foundation",
                    mode: str = "learn_companion") -> dict:
        topic = str(topic or "").strip()
        if not topic:
            raise ValueError("学习主题不能为空")
        mode = 'learn_companion'
        if level not in {"foundation", "systematic", "advanced", "custom"}:
            level = "custom"
        goal_id, now = _id("goal"), _now()
        status = "active" if mode != "companion" else "companion_only"
        with _LOCK, self._connect() as conn:
            conn.execute("UPDATE goals SET status='paused',updated_at=? WHERE status='active'", (now,))
            conn.execute("INSERT INTO goals VALUES (?,?,?,?,?,?,?,?)",
                         (goal_id, topic[:160], str(objective)[:1000], level, mode, status, now, now))
        return self.get_goal(goal_id) or {}

    def get_goal(self, goal_id: str) -> dict | None:
        with self._connect() as conn:
            return _row(conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone())

    def list_goals(self) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM goals ORDER BY CASE status WHEN 'active' THEN 0 ELSE 1 END, updated_at DESC").fetchall()]

    def add_node(self, goal_id: str, title: str, description: str = "", parent_id: str | None = None,
                 source: str = "user", mastery: float = 0) -> dict:
        title = str(title or "").strip()
        if not self.get_goal(goal_id) or not title:
            raise ValueError("学习目标或知识点无效")
        node_id, now = _id("node"), _now()
        mastery = max(0.0, min(100.0, float(mastery or 0)))
        status = "mastered" if mastery >= 80 else ("learning" if mastery > 0 else "gap")
        with _LOCK, self._connect() as conn:
            order = conn.execute("SELECT COALESCE(MAX(sort_order),-1)+1 FROM knowledge_nodes WHERE goal_id=?", (goal_id,)).fetchone()[0]
            conn.execute("INSERT INTO knowledge_nodes VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                node_id, goal_id, parent_id, title[:200], str(description)[:1200], order,
                mastery, 0, status, source[:30], now, now))
        return self.get_node(node_id) or {}

    def get_node(self, node_id: str) -> dict | None:
        with self._connect() as conn:
            return _row(conn.execute("SELECT * FROM knowledge_nodes WHERE id=?", (node_id,)).fetchone())

    def list_nodes(self, goal_id: str) -> list[dict]:
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(
                "SELECT * FROM knowledge_nodes WHERE goal_id=? ORDER BY sort_order,title", (goal_id,)).fetchall()]

    def record_evidence(self, node_id: str, score: float, kind: str = "assessment",
                        weight: float = 1, detail: str = "") -> dict:
        node = self.get_node(node_id)
        if not node:
            raise ValueError("知识点不存在")
        score = max(0.0, min(100.0, float(score)))
        weight = max(0.1, min(5.0, float(weight or 1)))
        evidence_id, now = _id("evidence"), _now()
        with _LOCK, self._connect() as conn:
            conn.execute("INSERT INTO mastery_evidence VALUES (?,?,?,?,?,?,?)",
                         (evidence_id, node_id, kind[:40], score, weight, str(detail)[:1000], now))
            rows = conn.execute("SELECT score,weight FROM mastery_evidence WHERE node_id=?", (node_id,)).fetchall()
            total_weight = sum(float(r["weight"]) for r in rows) or 1
            mastery = round(sum(float(r["score"]) * float(r["weight"]) for r in rows) / total_weight, 2)
            confidence = round(min(100.0, sum(float(r["weight"]) for r in rows) * 20), 2)
            status = "mastered" if mastery >= 80 and confidence >= 40 else ("learning" if mastery >= 40 else "gap")
            conn.execute("UPDATE knowledge_nodes SET mastery=?,confidence=?,status=?,updated_at=? WHERE id=?",
                         (mastery, confidence, status, now, node_id))
            if mastery < 60:
                severity = round((100 - mastery) / 100, 3)
                conn.execute("INSERT INTO weaknesses VALUES (?,?,?,?,?,?,?) ON CONFLICT(goal_id,node_id) DO UPDATE SET severity=excluded.severity,reason=excluded.reason,active=1,updated_at=excluded.updated_at",
                             (_id("weak"), node["goal_id"], node_id, severity, str(detail or kind)[:500], 1, now))
            else:
                conn.execute("UPDATE weaknesses SET active=0,updated_at=? WHERE goal_id=? AND node_id=?",
                             (now, node["goal_id"], node_id))
        return self.get_node(node_id) or {}

    def add_candidate(self, goal_id: str, bvid: str, title: str = "", node_id: str | None = None,
                      score: float = 0, reason: str = "", author: str = "", url: str = "",
                      search_round_id: str | None = None) -> dict:
        bvid = str(bvid or "").strip()
        if not self.get_goal(goal_id) or not bvid:
            raise ValueError("目标或 BV 号无效")
        cid, now = _id("video"), _now()
        with _LOCK, self._connect() as conn:
            conn.execute("INSERT INTO candidate_videos VALUES (?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(goal_id,bvid) DO UPDATE SET title=excluded.title,author=excluded.author,url=excluded.url,score=excluded.score,reason=excluded.reason",
                         (cid, search_round_id, goal_id, node_id, bvid[:32], str(title)[:300], str(author)[:120],
                          str(url)[:1000], max(0, min(10, float(score or 0))), str(reason)[:1000], "candidate", now))
            row = conn.execute("SELECT * FROM candidate_videos WHERE goal_id=? AND bvid=?", (goal_id, bvid[:32])).fetchone()
        return _row(row) or {}

    def start_search(self, goal_id: str, query: str, node_id: str | None = None) -> dict:
        if not self.get_goal(goal_id) or not str(query or "").strip():
            raise ValueError("学习目标或搜索词无效")
        search_id, now = _id("search"), _now()
        with _LOCK, self._connect() as conn:
            conn.execute("INSERT INTO search_rounds VALUES (?,?,?,?,?,?)",
                         (search_id, goal_id, node_id, str(query).strip()[:300], "running", now, None))
        return {"id": search_id, "goal_id": goal_id, "node_id": node_id, "query": str(query).strip()}

    def finish_search(self, search_id: str, status: str = "completed") -> None:
        with _LOCK, self._connect() as conn:
            conn.execute("UPDATE search_rounds SET status=?,finished_at=? WHERE id=?",
                         (str(status or "completed")[:30], _now(), search_id))

    def record_learning(self, goal_id: str, node_id: str | None = None, bvid: str = "",
                        title: str = "", note_path: str = "", outcome: str = "learned") -> dict:
        rid, now = _id("learn"), _now()
        with _LOCK, self._connect() as conn:
            candidate = conn.execute("SELECT id FROM candidate_videos WHERE goal_id=? AND bvid=?", (goal_id, bvid)).fetchone() if bvid else None
            conn.execute("INSERT INTO learning_records VALUES (?,?,?,?,?,?,?,?,?)",
                         (rid, goal_id, node_id, candidate[0] if candidate else None, bvid[:32], str(title)[:300], str(note_path)[:1000], now, outcome[:30]))
            if candidate:
                conn.execute("UPDATE candidate_videos SET status='learned' WHERE id=?", (candidate[0],))
        if node_id:
            self.record_evidence(node_id, 55, "learning_completed", 0.5, title or bvid)
        return {"id": rid, "goal_id": goal_id, "node_id": node_id, "bvid": bvid, "learned_at": now}

    def record_quiz(self, goal_id: str, node_id: str, correct: int, total: int,
                    mistakes: list[dict] | None = None) -> dict:
        total = max(1, int(total or 1)); correct = max(0, min(total, int(correct or 0)))
        score, now, attempt_id = round(correct / total * 100, 2), _now(), _id("quiz")
        mistakes = [m for m in (mistakes or []) if isinstance(m, dict)]
        with _LOCK, self._connect() as conn:
            conn.execute("INSERT INTO quiz_attempts VALUES (?,?,?,?,?,?,?,?)",
                         (attempt_id, goal_id, node_id, score, total, correct,
                          json.dumps(mistakes, ensure_ascii=False), now))
            for item in mistakes:
                conn.execute("INSERT INTO mistakes VALUES (?,?,?,?,?,?,?,?,?)", (
                    _id("mistake"), goal_id, node_id, str(item.get("question") or "错题")[:1000],
                    str(item.get("answer") or "")[:1000], str(item.get("expected") or "")[:1000], 0, now, None))
            days = 1 if score < 60 else (3 if score < 80 else 7)
            conn.execute("INSERT INTO review_tasks VALUES (?,?,?,?,?,?,?,?)",
                         (_id("review"), goal_id, node_id, (datetime.now()+timedelta(days=days)).isoformat(timespec="seconds"),
                          days, "pending", "测验后复习", now))
        node = self.record_evidence(node_id, score, "quiz", 1.5, f"{correct}/{total}")
        return {"id": attempt_id, "score": score, "node": node}

    def next_plan(self, goal_id: str) -> dict:
        goal = self.get_goal(goal_id)
        if not goal:
            raise ValueError("学习目标不存在")
        nodes = self.list_nodes(goal_id)
        gaps = sorted([n for n in nodes if n["status"] != "mastered"], key=lambda n: (n["mastery"], n["sort_order"]))
        current = gaps[0] if gaps else None
        topic = current["title"] if current else goal["topic"]
        level_words = {"foundation": "入门 基础", "systematic": "系统教程", "advanced": "进阶 实战", "custom": "教程"}
        queries = [f"{goal['topic']} {topic} {level_words.get(goal['level'],'教程')}"]
        if current and current.get("description"):
            keywords = re.findall(r"[A-Za-z][A-Za-z0-9_+.-]{2,}|[\u4e00-\u9fff]{2,8}", current["description"])
            if keywords:
                queries.append(f"{topic} {' '.join(keywords[:3])}")
        return {"goal": goal, "current_node": current, "gaps": gaps[:8], "search_queries": queries,
                "action": "review" if not gaps else "search_video"}

    def summary(self, goal_id: str = "") -> dict:
        goals = self.list_goals()
        goal = self.get_goal(goal_id) if goal_id else next((g for g in goals if g["status"] == "active"), goals[0] if goals else None)
        if not goal:
            return {"goals": [], "active_goal": None, "nodes": [], "stats": {"mastery": 0, "gaps": 0, "due_reviews": 0}}
        nodes = self.list_nodes(goal["id"])
        with self._connect() as conn:
            due = conn.execute("SELECT COUNT(*) FROM review_tasks WHERE goal_id=? AND status='pending' AND due_at<=?", (goal["id"], _now())).fetchone()[0]
            mistakes = conn.execute("SELECT COUNT(*) FROM mistakes WHERE goal_id=? AND resolved=0", (goal["id"],)).fetchone()[0]
            candidates = [dict(r) for r in conn.execute("SELECT * FROM candidate_videos WHERE goal_id=? ORDER BY score DESC,created_at DESC LIMIT 20", (goal["id"],)).fetchall()]
            reviews = [dict(r) for r in conn.execute("SELECT r.*,n.title AS node_title FROM review_tasks r LEFT JOIN knowledge_nodes n ON n.id=r.node_id WHERE r.goal_id=? AND r.status='pending' ORDER BY due_at LIMIT 20", (goal["id"],)).fetchall()]
        mastery = round(sum(float(n["mastery"]) for n in nodes) / len(nodes), 1) if nodes else 0
        return {"goals": goals, "active_goal": goal, "nodes": nodes, "candidates": candidates, "review_tasks": reviews,
                "stats": {"mastery": mastery, "gaps": sum(n["status"] != "mastered" for n in nodes),
                          "mastered": sum(n["status"] == "mastered" for n in nodes), "due_reviews": due,
                          "unresolved_mistakes": mistakes}, "next_plan": self.next_plan(goal["id"])}
