from types import SimpleNamespace

from brain.decision import parse_video_decision, response_text


FALLBACK_CONTEXT = {
    "title": "5090 显卡维修原理分析",
    "subtitle_text": "维修过程和电路原理。" * 100,
    "comment_text": "评论补充了测量方法。" * 20,
    "danmaku_text": "",
    "visual_score": 6,
}


def test_parses_fenced_python_style_decision_and_aliases():
    raw = """分析如下：\n```python\n{'mode': '普通', 'score': '7.2/10', 'thought': '有实质内容', 'coin_intent': True, 'collect_intent': 1, 'learning_topic': '显卡维修', 'replies': []}\n```"""
    decision, fallback = parse_video_decision(raw, **FALLBACK_CONTEXT)
    assert fallback is False
    assert decision["score"] == 7.2
    assert decision["coin_intention"] is True
    assert decision["fav_intention"] is True
    assert decision["learning_topic"] == "显卡维修"


def test_invalid_decision_uses_content_based_score_instead_of_fixed_five():
    decision, fallback = parse_video_decision("这不是JSON", **FALLBACK_CONTEXT)
    assert fallback is True
    assert decision["score"] >= 6.0
    assert decision["score"] != 5.0
    assert decision["learning_topic"]


def test_parses_decision_members_when_gateway_strips_outer_braces():
    raw = '''"mode": "吐槽", "thought": "内容完整", "score": 7.4,
    "coin_intention": false, "fav_intention": true, "remember_up": false,
    "learning_topic": "动画分析", "replies": []'''
    decision, fallback = parse_video_decision(raw, **FALLBACK_CONTEXT)
    assert fallback is False
    assert decision["score"] == 7.4
    assert decision["mode"] == "吐槽"
    assert decision["fav_intention"] is True


def test_keeps_decision_fields_when_gateway_truncates_a_later_member():
    raw = (
        '"mode": "夸夸", "thought": "字幕和评论共同证明内容质量较高", '
        '"score": 8.5, "remember_up": true, "coin_intention": '
    )
    decision, fallback = parse_video_decision(raw, **FALLBACK_CONTEXT)
    assert fallback is False
    assert decision["score"] == 8.5
    assert decision["remember_up"] is True


def test_response_text_accepts_reasoning_content_gateway_shape():
    message = SimpleNamespace(content="", reasoning_content='{"score": 7}')
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)])
    assert response_text(response) == '{"score": 7}'
