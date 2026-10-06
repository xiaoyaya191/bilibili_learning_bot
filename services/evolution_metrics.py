"""Evidence-backed learner portraits; unknown metrics remain unknown."""
import json
import sqlite3
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

from services.diary_scheduler import clean_text, parse_time, DiaryScheduler, settings as diary_settings
from services import diary_store


def read_json(path, default):
    if not path.exists():
        return default
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, type(default)):
        raise ValueError('来源数据格式错误')
    return data


def collect(engine, preferences):
    since = datetime.now() - timedelta(days=preferences['lookback_days'])
    events, warnings = [], []
    if 'videos' in preferences['sources']:
        try:
            with engine.connection() as database:
                rows = database.execute('SELECT payload FROM events WHERE time>=? ORDER BY id DESC LIMIT ?', (since.isoformat(), preferences['max_events'])).fetchall()
            events = [json.loads(row['payload']) for row in rows]
            queue = engine.data_dir / 'video_watch_queue.sqlite3'
            if queue.exists():
                database = sqlite3.connect(queue.as_uri() + '?mode=ro', uri=True, timeout=5)
                database.row_factory = sqlite3.Row
                try:
                    rows = database.execute('SELECT * FROM history WHERE finished_at>=? ORDER BY id DESC LIMIT ?', (since.isoformat(), preferences['max_events'])).fetchall()
                    for row in rows:
                        item = json.loads(row['payload'])
                        assessment = json.loads(row['assessment'] or '{}')
                        actions = json.loads(row['actions'] or '[]')
                        owner = item.get('owner') or {}
                        events.append({'id': 'queue-' + str(row['id']), 'time': row['finished_at'], 'title': clean_text(item.get('title'))[:200],
                            'up': clean_text(item.get('up') or item.get('up_name') or owner.get('name') or '未知来源')[:80],
                            'domain': clean_text(item.get('tname') or item.get('category') or assessment.get('learning_topic') or '未分类')[:80],
                            'outcome': row['outcome'], 'score': row['score'], 'learned': '学习归档' in actions,
                            'bvid': item.get('bvid') or row['bvid'], 'duration': item.get('duration'),
                            'expected_score': item.get('expected_score'), 'type': 'video_result'})
                finally:
                    database.close()
            if not events:
                for index, item in enumerate(read_json(engine.data_dir / 'history_videos.json', {}).get('videos', [])):
                    stamp = parse_time(item.get('time')) if isinstance(item, dict) else None
                    if stamp and stamp >= since and item.get('action') == 'view':
                        events.append({'id': 'legacy-view-' + str(index), 'time': item['time'], 'title': clean_text(item.get('title'))[:200],
                            'up': clean_text(item.get('up') or item.get('up_name') or '未知来源')[:80], 'domain': clean_text(item.get('category') or '未分类')[:80],
                            'bvid': item.get('bvid'), 'score': item.get('score'), 'outcome': 'legacy_unknown', 'learned': None, 'type': 'video_result'})
        except (ValueError, OSError, sqlite3.Error, TypeError, AttributeError):
            warnings.append('观看来源读取失败，相关指标可能不完整')
    unique = {}
    for item in sorted(events, key=lambda event: event.get('time', ''), reverse=True):
        unique.setdefault(item.get('bvid') or item['id'], item)
    events = list(unique.values())[:preferences['max_events']]
    sources = []
    if 'learning' in preferences['sources']:
        selected = diary_settings({'diary': {'sources': ['learning'], 'lookback_hours': min(720, preferences['lookback_days'] * 24), 'max_events': min(500, preferences['max_events'])}})
        collected = DiaryScheduler(engine.data_dir, engine.knowledge_dir).collect(selected)
        sources.extend({'id': 'knowledge-' + str(index), 'text': event['text'], 'time': event['time']} for index, event in enumerate(collected['events']))
        warnings.extend(collected['warnings'])
    if 'diary' in preferences['sources']:
        try:
            entries = diary_store.read(engine.data_dir / 'bot_diary.json')['entries']
            for item in entries[-preferences['max_events']:]:
                stamp = parse_time(item.get('time'))
                if stamp and stamp >= since:
                    sources.append({'id': str(item.get('id') or 'diary-' + item['time']), 'time': item['time'], 'text': clean_text(item.get('content'))[:3000]})
        except (ValueError, OSError, TypeError, AttributeError):
            warnings.append('日记来源读取失败')
    total = 0
    bounded = []
    for item in sources:
        item['text'] = item['text'][:max(0, preferences['max_source_chars'] - total)]
        total += len(item['text'])
        if item['text']:
            bounded.append(item)
    return {'events': events, 'sources': bounded, 'warnings': warnings, 'since': since.isoformat()}


def audit(collected, preferences):
    events = collected['events']
    videos = [item for item in events if item.get('type') == 'video_result' or item.get('type', '').startswith('video_')]
    domains = Counter(item.get('domain') or item.get('category') or '未分类' for item in videos)
    authors = Counter(item.get('up') or '未知来源' for item in videos)
    known = [item for item in videos if item.get('outcome') in ('done', 'skipped')]
    learned = [item for item in videos if item.get('learned') is True]
    paired = [item for item in videos if type(item.get('expected_score')) in (int, float) and type(item.get('score')) in (int, float)]
    goal_matches = sum(any(keyword.casefold() in str(item.get('title', '')).casefold() for keyword in preferences['goal_keywords']) for item in videos)
    known_authors = {key: count for key, count in authors.items() if key != '未知来源'}
    concentration = max(known_authors.values()) / sum(known_authors.values()) if known_authors else None
    metrics = {'sample_count': len(videos), 'known_outcomes': len(known), 'completed_ratio': sum(item.get('outcome') == 'done' for item in known) / len(known) if known else None,
        'archived_count': len(learned), 'unique_domains': len([key for key in domains if key != '未分类']), 'unique_authors': len([key for key in authors if key != '未知来源']),
        'largest_author_share': concentration, 'goal_match_ratio': goal_matches / len(videos) if videos and preferences['goal_keywords'] else None,
        'surprise_ratio': sum(item['score'] - item['expected_score'] >= 2 for item in paired) / len(paired) if paired else None,
        'decision_accuracy': None, 'retrieval_usefulness': None, 'conflict_rate': None}
    alerts = []
    if sum(known_authors.values()) >= 10 and concentration is not None and concentration > .5:
        alerts.append('信息源集中：单一UP主占比超过50%，建议增加来源多样性')
    if len(videos) >= 10 and len([key for key in domains if key != '未分类']) <= 1:
        alerts.append('领域覆盖线索偏窄：建议横向探索；未分类数据不能证明信息茧房')
    return {'time': datetime.now().isoformat(), 'metrics': metrics, 'portrait': {'domains': dict(domains.most_common(20)), 'authors': dict(authors.most_common(20)),
        'goal_keywords': preferences['goal_keywords'], 'knowledge_evidence_count': len(collected['sources']),
        'note': '领域和归档次数只是覆盖线索，不等于知识掌握、真实准确率或情绪。缺失指标显示未知，不编造。'},
        'alerts': alerts, 'warnings': collected['warnings'], 'evidence_ids': [item['id'] for item in events] + [item['id'] for item in collected['sources']]}
