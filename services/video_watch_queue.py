"""Durable per-account video queue and configurable completion history."""
from __future__ import annotations

import json
import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from core.user_data import DATA_DIR

DEFAULTS = {
    'enabled': True,
    'max_selected': 0,
    'remove_completed': True,
    'keep_history': True,
    'history_limit': 500,
    'skip_watched': True,
    'review_interest_again': False,
    'max_retries': 2,
    'retry_delay_seconds': 60,
    'sync_platform': False,
    'remove_platform_completed': False,
}


def settings(config_data: dict | None = None) -> dict:
    if config_data is None:
        from core.config import load_config
        config_data = load_config()
    value = dict(DEFAULTS)
    value.update(config_data.get('watch_queue', {}))
    return validate_settings(value)


def validate_settings(value: dict) -> dict:
    result = dict(DEFAULTS)
    limits = {'max_selected': (0, 100), 'history_limit': (0, 10000), 'max_retries': (0, 10), 'retry_delay_seconds': (0, 86400)}
    for key, supplied in value.items():
        if key not in DEFAULTS:
            raise ValueError('未知观看队列设置: ' + key)
        if key in limits:
            if isinstance(supplied, bool) or not isinstance(supplied, int):
                raise ValueError(key + ' 必须是整数')
            lower, upper = limits[key]
            if not lower <= supplied <= upper:
                raise ValueError(f'{key} 必须在 {lower} 到 {upper} 之间')
        elif not isinstance(supplied, bool):
            raise ValueError(key + ' 必须是布尔值')
        result[key] = supplied
    return result


