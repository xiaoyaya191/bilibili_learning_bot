"""完整日志与学习实况共用同一时间轴：日期 + 跨源排序。"""
import web_panel


def test_runtime_log_lines_use_full_datetime_timestamp():
    line = web_panel._timestamp_runtime_line("monitor event")
    assert line.startswith("[2026-")
    assert web_panel._LOG_CLOCK_RE.search(line)


def test_existing_time_only_prefix_is_preserved():
    assert web_panel._timestamp_runtime_line("[12:00:01] existing") == "[12:00:01] existing"


def test_sort_key_orders_across_days():
    old = web_panel._runtime_log_sort_key("[2026-08-03 23:59:59] yesterday", 0)
    new = web_panel._runtime_log_sort_key("[2026-08-04 00:00:01] today", 1)
    assert old < new


def test_lines_without_timestamp_sort_last():
    plain = web_panel._runtime_log_sort_key("some raw line", 0)
    dated = web_panel._runtime_log_sort_key("[2026-08-04 10:00:00] dated", 1)
    assert dated < plain
