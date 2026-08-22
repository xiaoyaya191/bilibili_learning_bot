from datetime import datetime, timedelta

from services.reminders import create_from_text, parse_reminder_time, take_due


def test_parse_common_chinese_reminder_times():
    now = datetime(2026, 7, 31, 10, 15)

    assert parse_reminder_time("20分钟后提醒我喝水", now=now) == now + timedelta(minutes=20)
    assert parse_reminder_time("明天晚上8点提醒我开会", now=now) == datetime(2026, 8, 1, 20, 0)
    assert parse_reminder_time("1小时20分钟后叫我休息", now=now) == now + timedelta(hours=1, minutes=20)
    assert parse_reminder_time("半小时后提醒我喝水", now=now) == now + timedelta(minutes=30)
    assert parse_reminder_time("今晚8点提醒我开会", now=now) == datetime(2026, 7, 31, 20, 0)
    assert parse_reminder_time("提醒我看视频", now=now) is None


def test_due_reminders_are_delivered_once(tmp_path):
    now = datetime(2026, 7, 31, 10, 15)
    created = create_from_text("5分钟后提醒我喝水", owner_uid="1", now=now, data_dir=tmp_path)

    assert created["ok"] is True
    assert take_due(now=now + timedelta(minutes=4), data_dir=tmp_path) == []
    due = take_due(now=now + timedelta(minutes=5), data_dir=tmp_path)
    assert due[0]["content"] == "喝水"
    assert take_due(now=now + timedelta(minutes=6), data_dir=tmp_path) == []
