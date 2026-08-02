import json

from xingye_bot.llm import ModelClient


def test_model_client_utf8_request_body_keeps_chinese_characters():
    body, headers = ModelClient._json_request_body({"prompt": "测试中文"})

    assert json.loads(body.decode("utf-8")) == {"prompt": "测试中文"}
    assert "测试中文".encode("utf-8") in body
    assert headers["Content-Type"] == "application/json; charset=utf-8"
    assert headers["Content-Length"] == str(len(body))
