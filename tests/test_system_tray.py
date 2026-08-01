from utils.system_tray import ISSUES_URL, OFFICIAL_SITE_URL, REPOSITORY_URL, SystemTray


class _FakeIcon:
    def __init__(self):
        self.started = False
        self.stopped = False

    def run_detached(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_tray_uses_project_links_and_draws_an_icon():
    image = SystemTray("http://127.0.0.1:18092/")._image()

    assert image.size == (64, 64)
    assert OFFICIAL_SITE_URL == "https://bxya.app"
    assert ISSUES_URL.endswith("/issues")
    assert REPOSITORY_URL.endswith("/bilibili_learning_bot")
    assert SystemTray._image().getbbox() is not None


def test_tray_start_and_stop_are_non_blocking(monkeypatch):
    tray = SystemTray("http://127.0.0.1:18092/")
    icon = _FakeIcon()
    monkeypatch.setattr(tray, "_build_icon", lambda: icon)

    assert tray.start() is True
    assert icon.started is True
    tray.stop()
    assert icon.stopped is True
