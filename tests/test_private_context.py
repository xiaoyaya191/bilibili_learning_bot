import json

from persona import managers


def test_private_context_keeps_one_conversation_for_int_and_string_uid(tmp_path, monkeypatch):
    context_file = tmp_path / "private_context.json"
    monkeypatch.setattr(managers, "PRIVATE_CONTEXT_FILE", str(context_file))

    context = managers.PrivateContextDB()
    context.add_message(42, "user", "第一条消息")
    context.add_message("42", "assistant", "第一条回复")

    assert [turn["role"] for turn in context.get_context(42)] == ["user", "assistant"]
    assert "用户: 第一条消息" in context.conversation_prompt("42")
    assert "助手: 第一条回复" in context.conversation_prompt(42)

    reloaded = managers.PrivateContextDB()
    assert [turn["content"] for turn in reloaded.get_context("42")] == ["第一条消息", "第一条回复"]
    assert list(json.loads(context_file.read_text(encoding="utf-8")).keys()).count("42") == 1
