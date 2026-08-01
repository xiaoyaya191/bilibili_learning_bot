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
