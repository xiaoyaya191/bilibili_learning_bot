import asyncio
from types import SimpleNamespace

from brain import _brain_loop
from services.video_watch_queue import DEFAULTS, VideoWatchQueue
from services import video_watch_workflow as workflow


def candidate(index, title='Python'):
    return {'bvid': f'BV1AA{index:08d}', 'title': title, 'owner': {'name': '测试'}}


def setup_selection(monkeypatch, response, interests=None):
    from core import config as config_module
    monkeypatch.setattr(config_module, 'load_config', lambda: {'video': {'candidate_pool_size': 20}, 'watch_queue': {'max_selected': 10}})
    engine = SimpleNamespace(get_keywords=lambda: interests or ['Python'], match=lambda **kwargs: SimpleNamespace(matched_keywords=['Python'] if 'Python' in kwargs['title'] else []))
    monkeypatch.setattr('services.interest_engine.InterestEngine', lambda: engine)
    async def call_ai(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=response))])
    return SimpleNamespace(_call_ai_with_retry=call_ai, interest_mgr=SimpleNamespace(get_interests=lambda: ['Python']))


def test_ai_selects_multiple_in_ai_order_not_keyword_only(monkeypatch):
    items = [candidate(1), candidate(2, '深入理解解释器'), candidate(3)]
    brain = setup_selection(monkeypatch, f'["{items[1]["bvid"]}","{items[0]["bvid"]}","{items[1]["bvid"]}"]')
    chosen = asyncio.run(_brain_loop.select_candidate_videos(brain, items))
    assert [item['bvid'] for item in chosen] == [items[1]['bvid'], items[0]['bvid']]


def test_empty_ai_result_selects_nothing(monkeypatch):
    brain = setup_selection(monkeypatch, '```json\n[]\n```')
    assert asyncio.run(_brain_loop.select_candidate_videos(brain, [candidate(1)])) == []


def test_unknown_ai_identifiers_do_not_choose_random_video(monkeypatch):
    brain = setup_selection(monkeypatch, '["BV1ZZ99999999"]')
    assert asyncio.run(_brain_loop.select_candidate_videos(brain, [candidate(1)])) == []


def test_existing_batch_is_consumed_before_another_ai_call(tmp_path, monkeypatch):
    queue = VideoWatchQueue(tmp_path / 'queue.sqlite3')
    calls = []
    async def select(_brain, items):
        calls.append(items)
        return items
    monkeypatch.setattr(_brain_loop, 'select_candidate_videos', select)
    async def exercise():
        first = await workflow.next_candidate(None, queue, [candidate(1), candidate(2)], DEFAULTS)
        assert len(queue.snapshot()['items']) == 2
        queue.finish(first['bvid'], 'done', preferences=DEFAULTS)
        second = await workflow.next_candidate(None, queue, [candidate(3)], DEFAULTS)
        assert second['bvid'] == candidate(2)['bvid']
        queue.finish(second['bvid'], 'done', preferences=DEFAULTS)
        third = await workflow.next_candidate(None, queue, [candidate(3)], DEFAULTS)
        assert third['bvid'] == candidate(3)['bvid']
    asyncio.run(exercise())
    assert len(calls) == 2


def test_content_reader_finishes_before_comments_and_failure_isolated():
    events = []
    async def content():
        events.append('content-start')
        await asyncio.sleep(0)
        events.append('content-end')
    async def comments():
        events.append('comments')
    asyncio.run(workflow.read_content_then_comments(content, comments, lambda *_: None))
    assert events == ['content-start', 'content-end', 'comments']


def test_statistics_preserve_zero_and_skip_unavailable_share(monkeypatch):
    class Video:
        def __init__(self, **kwargs):
            pass
        async def get_info(self):
            return {'aid': 10, 'stat': {'like': 0, 'reply': 3, 'favorite': 2}, 'desc': '简介'}
    async def throttle(*args):
        pass
    monkeypatch.setattr(workflow, 'Video', Video)
    monkeypatch.setattr('api.throttle._bili_throttle', throttle)
    brain = SimpleNamespace(credential=None)
    stat, text = asyncio.run(workflow.read_video_statistics(brain, candidate(1), lambda *_: None))
    assert '点赞=0' in text
    assert '评论=3' in text
    assert '转发' not in text
    assert brain._last_video_desc == '简介'


def test_platform_sync_failure_does_not_lose_local_batch(tmp_path, monkeypatch):
    queue = VideoWatchQueue(tmp_path / 'queue.sqlite3')
    queue.enqueue([candidate(1), candidate(2)], DEFAULTS)
    class Video:
        def __init__(self, **kwargs):
            pass
        async def add_to_toview(self):
            raise RuntimeError('网络错误')
    async def throttle(*args):
        pass
    monkeypatch.setattr(workflow, 'Video', Video)
    monkeypatch.setattr('api.throttle._bili_throttle', throttle)
    monkeypatch.setattr('core.platform_actions.watch_later_enabled', lambda: True)
    asyncio.run(workflow.sync_selected(queue, None, dict(DEFAULTS, sync_platform=True), lambda *_: None))
    assert len(queue.snapshot()['items']) == 2
    assert not any(row['platform_synced'] for row in queue.snapshot()['items'])
