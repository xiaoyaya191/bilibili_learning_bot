"""Global safety policy for actions that write to a Bilibili account."""

def public_commenting_enabled() -> bool:
    return platform_action_enabled('public_comment')


def at_mention_replies_enabled() -> bool:
    """Whether a reply to an explicit @ mention may be sent."""
    return platform_action_enabled('public_comment')


def video_liking_enabled() -> bool:
    return platform_action_enabled('video_like')


# ===== 功能开关 =====
def _interaction_switch(key, default=True):
    """Check if an interaction feature is enabled."""
    try:
        from core.config import load_config
        config = load_config()
        mapping = {
            "enable_comment": "public_comment", "enable_reply_comment": "public_comment",
            "enable_reply_dm": "private_reply", "enable_like": "video_like",
            "enable_coin": "coin", "enable_favorite": "favorite", "enable_follow": "follow_up",
            "enable_watch_later": "watch_later", "enable_dynamic_publish": "dynamic_publish",
            "enable_active_dm": "private_reply", "enable_owner_share": "private_reply",
            "enable_dynamic_draft": "dynamic_draft",
        }
        action = mapping.get(key)
        if action:
            from services.action_permissions import allowed
            return allowed(action, config)
        if key == 'enable_asr':
            return config.get('asr', {}).get('enabled', False) is True
        if key == "enable_monitor":
            return bool(config.get("interaction", {}).get(key, default))
        return bool(config.get("interaction", {}).get(key, default))
    except Exception:
        return False

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


def platform_action_enabled(action: str) -> bool:
    from services.action_permissions import allowed
    return allowed(action)
