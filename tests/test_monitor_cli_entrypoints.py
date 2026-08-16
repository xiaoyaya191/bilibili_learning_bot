import asyncio


def test_monitor_cli_entrypoints_are_importable():
    from brain.monitor import configure_monitor_cli, main

    assert callable(configure_monitor_cli)
    assert callable(main)


def test_monitor_main_runs_monitor_instance(monkeypatch):
    import brain.monitor as monitor

    class FakeMonitor:
        async def run(self):
            return "monitor-ran"

    monkeypatch.setattr(monitor, "MonitorBot", FakeMonitor)

    assert asyncio.run(monitor.main()) == "monitor-ran"
