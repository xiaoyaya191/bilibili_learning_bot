from utils.system_tray import ISSUES_URL, OFFICIAL_SITE_URL, REPOSITORY_URL, SystemTray


class _FakeIcon:
    def __init__(self):
        self.started = False
        self.stopped = False

    def run(self):
        self.started = True

    def run_detached(self):
        self.started = True

    def stop(self):
        self.stopped = True


def test_tray_uses_project_links_and_draws_an_icon():
    image = SystemTray("http://127.0.0.1:18092/")._image()

    assert image.size == (64, 64)
    assert OFFICIAL_SITE_URL == "https://bxya.top"
    assert ISSUES_URL.endswith("/issues")
    assert REPOSITORY_URL.endswith("/bilibili_learning_bot")
    assert SystemTray._image().getbbox() is not None


def test_tray_start_and_stop_are_non_blocking(monkeypatch):
    import utils.system_tray as st

    tray = SystemTray("http://127.0.0.1:18092/")
    icon = _FakeIcon()
    monkeypatch.setattr(tray, "_build_icon", lambda: icon)
    # 测试隔离：机器上若有正在运行的实例持有全局托盘互斥体，
    # 不应影响本测试（单测不依赖机器全局状态）
    monkeypatch.setattr(st, "acquire_tray_ownership", lambda: True)
    monkeypatch.setattr(st, "release_tray_ownership", lambda: None)

    assert tray.start() is True
    assert icon.started is True
    tray.stop()
    assert icon.stopped is True
