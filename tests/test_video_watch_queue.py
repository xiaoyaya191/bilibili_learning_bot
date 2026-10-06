from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from services.video_watch_queue import DEFAULTS, VideoWatchQueue, settings, validate_settings


def video(index):
    return {'bvid': f'BV1AA{index:08d}', 'title': f'视频{index}', 'owner': {'name': '测试'}}


def preferences(**changes):
    return dict(DEFAULTS, **changes)


def test_selection_is_saved_before_claim_and_survives_restart(tmp_path):
    path = tmp_path / 'queue.sqlite3'
    queue = VideoWatchQueue(path)
    assert len(queue.enqueue([video(1), video(2), video(3), video(1)], preferences())) == 3
    first = queue.claim(preferences())
    assert first['bvid'] == video(1)['bvid']
    assert queue.claim(preferences()) is None
    reopened = VideoWatchQueue(path)
    assert reopened.recover() == 1
    assert reopened.claim(preferences())['bvid'] == first['bvid']
    reopened.finish(first['bvid'], 'done', score=8.5, actions=['学习归档'], preferences=preferences())
    assert reopened.claim(preferences())['bvid'] == video(2)['bvid']
    snapshot = reopened.snapshot()
    assert snapshot['history'][0]['score'] == 8.5
    assert snapshot['history'][0]['actions'] == ['学习归档']


def test_history_optional_and_dedup_independent(tmp_path):
    queue = VideoWatchQueue(tmp_path / 'queue.sqlite3')
    prefs = preferences(keep_history=False)
    queue.enqueue([video(1)], prefs)
    queue.claim(prefs)
    queue.finish(video(1)['bvid'], 'done', preferences=prefs)
    assert not queue.snapshot()['items']
    assert not queue.snapshot()['history']
    assert queue.enqueue([video(1)], prefs) == []
    queue.clear_seen()
    assert queue.enqueue([video(1)], prefs) == [video(1)['bvid']]


def test_keep_completed_restore_and_history_retention(tmp_path):
    queue = VideoWatchQueue(tmp_path / 'queue.sqlite3')
    prefs = preferences(remove_completed=False, history_limit=1)
    queue.enqueue([video(1), video(2)], prefs)
    queue.claim(prefs)
    queue.finish(video(1)['bvid'], 'done', preferences=prefs)
    queue.restore(video(1)['bvid'])
    assert queue.claim(prefs)['bvid'] == video(1)['bvid']
    queue.finish(video(1)['bvid'], 'done', preferences=prefs)
    assert queue.claim(prefs)['bvid'] == video(2)['bvid']
    queue.finish(video(2)['bvid'], 'skipped', preferences=prefs)
    assert len(queue.snapshot()['items']) == 2
    assert queue.snapshot()['history_total'] == 1
    queue.clear_history()
    assert queue.eligible([video(1), video(2)], prefs) == []


def test_failure_retry_delay_and_exhaustion(tmp_path):
    queue = VideoWatchQueue(tmp_path / 'queue.sqlite3')
    prefs = preferences(max_retries=1, retry_delay_seconds=0)
    queue.enqueue([video(1)], prefs)
    queue.claim(prefs)
    queue.fail(video(1)['bvid'], '临时失败', preferences=prefs)
    assert queue.snapshot()['items'][0]['status'] == 'pending'
    queue.claim(prefs)
    queue.fail(video(1)['bvid'], '再次失败', preferences=prefs)
    assert queue.snapshot()['items'][0]['status'] == 'failed'
    assert not queue.pending()
    queue.retry(video(1)['bvid'])
    assert queue.claim(prefs)['bvid'] == video(1)['bvid']
    queue.fail(video(1)['bvid'], '关闭', interrupted=True, preferences=preferences(max_retries=0))
    assert queue.snapshot()['items'][0]['status'] == 'pending'


def test_delayed_item_does_not_discard_remaining_batch(tmp_path):
    queue = VideoWatchQueue(tmp_path / 'queue.sqlite3')
    prefs = preferences(retry_delay_seconds=600)
    queue.enqueue([video(1), video(2)], prefs)
    queue.claim(prefs)
    queue.fail(video(1)['bvid'], '等待重试', preferences=prefs)
    assert queue.claim(prefs)['bvid'] == video(2)['bvid']
    queue.finish(video(2)['bvid'], 'done', preferences=prefs)
    assert queue.pending()
    assert queue.claim(prefs) is None


def test_manual_prioritization_pause_and_watch_remove_guard(tmp_path):
    queue = VideoWatchQueue(tmp_path / 'queue.sqlite3')
    queue.enqueue([video(1), video(2)], preferences())
    assert queue.claim(preferences(enabled=False)) is None
    queue.prioritize(video(2)['bvid'])
    assert queue.claim(preferences())['bvid'] == video(2)['bvid']
    with pytest.raises(ValueError):
        queue.remove(video(2)['bvid'])
    queue.remove(video(1)['bvid'])
    assert len(queue.snapshot()['items']) == 1


