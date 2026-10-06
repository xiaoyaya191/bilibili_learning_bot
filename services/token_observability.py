"""Account-local physical AI request telemetry; never stores request content."""
import json
import asyncio
import logging
import math
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DEFAULTS = {'retention_days': 180, 'monthly_token_budget': 0, 'prices': {}}


def validate_settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError('设置格式错误')
    result = dict(DEFAULTS, **value)
    for key, minimum, maximum in [('retention_days', 1, 3650), ('monthly_token_budget', 0, 10**12)]:
        if type(result[key]) is not int or not minimum <= result[key] <= maximum:
            raise ValueError(key + ' 超出允许范围')
    if not isinstance(result['prices'], dict) or len(result['prices']) > 200:
        raise ValueError('价格表最多200个模型')
    for model, price in result['prices'].items():
        if not isinstance(model, str) or not 1 <= len(model) <= 200 or not isinstance(price, dict) or set(price) != {'input', 'output', 'cached'}:
            raise ValueError('价格格式：模型名 → input/output/cached，单位人民币/百万Token')
        if any(type(amount) not in (int, float) or not math.isfinite(amount) or not 0 <= amount <= 10**8 for amount in price.values()):
            raise ValueError('单价必须是有限非负数')
    return result


def count(value):
    return value if type(value) is int and 0 <= value <= 10**15 else None


def usage(data):
    supplied = data.get('usage') if isinstance(data, dict) else None
    supplied = supplied if isinstance(supplied, dict) else {}
    incoming = count(supplied.get('prompt_tokens', supplied.get('input_tokens')))
    outgoing = count(supplied.get('completion_tokens', supplied.get('output_tokens')))
    total = count(supplied.get('total_tokens'))
    if total is None and incoming is not None and outgoing is not None:
        total = incoming + outgoing
    inputs = supplied.get('prompt_tokens_details', supplied.get('input_tokens_details', {})) or {}
    outputs = supplied.get('completion_tokens_details', supplied.get('output_tokens_details', {})) or {}
    cached = count(inputs.get('cached_tokens')) if isinstance(inputs, dict) else None
    reasoning = count(outputs.get('reasoning_tokens')) if isinstance(outputs, dict) else None
    if cached is not None and incoming is not None and cached > incoming:
        cached = None
    if reasoning is not None and outgoing is not None and reasoning > outgoing:
        reasoning = None
    return incoming, outgoing, total, cached, reasoning


