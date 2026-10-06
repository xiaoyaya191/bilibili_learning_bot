"""Bounded retries compare timeline coverage instead of accepting first JSON."""
import asyncio


def valid_segments(body):
    if not isinstance(body, list):
        return []
    result = []
    for segment in body[:50000]:
        if not isinstance(segment, dict) or not isinstance(segment.get('content'), str):
            continue
        try:
            start = float(segment.get('from', 0))
            end = float(segment.get('to', start))
            if 0 <= start <= end and end < 86400 and segment['content'].strip():
                result.append({'from': start, 'to': end, 'content': segment['content'].strip()})
        except (ValueError, TypeError):
            continue
    return sorted(result, key=lambda segment: (segment['from'], segment['to']))


async def fetch_candidates(client, url, attempts=3, evaluator=None):
    candidates = []
    for attempt in range(max(1, min(5, int(attempts)))):
        if attempt:
            await asyncio.sleep(0.3)
        try:
            separator = '&' if '?' in url else '?'
            response = await client.get(url + (f'{separator}_retry={attempt}' if attempt else ''))
            response.raise_for_status()
            body = valid_segments(response.json().get('body', []))
            if body:
                candidates.append(body)
        except (ValueError, TypeError, AttributeError, OSError):
            continue
        except Exception as error:
            import httpx
            if not isinstance(error, httpx.HTTPError):
                raise
    if not candidates:
        return []
    def quality(body):
        coverage = 0.0
        covered_end = 0.0
        for item in body:
            coverage += max(0, item['to'] - max(item['from'], covered_end))
            covered_end = max(covered_end, item['to'])
        semantic_priority = 0
        if evaluator is not None:
            status = evaluator(' '.join(item['content'] for item in body)).get('status')
            semantic_priority = 1 if status == 'match' else -1 if status == 'mismatch' else 0
        return semantic_priority, coverage, len(body), sum(len(item['content']) for item in body)
    return await asyncio.to_thread(max, candidates, key=quality)
