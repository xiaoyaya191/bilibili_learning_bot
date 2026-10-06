from pathlib import Path


def test_settings_section_cannot_be_hidden():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")
    assert "x.dataset.pg!=='conf'" in template
    assert "delete hidden.conf" in template
    assert "主要使用方式" not in template
    assert "learning-workspace.js" in template


def test_removed_free_channel_is_not_rendered():
    template = (Path(__file__).resolve().parents[1] / "web_panel.html").read_text(encoding="utf-8")
    assert "cqFreeChannelRow" not in template
    assert "btnFreeChannelOn" not in template
