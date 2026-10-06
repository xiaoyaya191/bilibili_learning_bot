from core.platform_actions import (
    at_mention_replies_enabled,
    public_commenting_enabled,
    video_liking_enabled,
)


def test_public_commenting_is_disabled_without_explicit_permission(monkeypatch):
    monkeypatch.setattr('core.config.load_config', lambda: {})
    assert public_commenting_enabled() is False


def test_explicit_at_mention_replies_need_permission(monkeypatch):
    monkeypatch.setattr('core.config.load_config', lambda: {})
    assert at_mention_replies_enabled() is False


def test_video_liking_needs_permission_even_for_reviewed_actions(monkeypatch):
    monkeypatch.setattr('core.config.load_config', lambda: {})
    assert video_liking_enabled() is False


def test_all_write_paths_check_the_global_policy():
    paths = {
        "brain/comment.py": "public_commenting_enabled",
        "brain/_brain_loop.py": "video_liking_enabled",
        "brain/standby.py": "public_commenting_enabled",
        "xingye_bot/bilibili_ops.py": "video_liking_enabled",
    }
    for path, marker in paths.items():
        with open(path, encoding="utf-8") as source:
            assert marker in source.read()
