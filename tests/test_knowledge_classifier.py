from knowledge.classifier import _decode_ai_mapping
from brain.decision import decode_ai_mapping


def test_classifier_uses_first_json_object_when_model_appends_extra_data():
    result = _decode_ai_mapping(
        '{"selected_category":"科技/人工智能","confidence":0.88}'
        '\n{"debug":"ignored"}'
    )
    assert result == {"selected_category": "科技/人工智能", "confidence": 0.88}


def test_classifier_accepts_members_without_outer_braces():
    result = _decode_ai_mapping(
        '"selected_category":"科技/人工智能", "reason":"主题匹配", '
        '"is_new":true, "confidence":0.9'
    )
    assert result["selected_category"] == "科技/人工智能"
    assert result["is_new"] is True


def test_classifier_keeps_members_when_gateway_response_is_incomplete():
    result = _decode_ai_mapping(
        '"selected_category":"音乐/虚拟歌手", "reason":"歌曲创作与评论讨论", '
        '"is_new":true, "confidence":0.91, "debug":'
    )
    assert result["selected_category"] == "音乐/虚拟歌手"
    assert result["confidence"] == 0.91


def test_bulk_classifier_plan_ignores_gateway_trailing_content():
    result = decode_ai_mapping(
        '{"file_assignments":{"BV1":"\u79d1\u6280/AI/\u5de5\u5177"}}\n\n\u8fd9\u662f\u5206\u7c7b\u8bf4\u660e',
        ("category_tree", "file_assignments"),
    )
    assert result == {"file_assignments": {"BV1": "\u79d1\u6280/AI/\u5de5\u5177"}}
