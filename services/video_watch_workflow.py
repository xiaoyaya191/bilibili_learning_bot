"""Queue-aware selection and ordered video observation helpers."""
from __future__ import annotations

from bilibili_api.video import Video

from services.video_watch_queue import VideoWatchQueue, settings


async def next_candidate(brain, queue: VideoWatchQueue, items: list[dict], preferences: dict) -> dict | None:
    existing = queue.claim(preferences)
    if existing or queue.pending():
        return existing
    from brain._brain_loop import select_candidate_videos
    selected = await select_candidate_videos(brain, queue.eligible(items, preferences))
    queue.enqueue(selected, preferences)
    return queue.claim(preferences)


async def prepare_target(target: dict, credential, log) -> dict:
    if target.get('aid') or target.get('id'):
        return target
    from api.throttle import _bili_throttle
    await _bili_throttle('获取队列视频信息')
    info = await Video(bvid=target['bvid'], credential=credential).get_info()
    if not isinstance(info, dict) or not info.get('aid'):
        raise ValueError('队列视频不可用或缺少视频ID')
    target.update({key: info[key] for key in ('aid', 'title', 'owner', 'pic', 'duration', 'desc', 'stat') if key in info})
    return target


async def sync_selected(queue: VideoWatchQueue, credential, preferences: dict, log) -> None:
    if not preferences['sync_platform']:
        return
    from core.platform_actions import watch_later_enabled
    if not watch_later_enabled():
        return
    for row in queue.snapshot(history_limit=0)['items']:
        if row['platform_synced'] or row['status'] not in ('pending', 'watching'):
            continue
        try:
            from api.throttle import _bili_throttle
            await _bili_throttle('候选加入稍后再看')
            await Video(bvid=row['bvid'], credential=credential).add_to_toview()
            queue.mark_synced(row['bvid'])
        except Exception as error:
            log(f"B站稍后再看同步失败，视频已保存在本地队列: {row['bvid']} | {error}", 'WARN')


async def finish_selected(queue: VideoWatchQueue, target: dict, outcome: str, credential, *, score=None, actions=None, assessment=None, preferences: dict, log) -> None:
    if preferences['remove_platform_completed']:
        from core.platform_actions import watch_later_enabled
        row = next((row for row in queue.snapshot(history_limit=0)['items'] if row['bvid'] == target['bvid']), None)
        if row and row['platform_synced'] and watch_later_enabled():
            try:
                from api.throttle import _bili_throttle
                await _bili_throttle('已观看移出稍后再看')
                await Video(bvid=target['bvid'], credential=credential).delete_from_toview()
            except Exception as error:
                log(f"B站稍后再看移除失败，保留平台条目: {error}", 'WARN')
    queue.finish(target['bvid'], outcome, score=score, actions=actions, assessment=assessment, preferences=preferences)


async def read_content_then_comments(content_reader, comment_reader, log) -> None:
    for label, reader in (('视频内容', content_reader), ('评论与弹幕', comment_reader)):
        try:
            await reader()
        except Exception as error:
            log(f'{label}读取失败: {error}', 'WARN')


async def read_video_statistics(brain, target: dict, log) -> tuple[dict, str]:
    stat = dict(target.get('stat') or {}) if isinstance(target.get('stat'), dict) else {}
    try:
        from api.throttle import _bili_throttle
        await _bili_throttle('查看视频数据')
        info = await Video(bvid=target['bvid'], credential=brain.credential).get_info()
        if isinstance(info, dict):
            stat.update(info.get('stat') or {})
            brain._last_video_desc = str(info.get('desc') or '')
            if info.get('aid'):
                target['aid'] = info['aid']
    except Exception as error:
        log(f'视频数据读取失败，使用可用字段，缺失字段跳过: {error}', 'WARN')
    text = []
    for key, label in (('view', '播放'), ('like', '点赞'), ('reply', '评论'), ('favorite', '收藏'), ('share', '转发')):
        value = stat.get(key)
        if value is not None:
            text.append(f'{label}={value}')
    return stat, ' | '.join(text) or '暂无可用统计，已跳过'
