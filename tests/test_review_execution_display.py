import web_panel


def test_private_reply_execution_display_hides_raw_platform_response():
    raw = {"msg_key": "abc123", "e_infos": [{"text": "[doge]"}]}

    display = web_panel._review_execution_display("private_reply", raw)

    assert display.startswith("私信已提交并得到 B 站确认")
    assert "msg_key" not in display
    assert "e_infos" not in display


def test_legacy_raw_execution_display_becomes_generic_confirmation():
    display = web_panel._review_execution_display(
        "video_like", {"result": '{"code":0,"msg_key":"legacy"}'}
    )

    assert display == "平台已确认执行"