class VideoWatchQueue:
    def __init__(self, path: Path | str | None = None):
        self.path = Path(path) if path else Path(DATA_DIR) / 'video_watch_queue.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS queue (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bvid TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    available_at REAL NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT '',
                    outcome TEXT NOT NULL DEFAULT '',
                    score REAL,
                    platform_synced INTEGER NOT NULL DEFAULT 0,
                    priority INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS seen (bvid TEXT PRIMARY KEY);
                CREATE TABLE IF NOT EXISTS action_attempts (
                    queue_id INTEGER NOT NULL,
                    action TEXT NOT NULL,
                    state TEXT NOT NULL,
                    PRIMARY KEY(queue_id,action)
                );
                CREATE TABLE IF NOT EXISTS history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bvid TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    score REAL,
                    actions TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    assessment TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS history_bvid ON history(bvid);
            ''')
            columns = {row[1] for row in connection.execute('PRAGMA table_info(queue)')}
            if 'priority' not in columns:
                connection.execute('ALTER TABLE queue ADD COLUMN priority INTEGER NOT NULL DEFAULT 0')
            history_columns = {row[1] for row in connection.execute('PRAGMA table_info(history)')}
            if 'assessment' not in history_columns:
                connection.execute("ALTER TABLE history ADD COLUMN assessment TEXT NOT NULL DEFAULT '{}'")

    @contextmanager
    def _connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA busy_timeout=15000')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def eligible(self, items: list[dict], preferences: dict | None = None) -> list[dict]:
        preferences = preferences or settings()
        with self._connect() as connection:
            known = {row[0] for row in connection.execute('SELECT bvid FROM queue')}
            if preferences['skip_watched']:
                known.update(row[0] for row in connection.execute('SELECT bvid FROM seen'))
        return [item for item in items if isinstance(item, dict) and item.get('bvid') not in known]

    def _row(self, row):
        value = dict(row)
        value['video'] = json.loads(value.pop('payload'))
        value.update({key: value['video'].get(key, '') for key in ('title', 'pic', 'duration')})
        if 'actions' in value:
            value['actions'] = json.loads(value['actions'])
        if 'assessment' in value:
            value['assessment'] = json.loads(value['assessment'])
        return value

    def enqueue(self, items: list[dict], preferences: dict | None = None) -> list[str]:
        preferences = preferences or settings()
        added = []
        now = datetime.now().isoformat(timespec='seconds')
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            for item in items:
                bvid = str(item.get('bvid') or '').strip()
                if not re.fullmatch(r'BV[0-9A-Za-z]{8,20}', bvid):
                    continue
                if preferences['skip_watched'] and connection.execute('SELECT 1 FROM seen WHERE bvid=? LIMIT 1', (bvid,)).fetchone():
                    continue
                cursor = connection.execute('INSERT OR IGNORE INTO queue(bvid,payload,created_at,updated_at) VALUES(?,?,?,?)', (bvid, json.dumps(item, ensure_ascii=False), now, now))
                if cursor.rowcount:
                    added.append(bvid)
        return added

    def recover(self) -> int:
        with self._connect() as connection:
            return connection.execute("UPDATE queue SET status='pending',attempts=MAX(0,attempts-1),available_at=0,error='上次进程中断，等待恢复',updated_at=? WHERE status='watching'", (datetime.now().isoformat(timespec='seconds'),)).rowcount

    def claim(self, preferences: dict | None = None) -> dict | None:
        import time
        preferences = preferences or settings()
        if not preferences['enabled']:
            return None
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute("SELECT 1 FROM queue WHERE status='watching' LIMIT 1").fetchone():
                return None
            row = connection.execute("SELECT * FROM queue WHERE status='pending' AND available_at<=? ORDER BY priority DESC,id LIMIT 1", (time.time(),)).fetchone()
            if not row:
                return None
            connection.execute("UPDATE queue SET status='watching',attempts=attempts+1,updated_at=? WHERE id=?", (datetime.now().isoformat(timespec='seconds'), row['id']))
            result = json.loads(row['payload'])
            result['_watch_queue_id'] = row['id']
            result['_candidate_selected'] = True
            return result

    def pending(self) -> bool:
        with self._connect() as connection:
            return bool(connection.execute("SELECT 1 FROM queue WHERE status IN ('pending','watching') LIMIT 1").fetchone())

    def retry(self, bvid: str) -> None:
        with self._connect() as connection:
            cursor = connection.execute("UPDATE queue SET status='pending',attempts=0,available_at=0,error='',updated_at=? WHERE bvid=? AND status IN ('failed','done','skipped')", (datetime.now().isoformat(timespec='seconds'), bvid))
            if not cursor.rowcount:
                raise ValueError('只能重新排队已完成、跳过或失败的视频')

    def remove(self, bvid: str) -> None:
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT status FROM queue WHERE bvid=?', (bvid,)).fetchone()
            if row and row['status'] == 'watching':
                raise ValueError('正在观看的视频不能移除，请先停止机器人')
            connection.execute('DELETE FROM action_attempts WHERE queue_id IN (SELECT id FROM queue WHERE bvid=?)', (bvid,))
            connection.execute('DELETE FROM queue WHERE bvid=?', (bvid,))

    def update_video(self, video: dict) -> None:
        payload = {key: value for key, value in video.items() if key not in ('_watch_queue_id', '_candidate_selected')}
        with self._connect() as connection:
            connection.execute('UPDATE queue SET payload=? WHERE bvid=?', (json.dumps(payload, ensure_ascii=False), video['bvid']))

    def finish(self, bvid: str, outcome: str, *, score: float | None = None, actions: Any = None, assessment: dict | None = None, preferences: dict | None = None) -> None:
        preferences = preferences or settings()
        if outcome not in ('done', 'skipped'):
            raise ValueError('无效观看结果')
        now = datetime.now().isoformat(timespec='seconds')
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute("SELECT * FROM queue WHERE bvid=? AND status='watching'", (bvid,)).fetchone()
            if not row:
                return
            connection.execute('INSERT OR IGNORE INTO seen(bvid) VALUES(?)', (bvid,))
            if preferences['keep_history']:
                connection.execute('INSERT INTO history(bvid,payload,outcome,score,actions,finished_at,assessment) VALUES(?,?,?,?,?,?,?)', (bvid, row['payload'], outcome, score, json.dumps(actions or [], ensure_ascii=False), now, json.dumps(assessment or {}, ensure_ascii=False)))
                limit = preferences['history_limit']
                if limit:
                    connection.execute('DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT ?)', (limit,))
            if preferences['remove_completed']:
                connection.execute('DELETE FROM action_attempts WHERE queue_id=?', (row['id'],))
                connection.execute('DELETE FROM queue WHERE id=?', (row['id'],))
            else:
                connection.execute('UPDATE queue SET status=?,outcome=?,score=?,updated_at=? WHERE id=?', (outcome, outcome, score, now, row['id']))

    def fail(self, bvid: str, error: str, *, interrupted: bool = False, preferences: dict | None = None) -> None:
        import time
        preferences = preferences or settings()
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute("SELECT attempts FROM queue WHERE bvid=? AND status='watching'", (bvid,)).fetchone()
            if not row:
                return
            status = 'pending' if interrupted or row['attempts'] <= preferences['max_retries'] else 'failed'
            available = 0 if interrupted else time.time() + preferences['retry_delay_seconds']
            connection.execute('UPDATE queue SET status=?,available_at=?,error=?,updated_at=? WHERE bvid=?', (status, available, str(error)[:500], datetime.now().isoformat(timespec='seconds'), bvid))
            if interrupted:
                connection.execute('UPDATE queue SET attempts=MAX(0,attempts-1) WHERE bvid=?', (bvid,))

    def reserve_action(self, bvid: str, action: str) -> bool:
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute("SELECT id FROM queue WHERE bvid=? AND status='watching'", (bvid,)).fetchone()
            if not row:
                return False
            cursor = connection.execute("INSERT OR IGNORE INTO action_attempts(queue_id,action,state) VALUES(?,?,'started')", (row['id'], action))
            return bool(cursor.rowcount)

    def complete_action(self, bvid: str, action: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE action_attempts SET state='done' WHERE queue_id=(SELECT id FROM queue WHERE bvid=?) AND action=?", (bvid, action))

    def snapshot(self, *, history_limit: int = 100, history_offset: int = 0) -> dict:
        with self._connect() as connection:
            rows = connection.execute('SELECT * FROM queue ORDER BY priority DESC,id').fetchall()
            history = connection.execute('SELECT * FROM history ORDER BY id DESC LIMIT ? OFFSET ?', (history_limit, history_offset)).fetchall()
            count = connection.execute('SELECT count(*) FROM history').fetchone()[0]
        return {'items': [self._row(row) for row in rows], 'history': [self._row(row) for row in history], 'history_total': count}

    def restore(self, bvid: str) -> None:
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            row = connection.execute('SELECT payload FROM history WHERE bvid=? ORDER BY id DESC LIMIT 1', (bvid,)).fetchone()
            if not row:
                raise ValueError('历史记录不存在')
            existing = connection.execute('SELECT status FROM queue WHERE bvid=?', (bvid,)).fetchone()
            if existing and existing['status'] in ('watching', 'pending'):
                raise ValueError('视频已经在待观看队列中')
            now = datetime.now().isoformat(timespec='seconds')
            connection.execute('INSERT OR IGNORE INTO queue(bvid,payload,created_at,updated_at) VALUES(?,?,?,?)', (bvid, row['payload'], now, now))
            connection.execute("UPDATE queue SET status='pending',attempts=0,available_at=0,error='' WHERE bvid=?", (bvid,))

    def clear_history(self) -> None:
        with self._connect() as connection:
            connection.execute('DELETE FROM history')

    def clear_seen(self) -> None:
        with self._connect() as connection:
            connection.execute('DELETE FROM seen')

    def prioritize(self, bvid: str) -> None:
        with self._connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            priority = connection.execute('SELECT COALESCE(MAX(priority),0)+1 FROM queue').fetchone()[0]
            cursor = connection.execute("UPDATE queue SET priority=? WHERE bvid=? AND status='pending'", (priority, bvid))
            if not cursor.rowcount:
                raise ValueError('只有待观看视频可提到队首')

    def mark_synced(self, bvid: str) -> None:
        with self._connect() as connection:
            connection.execute('UPDATE queue SET platform_synced=1 WHERE bvid=?', (bvid,))
