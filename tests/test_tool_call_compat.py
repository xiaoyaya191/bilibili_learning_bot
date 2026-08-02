from services._services_ai import _extract_text_tool_call


def test_parses_gateway_textual_tool_call_with_outer_object():
    result = _extract_text_tool_call(
        '{"name":"get_video_content","arguments":{"bvid":"BV1AA1111111"}}',
        {"get_video_content"},
    )
    assert result == ("get_video_content", {"bvid": "BV1AA1111111"})


def test_parses_gateway_textual_tool_call_without_outer_braces():
    result = _extract_text_tool_call(
        '"name":"get_video_content","arguments":"{\\"bvid\\":\\"BV1BB2222222\\"}"',
        {"get_video_content"},
    )
    assert result == ("get_video_content", {"bvid": "BV1BB2222222"})


def test_rejects_a_textual_tool_call_not_in_the_supplied_tool_list():
    result = _extract_text_tool_call('{"name":"dangerous_tool","arguments":{}}', {"read_kb_file"})
    assert result is None
