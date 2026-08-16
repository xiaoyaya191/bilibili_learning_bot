"""Global safety policy for actions that write to a Bilibili account."""

# Public comment replies are enabled by the account owner. They still pass
# through the existing review, sensitive-word, and platform-result checks.
ALLOW_PUBLIC_COMMENTS = True
ALLOW_AT_MENTION_REPLIES = True
ALLOW_VIDEO_LIKES = True


def public_commenting_enabled() -> bool:
    return ALLOW_PUBLIC_COMMENTS


def at_mention_replies_enabled() -> bool:
    """Whether a reply to an explicit @ mention may be sent."""
    return ALLOW_AT_MENTION_REPLIES


def video_liking_enabled() -> bool:
    return ALLOW_VIDEO_LIKES


# ===== 功能开关 =====
def _interaction_switch(key, default=True):
    """Check if an interaction feature is enabled."""
    try:
        from core.config import config
        return bool(config.get("interaction", {}).get(key, default))
    except Exception:
        return default

def commenting_enabled():
    return _interaction_switch("enable_comment")

def reply_comment_enabled():
    return _interaction_switch("enable_reply_comment")

def reply_dm_enabled():
    return _interaction_switch("enable_reply_dm")

def liking_enabled():
    return _interaction_switch("enable_like")

def coining_enabled():
    return _interaction_switch("enable_coin")

def favoriting_enabled():
    return _interaction_switch("enable_favorite")

def following_enabled():
    return _interaction_switch("enable_follow")

def watch_later_enabled():
    return _interaction_switch("enable_watch_later", True)

def active_dm_enabled():
    return _interaction_switch("enable_active_dm", True)

def owner_share_enabled():
    return _interaction_switch("enable_owner_share", True)

def dynamic_draft_enabled():
    return _interaction_switch("enable_dynamic_draft", True)

def dynamic_publish_enabled():
    return _interaction_switch("enable_dynamic_publish", False)
