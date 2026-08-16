from brain.decision import decode_ai_mapping


def test_private_message_tool_plan_ignores_trailing_gateway_text():
    result = decode_ai_mapping(
        '{"recommend_videos":true,"video_search":"AI"}\nextra explanation',
        ("recommend_videos", "video_search"),
    )
    assert result == {"recommend_videos": True, "video_search": "AI"}


def test_knowledge_verification_mapping_keeps_first_complete_object():
    result = decode_ai_mapping(
        '{"overall_reliable":true,"overall_score":0.9,"issues":[]}\n{"debug":true}',
        ("overall_reliable", "overall_score", "issues"),
    )
    assert result["overall_reliable"] is True
    assert result["overall_score"] == 0.9