class TokenStore:
    def __init__(self, directory=None):
        if directory is None:
            from core.user_data import DATA_DIR
            directory = DATA_DIR
        self.path = Path(directory) / 'token_observability.sqlite3'
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute('PRAGMA journal_mode=WAL')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS requests(
                    id INTEGER PRIMARY KEY, started REAL NOT NULL, latency_ms REAL NOT NULL,
                    source TEXT NOT NULL, model TEXT NOT NULL, provider TEXT NOT NULL,
                    endpoint TEXT NOT NULL, status INTEGER, outcome TEXT NOT NULL,
                    input_tokens INTEGER, output_tokens INTEGER, total_tokens INTEGER,
                    cached_tokens INTEGER, reasoning_tokens INTEGER);
                CREATE INDEX IF NOT EXISTS token_started ON requests(started);
                CREATE TABLE IF NOT EXISTS preferences(id INTEGER PRIMARY KEY, payload TEXT NOT NULL);
            ''')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def settings(self):
        with self.connect() as connection:
            row = connection.execute('SELECT payload FROM preferences WHERE id=1').fetchone()
        return validate_settings(json.loads(row[0]) if row else {})

    def save_settings(self, value):
        preferences = validate_settings(value)
        with self.connect() as connection:
            connection.execute('INSERT OR REPLACE INTO preferences VALUES(1,?)', (json.dumps(preferences),))
        return preferences

    def record(self, *, started, latency_ms, source, model, url, endpoint='', status=None, outcome='success', data=None):
        provider = urlsplit(str(url)).hostname or 'unknown'
        actual_model = data.get('model') if isinstance(data, dict) else None
        model = actual_model if isinstance(actual_model, str) and actual_model else model
        with self.connect() as connection:
            connection.execute('INSERT INTO requests(started,latency_ms,source,model,provider,endpoint,status,outcome,input_tokens,output_tokens,total_tokens,cached_tokens,reasoning_tokens) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                               (started, round(latency_ms, 3), str(source)[:100], str(model)[:200], provider[:255], str(endpoint)[:100], status, outcome, *usage(data)))

    def prune(self):
        cutoff = time.time() - self.settings()['retention_days'] * 86400
        with self.connect() as connection:
            removed = connection.execute('DELETE FROM requests WHERE started < ?', (cutoff,)).rowcount
        return removed


async def observed_post(client, url, *, source, model, data_dir=None, endpoint='', **kwargs):
    started = time.time()
    clock = time.perf_counter()
    data = None
    status = None
    outcome = 'network_error'
    try:
        response = await client.post(url, **kwargs)
        status = response.status_code
        outcome = 'success' if 200 <= status < 300 else 'http_error'
        try:
            data = response.json()
            if not isinstance(data, dict):
                outcome = 'invalid_response' if outcome == 'success' else outcome
        except (ValueError, UnicodeError):
            outcome = 'invalid_response' if outcome == 'success' else outcome
        return response
    except asyncio.CancelledError:
        outcome = 'cancelled'
        raise
    finally:
        try:
            TokenStore(data_dir).record(started=started, latency_ms=(time.perf_counter() - clock) * 1000,
                                       source=source, model=model, url=url, endpoint=endpoint,
                                       status=status, outcome=outcome, data=data)
        except Exception:
            logging.getLogger(__name__).warning('Token telemetry write failed; AI request unaffected')


def observed_urlopen(opener, request, *, model, data_dir=None, **kwargs):
    started = time.time()
    clock = time.perf_counter()
    data = None
    status = None
    outcome = 'network_error'
    try:
        with opener(request, **kwargs) as response:
            status = getattr(response, 'status', 200)
            outcome = 'invalid_response'
            data = json.loads(response.read() or b'{}')
            outcome = 'success'
        return data
    except Exception as error:
        code = getattr(error, 'code', None)
        if type(code) is int:
            status = code
            outcome = 'http_error'
        raise
    finally:
        try:
            TokenStore(data_dir).record(started=started, latency_ms=(time.perf_counter()-clock)*1000,
                                       source='model-test', model=model, url=request.full_url,
                                       status=status, outcome=outcome, data=data)
        except Exception:
            logging.getLogger(__name__).warning('Token telemetry write failed; AI request unaffected')


def period(args):
    try:
        zone = ZoneInfo(args.get('timezone', 'Asia/Shanghai'))
        today = datetime.now(zone).date()
        start = datetime.strptime(args.get('start', str(today - timedelta(days=6))), '%Y-%m-%d').date()
        end = datetime.strptime(args.get('end', str(today)), '%Y-%m-%d').date()
    except (ValueError, ZoneInfoNotFoundError):
        raise ValueError('日期或时区无效') from None
    if end < start or (end - start).days > 365:
        raise ValueError('日期范围必须为1至366天（包含结束日）')
    lower = datetime.combine(start, datetime.min.time(), zone).timestamp()
    upper = datetime.combine(end + timedelta(days=1), datetime.min.time(), zone).timestamp()
    return start, end, zone, lower, upper


def estimate(row, prices):
    price = prices.get(row['model'])
    if price is None or row['input_tokens'] is None or row['output_tokens'] is None:
        return None
    cached = row['cached_tokens']
    if cached is None and price['cached'] != price['input']:
        return None
    cached = cached or 0
    return ((row['input_tokens'] - cached) * price['input'] + cached * price['cached'] + row['output_tokens'] * price['output']) / 1000000


def report(store, args):
    start, end, zone, lower, upper = period(args)
    where = 'started >= ? AND started < ?'
    parameters = [lower, upper]
    for key in ('model', 'provider', 'source', 'outcome'):
        if args.get(key):
            where += ' AND ' + key + ' = ?'
            parameters.append(args[key])
    preferences = store.settings()
    with store.connect() as connection:
        rows = [dict(row) for row in connection.execute('SELECT * FROM requests WHERE ' + where + ' ORDER BY started DESC,id DESC', parameters)]
        options = {key: [row[0] for row in connection.execute('SELECT DISTINCT ' + key + ' FROM requests ORDER BY ' + key)] for key in ('model', 'provider', 'source')}
        month_start = datetime.now(zone).replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp()
        month_tokens = connection.execute('SELECT COALESCE(SUM(total_tokens),0) FROM requests WHERE started >= ? AND started < ?', (month_start, time.time())).fetchone()[0]
    summary = {'requests': len(rows), 'success': 0, 'known': 0, 'unknown': 0, 'input_tokens': 0, 'output_tokens': 0, 'total_tokens': 0, 'cached_tokens': 0, 'reasoning_tokens': 0, 'estimated_cny': 0, 'priced_requests': 0}
    summary['field_coverage'] = {key: 0 for key in ('input_tokens', 'output_tokens', 'cached_tokens', 'reasoning_tokens')}
    daily = {str(start + timedelta(days=offset)): {'date': str(start + timedelta(days=offset)), 'input': 0, 'output': 0, 'total': 0, 'requests': 0, 'unknown': 0} for offset in range((end-start).days+1)}
    groups = {key: {} for key in ('model', 'provider', 'source')}
    heatmap = [[0] * 24 for unused in range(7)]
    for row in rows:
        timestamp = datetime.fromtimestamp(row['started'], zone)
        row['timestamp'] = timestamp.isoformat(timespec='milliseconds')
        row['estimated_cny'] = estimate(row, preferences['prices'])
        summary['success'] += row['outcome'] == 'success'
        summary['known'] += row['total_tokens'] is not None
        summary['unknown'] += row['total_tokens'] is None
        for key in ('input_tokens', 'output_tokens', 'total_tokens', 'cached_tokens', 'reasoning_tokens'):
            summary[key] += row[key] or 0
            if key in summary['field_coverage']:
                summary['field_coverage'][key] += row[key] is not None
        if row['estimated_cny'] is not None:
            summary['estimated_cny'] += row['estimated_cny']
            summary['priced_requests'] += 1
        day = daily[str(timestamp.date())]
        day['requests'] += 1
        day['unknown'] += row['total_tokens'] is None
        for key in ('input', 'output', 'total'):
            day[key] += row[key + '_tokens'] or 0
        heatmap[timestamp.weekday()][timestamp.hour] += 1
        for key, mapping in groups.items():
            group = mapping.setdefault(row[key], {'name': row[key], 'tokens': 0, 'requests': 0, 'failures': 0})
            group['tokens'] += row['total_tokens'] or 0
            group['requests'] += 1
            group['failures'] += row['outcome'] != 'success'
    latencies = sorted(row['latency_ms'] for row in rows)
    summary['avg_latency_ms'] = sum(latencies)/len(latencies) if latencies else 0
    summary['p95_latency_ms'] = latencies[max(0, math.ceil(len(latencies)*0.95)-1)] if latencies else 0
    summary['coverage_percent'] = round(summary['known'] / len(rows)*100, 2) if rows else 0
    try:
        page = int(args.get('page', 1))
        limit = int(args.get('limit', 30))
        if not 1 <= page <= 1000000 or not 1 <= limit <= 100:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('分页参数无效') from None
    return {'summary': summary, 'daily': list(daily.values()), 'groups': {key: sorted(mapping.values(), key=lambda group: group['tokens'], reverse=True) for key, mapping in groups.items()}, 'heatmap': heatmap, 'options': options, 'records': rows[(page-1)*limit:page*limit], 'page': page, 'pages': max(1, math.ceil(len(rows)/limit)), 'settings': preferences, 'month_tokens': month_tokens, 'budget_exceeded': bool(preferences['monthly_token_budget'] and month_tokens >= preferences['monthly_token_budget']), 'timezone': str(zone), 'start': str(start), 'end': str(end), 'generated_at': datetime.now(zone).isoformat(), '_export': rows}
