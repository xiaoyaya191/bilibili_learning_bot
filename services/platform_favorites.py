"""Validated platform collection operations; mutations always need human review."""
import re

OPERATIONS = {'add': 'favorite', 'remove': 'favorite_remove', 'create': 'favorite_create',
              'edit': 'favorite_edit', 'delete': 'favorite_delete', 'copy': 'favorite_copy',
              'move': 'favorite_move', 'clean': 'favorite_clean'}


def validate_payload(operation, payload):
    if operation not in OPERATIONS or not isinstance(payload, dict):
        raise ValueError('未知收藏夹操作')
    allowed_keys = {'bvid', 'media_id', 'target_id', 'aids', 'title', 'introduction', 'private'}
    if set(payload) - allowed_keys:
        raise ValueError('未知收藏夹参数')
    result = dict(payload)
    for key in ('media_id', 'target_id'):
        if key in result and (type(result[key]) is not int or result[key] <= 0):
            raise ValueError(key + ' 必须是正整数')
    if operation != 'create' and not result.get('media_id'):
        raise ValueError('请指定收藏夹 media_id')
    if operation in {'copy', 'move'} and (not result.get('target_id') or result['target_id'] == result['media_id']):
        raise ValueError('请选择不同的目标收藏夹')
    if operation in {'add', 'remove'} and not re.fullmatch(r'BV[0-9a-zA-Z]{10}', str(result.get('bvid') or '')):
        raise ValueError('请指定有效 BV 号')
    if operation in {'copy', 'move'}:
        aids = result.get('aids')
        if not isinstance(aids, list) or not 1 <= len(aids) <= 100 or any(type(value) is not int or value <= 0 for value in aids):
            raise ValueError('aids 必须是 1–100 个正整数')
    if operation in {'create', 'edit'}:
        if not isinstance(result.get('title'), str) or not 1 <= len(result['title'].strip()) <= 60:
            raise ValueError('收藏夹标题应为 1–60 字符')
        result['title'] = result['title'].strip()
        if not isinstance(result.get('introduction', ''), str) or len(result.get('introduction', '')) > 500:
            raise ValueError('简介应为最多 500 字符')
        if 'private' in result and type(result['private']) is not bool:
            raise ValueError('private 必须是布尔值')
    return result


def propose(operation, payload, data_dir):
    from services.action_permissions import require
    from services.like_review import ActionReviewInbox
    require(OPERATIONS.get(operation))
    payload = validate_payload(operation, payload)
    row = ActionReviewInbox(data_dir).propose(
        OPERATIONS[operation], '平台收藏夹操作：' + operation,
        '平台写操作存在账号风险。请核对具体收藏夹和视频，再批准执行。',
        payload={'operation': operation, **payload})
    return {'ok': True, 'queued': True, 'review_id': row['id'] if row else None,
            'message': '等待人工审核' if row else '相同操作已在审核队列'}


async def execute(operation, payload, credential):
    from services.action_permissions import require
    from bilibili_api import favorite_list
    from bilibili_api.video import Video
    require(OPERATIONS.get(operation))
    payload = validate_payload(operation, {key: value for key, value in payload.items() if key != 'operation'})
    folder = payload.get('media_id')
    if operation in {'add', 'remove'}:
        video = Video(bvid=payload['bvid'], credential=credential)
        return await video.set_favorite(**{'add_media_ids' if operation == 'add' else 'del_media_ids': [folder]})
    if operation == 'create':
        return await favorite_list.create_video_favorite_list(payload['title'], payload.get('introduction', ''), payload.get('private', False), credential)
    if operation == 'edit':
        return await favorite_list.modify_video_favorite_list(folder, payload['title'], payload.get('introduction', ''), payload.get('private', False), credential)
    if operation == 'delete':
        return await favorite_list.delete_video_favorite_list([folder], credential)
    if operation == 'clean':
        return await favorite_list.clean_video_favorite_list_content(folder, credential)
    function = favorite_list.copy_video_favorite_list_content if operation == 'copy' else favorite_list.move_video_favorite_list_content
    return await function(folder, payload['target_id'], payload['aids'], credential)
