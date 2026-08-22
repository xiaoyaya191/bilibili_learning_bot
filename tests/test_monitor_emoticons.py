import json

from brain import monitor


def test_default_monitor_emoticons_include_full_builtin_library():
    assert len(monitor.DEFAULT_TEXT_EMOTICONS) == 64
    assert "[doge_金箍]" in monitor.DEFAULT_TEXT_EMOTICONS
    assert "[哈欠]" in monitor.DEFAULT_TEXT_EMOTICONS


def test_legacy_default_emoticons_upgrade_without_overwriting_custom_list(monkeypatch, tmp_path):
    config_path = tmp_path / "monitor_config.json"
    monkeypatch.setattr(monitor, "MONITOR_CONFIG_FILE", str(config_path))

    config_path.write_text(
        json.dumps({"text_emoticons": ["[doge]", "[妙啊]", "[支持]"]}),
        encoding="utf-8",
    )
    assert monitor.load_monitor_config()["text_emoticons"] == monitor.DEFAULT_TEXT_EMOTICONS

    config_path.write_text(json.dumps({"text_emoticons": ["[custom]"]}), encoding="utf-8")
    assert monitor.load_monitor_config()["text_emoticons"] == ["[custom]"]
