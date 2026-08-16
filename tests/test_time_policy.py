from datetime import datetime

from core.time_policy import is_quiet_period


def test_overnight_quiet_period_blocks_late_night_and_early_morning():
    assert is_quiet_period(datetime(2026, 7, 29, 1, 30), 22, 8) is True
    assert is_quiet_period(datetime(2026, 7, 29, 23, 0), 22, 8) is True
    assert is_quiet_period(datetime(2026, 7, 29, 12, 0), 22, 8) is False


def test_same_start_and_end_disables_quiet_period():
    assert is_quiet_period(datetime(2026, 7, 29, 1, 30), 8, 8) is False