def test_concurrent_insert_and_claim_do_not_duplicate(tmp_path):
    path = tmp_path / 'queue.sqlite3'
    queue = VideoWatchQueue(path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(lambda _: VideoWatchQueue(path).enqueue([video(1), video(2)], preferences()), range(8)))
    assert len(queue.snapshot()['items']) == 2
    with ThreadPoolExecutor(max_workers=4) as executor:
        claims = list(executor.map(lambda _: VideoWatchQueue(path).claim(preferences()), range(4)))
    assert sum(item is not None for item in claims) == 1


def test_account_queue_files_and_history_pages_are_independent(tmp_path):
    first = VideoWatchQueue(tmp_path / 'first' / 'queue.sqlite3')
    second = VideoWatchQueue(tmp_path / 'second' / 'queue.sqlite3')
    first.enqueue([video(1), video(2)], preferences())
    for index in (1, 2):
        first.claim(preferences())
        first.finish(video(index)['bvid'], 'done', preferences=preferences())
    assert first.snapshot(history_limit=1, history_offset=1)['history'][0]['bvid'] == video(1)['bvid']
    assert second.snapshot()['history_total'] == 0
    assert second.enqueue([video(1)], preferences())


@pytest.mark.parametrize('changes', [{'max_selected': -1}, {'max_selected': 101}, {'enabled': 'false'}, {'max_retries': True}, {'history_limit': 10001}, {'unknown': True}])
def test_settings_reject_invalid_values(changes):
    with pytest.raises(ValueError):
        validate_settings(changes)


def test_corrupt_database_does_not_silently_reset(tmp_path):
    path = tmp_path / 'queue.sqlite3'
    path.write_text('not a database', encoding='utf-8')
    with pytest.raises(Exception):
        VideoWatchQueue(path)
    assert path.read_text(encoding='utf-8') == 'not a database'


def test_interrupted_coin_or_comment_attempt_is_not_sent_twice(tmp_path):
    path = tmp_path / 'queue.sqlite3'
    queue = VideoWatchQueue(path)
    queue.enqueue([video(1)], preferences())
    queue.claim(preferences())
    assert queue.reserve_action(video(1)['bvid'], 'coin')
    assert queue.reserve_action(video(1)['bvid'], 'comment:42')
    reopened = VideoWatchQueue(path)
    reopened.recover()
    reopened.claim(preferences())
    assert not reopened.reserve_action(video(1)['bvid'], 'coin')
    assert not reopened.reserve_action(video(1)['bvid'], 'comment:42')
    assert reopened.snapshot()['items'][0]['attempts'] == 1


def test_history_stores_final_assessment(tmp_path):
    queue = VideoWatchQueue(tmp_path / 'queue.sqlite3')
    queue.enqueue([video(1)], preferences())
    queue.claim(preferences())
    queue.finish(video(1)['bvid'], 'done', score=8, assessment={'thought': '内容完整', 'like_intention': True}, preferences=preferences())
    assert queue.snapshot()['history'][0]['assessment']['thought'] == '内容完整'


def test_abrupt_process_exit_keeps_remaining_batch(tmp_path):
    import os
    import subprocess
    import sys

    path = tmp_path / 'queue.sqlite3'
    source = "from services.video_watch_queue import VideoWatchQueue,DEFAULTS; import os; queue=VideoWatchQueue(" + repr(str(path)) + "); queue.enqueue(" + repr([video(1), video(2), video(3)]) + ",DEFAULTS); queue.claim(DEFAULTS); os._exit(19)"
    environment = dict(os.environ, BILI_USER_DATA_DIR=str(tmp_path / 'isolated'), BILI_ACCOUNT_ID='queue-crash-test')
    result = subprocess.run([sys.executable, '-c', source], cwd=Path(__file__).resolve().parents[1], env=environment, timeout=30, capture_output=True)
    assert result.returncode == 19
    reopened = VideoWatchQueue(path)
    assert len(reopened.snapshot()['items']) == 3
    assert reopened.recover() == 1
    assert reopened.claim(preferences())['bvid'] == video(1)['bvid']


def test_manual_metadata_is_saved_for_history(tmp_path):
    queue = VideoWatchQueue(tmp_path / 'queue.sqlite3')
    queue.enqueue([video(1)], preferences())
    target = queue.claim(preferences())
    target['title'] = '实际标题'
    target['aid'] = 123
    queue.update_video(target)
    queue.finish(target['bvid'], 'done', preferences=preferences())
    saved = queue.snapshot()['history'][0]['video']
    assert saved['title'] == '实际标题'
    assert '_watch_queue_id' not in saved
