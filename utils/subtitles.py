"""Shared subtitle utilities."""


def subtitle_priority(subtitle: dict) -> int:
    """Return lower score for preferred subtitle tracks.

    Priority: AI Chinese > human Chinese > other Chinese > other AI > others.
    """
    lan = subtitle.get("lan", "")
    if lan == "ai-zh":
        return 0
    if lan == "zh":
        return 10
    if "zh" in lan:
        return 20
    if lan.startswith("ai-"):
        return 30
    return 50
