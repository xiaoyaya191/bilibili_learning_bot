from core.platform_actions import (
    at_mention_replies_enabled,
    public_commenting_enabled,
    video_liking_enabled,
)


def test_public_commenting_is_available_after_the_policy_checks():
    assert public_commenting_enabled() is True


def test_explicit_at_mention_replies_are_available():
    assert at_mention_replies_enabled() is True


def test_video_liking_is_available_for_reviewed_actions():
    assert video_liking_enabled() is True


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
