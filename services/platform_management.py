"""Explicit-target AI platform actions submitted only through human review."""
import re

ACTIONS = {'video_like', 'video_unlike', 'coin', 'follow_up', 'unfollow_user',
           'public_comment', 'comment_like', 'comment_delete', 'private_reply',
           'send_danmaku', 'danmaku_like', 'dynamic_delete', 'dynamic_like', 'dynamic_repost'}


def validate(action, payload):
    if action not in ACTIONS or not isinstance(payload, dict):
        raise ValueError('未知平台管理操作')
    fields = {
        'video_like': {'bvid'}, 'video_unlike': {'bvid'}, 'coin': {'bvid', 'num'},
        'follow_up': {'uid'}, 'unfollow_user': {'uid'},
        'public_comment': {'oid', 'text', 'root', 'parent'},
        'comment_like': {'oid', 'rpid'}, 'comment_delete': {'oid', 'rpid'},
        'private_reply': {'receiver_id', 'text'}, 'send_danmaku': {'bvid', 'text'},
        'danmaku_like': {'bvid', 'dmid', 'cid'}, 'dynamic_delete': {'dynamic_id'},
        'dynamic_like': {'dynamic_id'}, 'dynamic_repost': {'dynamic_id', 'text'},
    }
    if set(payload) - fields[action]:
        raise ValueError('未知平台管理参数')
    if 'bvid' in fields[action] and not re.fullmatch(r'BV[0-9A-Za-z]{10}', str(payload.get('bvid') or '')):
        raise ValueError('请指定有效 BV 号')
    for key in fields[action] - {'bvid', 'text', 'num', 'root', 'parent'}:
        if type(payload.get(key)) is not int or payload[key] <= 0:
            raise ValueError(key + ' 必须为正整数')
    for key in {'root', 'parent'} & set(payload):
        if type(payload[key]) is not int or payload[key] < 0:
            raise ValueError(key + ' 必须为非负整数')
    if 'text' in fields[action] and (not isinstance(payload.get('text'), str) or not 1 <= len(payload['text'].strip()) <= 2000):
        raise ValueError('文本应为 1–2000 字符')
    if action == 'coin' and (type(payload.get('num', 1)) is not int or payload.get('num', 1) not in (1, 2)):
        raise ValueError('投币数量只能为 1 或 2')
    return dict(payload)


def propose(action, payload, directory):
    from services.action_permissions import require
    from services.like_review import ActionReviewInbox
    require(action)
    payload = validate(action, payload)
    if action in {'public_comment', 'private_reply', 'dynamic_repost'}:
        from xingye_bot.bilibili_ops import _political_hits, _with_ai_marker
        if _political_hits(payload['text']):
            raise ValueError('文本未通过安全检查')
        payload['text'] = _with_ai_marker(payload['text'])
    row = ActionReviewInbox(directory).propose(action, 'AI 平台操作：' + action,
        '请检查目标与内容后人工批准。授权不代表自动执行。', payload=payload)
    return {'ok': True, 'queued': True, 'review_id': row['id'] if row else None}


async def execute(action, payload, credential):
    from services.action_permissions import require
    from bilibili_api import video, user, comment, session, dynamic
    require(action)
    payload = validate(action, payload)
    if action in {'video_like', 'video_unlike', 'coin', 'send_danmaku', 'danmaku_like'}:
        target = video.Video(bvid=payload['bvid'], credential=credential)
        if action in {'video_like', 'video_unlike'}:
            return await target.like(status=action == 'video_like')
        if action == 'coin':
            return await target.pay_coin(num=payload.get('num', 1), like=False)
        if action == 'danmaku_like':
            return await target.like_danmaku(dmid=payload['dmid'], cid=payload['cid'])
        from bilibili_api import Danmaku
        return await target.send_danmaku(danmaku=Danmaku(payload['text']), page_index=0)
    if action in {'follow_up', 'unfollow_user'}:
        target = user.User(payload['uid'], credential)
        return await target.modify_relation(user.RelationType.SUBSCRIBE if action == 'follow_up' else user.RelationType.UNSUBSCRIBE)
    if action in {'comment_like', 'comment_delete'}:
        target = comment.Comment(payload['oid'], comment.CommentResourceType.VIDEO, payload['rpid'], credential)
        return await (target.delete() if action == 'comment_delete' else target.like(True))
    if action == 'public_comment':
        return await comment.send_comment(payload['text'], oid=payload['oid'], type_=comment.CommentResourceType.VIDEO,
                                          root=payload.get('root'), parent=payload.get('parent'), credential=credential)
    if action == 'private_reply':
        return await session.send_msg(credential=credential, receiver_id=payload['receiver_id'], msg_type=session.EventType.TEXT, content=payload['text'])
    target = dynamic.Dynamic(payload['dynamic_id'], credential)
    if action == 'dynamic_delete':
        return await target.delete()
    if action == 'dynamic_like':
        return await target.set_like(True)
    return await target.repost(payload['text'])
