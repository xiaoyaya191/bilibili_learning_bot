"""Time-based behavior policies shared by CLI and runtime services."""
from __future__ import annotations

from datetime import datetime


def is_quiet_period(now: datetime, start_hour: int = 22, end_hour: int = 8) -> bool:
    """Return whether local time is inside a possibly overnight quiet period."""
    start = max(0, min(23, int(start_hour)))
    end = max(0, min(23, int(end_hour)))
    if start == end:
        return False
    if start < end:
        return start <= now.hour < end
    return now.hour >= start or now.hour < end
