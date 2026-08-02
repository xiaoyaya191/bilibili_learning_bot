import base64


def test_qr_done_callback_extracts_all_required_cookies():
    import web_panel

    cookies = web_panel._cookies_from_qr_done_event({
        "url": (
            "https://www.bilibili.com/?SESSDATA=abc%2Cdef%3Aghi"
            "&bili_jct=csrf-token-123&DedeUserID=10001"
        ),
        "refresh_token": "refresh-token-123",
    })

    assert cookies["SESSDATA"] == "abc%2Cdef%3Aghi"
    assert cookies["bili_jct"] == "csrf-token-123"
    assert cookies["DedeUserID"] == "10001"
    assert cookies["ac_time_value"] == "refresh-token-123"


def test_qr_done_callback_extracts_nested_cookie_payload():
    import web_panel

    cookies = web_panel._cookies_from_qr_done_event({
        "code": 0,
        "data": {
            "url": (
                "https://www.bilibili.com/?SESSDATA=abc%2Cdef%3Aghi"
                "&bili_jct=csrf-token-123&DedeUserID=10001"
            ),
            "refresh_token": "refresh-token-123",
        },
    })

    assert cookies["SESSDATA"] == "abc%2Cdef%3Aghi"
    assert cookies["bili_jct"] == "csrf-token-123"
    assert cookies["DedeUserID"] == "10001"


def _allow_web_request(monkeypatch, web_panel):
    monkeypatch.setitem(web_panel.app.before_request_funcs, None, [])


def test_qr_start_requires_an_image_and_serves_png(monkeypatch):
    import web_panel

    _allow_web_request(monkeypatch, web_panel)
    png = b"\x89PNG\r\n\x1a\nexample"

    def fake_qr_login(*_args):
        state = dict(web_panel.qr_state)
        state.update({
            "active": True,
            "url": "https://passport.bilibili.com/qrcode",
            "status": "waiting_scan",
            "message": "请使用 B站APP 扫描二维码",
            "uid": "",
            "img_b64": base64.b64encode(png).decode("ascii"),
        })
        web_panel.qr_state = state

    monkeypatch.setattr(web_panel, "do_qr_login", fake_qr_login)
    client = web_panel.app.test_client()

    started = client.post("/api/bili/qr/start")
    assert started.status_code == 200
    assert started.get_json()["ok"] is True
    assert started.get_json()["img"]

    image = client.get("/api/bili/qr/image")
    assert image.status_code == 200
    assert image.mimetype == "image/png"
    assert image.data == png


def test_qr_start_reuses_active_qr_instead_of_hiding_it(monkeypatch):
    import web_panel

    _allow_web_request(monkeypatch, web_panel)
    png = b"\x89PNG\r\n\x1a\nactive"
    web_panel.qr_state = {
        "active": True,
        "url": "https://passport.bilibili.com/qrcode",
        "status": "waiting_scan",
        "message": "请使用 B站APP 扫描二维码",
        "uid": "",
        "img_b64": base64.b64encode(png).decode("ascii"),
    }
    worker_started = []
    monkeypatch.setattr(web_panel.threading, "Thread", lambda *args, **kwargs: worker_started.append(True))

    response = web_panel.app.test_client().post("/api/bili/qr/start")

    assert response.status_code == 200
    assert response.get_json()["ok"] is True
    assert response.get_json()["reused"] is True
    assert response.get_json()["img"]
    assert not worker_started


def test_qr_start_force_replaces_an_active_qr(monkeypatch):
    import web_panel

    _allow_web_request(monkeypatch, web_panel)
    web_panel.qr_state = {
        "active": True,
        "url": "https://passport.bilibili.com/qrcode-old",
        "status": "waiting_scan",
        "message": "旧二维码",
        "uid": "",
        "img_b64": "old",
        "session_id": "old-session",
    }
    started = []

    class FakeThread:
        def __init__(self, target, args=(), daemon=False):
            self.target = target
            self.args = args

        def start(self):
            started.append(self.args)

    monkeypatch.setattr(web_panel.threading, "Thread", FakeThread)
    monkeypatch.setattr(web_panel.time, "sleep", lambda *_args: None)
    response = web_panel.app.test_client().post("/api/bili/qr/start", json={"force": True})

    assert response.status_code == 503
    assert started and started[0]
    assert web_panel.qr_state["session_id"] != "old-session"
    assert web_panel.qr_state["status"] == "generating"


def test_qr_login_rejects_incomplete_credential(monkeypatch, tmp_path):
    import asyncio
    import sys
    import types
    import web_panel

    class FakeQr:
        def __init__(self):
            self._QrCodeLogin__qr_link = "https://passport.bilibili.com/qrcode"

        async def generate_qrcode(self):
            return None

    fake_module = types.ModuleType("bilibili_api.login_v2")
    fake_module.QrCodeLogin = FakeQr
    monkeypatch.setitem(sys.modules, "bilibili_api.login_v2", fake_module)
    async def incomplete_done_event(_qr):
        return {"code": 0, "url": "https://www.bilibili.com/?SESSDATA=", "refresh_token": ""}
    monkeypatch.setattr(web_panel, "_poll_qr_login_event", incomplete_done_event)
    monkeypatch.setattr(web_panel, "_cookies_from_qr_callback_redirect", lambda _url: {})
    monkeypatch.setattr(web_panel, "COOKIE_FILE", tmp_path / "bilibili_cookies.json")
    monkeypatch.setattr(web_panel, "QR_CODES_DIR", tmp_path / "qr_codes")
    web_panel.qr_state = {"active": False, "url": "", "status": "idle", "message": "", "uid": "", "img_b64": ""}

    web_panel.do_qr_login()

    assert web_panel.qr_state["status"] == "error"
    assert "未返回完整登录凭据" in web_panel.qr_state["message"]
    assert not web_panel.COOKIE_FILE.exists()


def test_qr_login_saves_complete_credentials_from_done_event(monkeypatch, tmp_path):
    import sys
    import types
    import web_panel

    class FakeQr:
        def __init__(self):
            self._QrCodeLogin__qr_link = "https://passport.bilibili.com/qrcode"
            self._QrCodeLogin__qr_key = "test-key"

        async def generate_qrcode(self):
            return None

    fake_module = types.ModuleType("bilibili_api.login_v2")
    fake_module.QrCodeLogin = FakeQr
    monkeypatch.setitem(sys.modules, "bilibili_api.login_v2", fake_module)
    monkeypatch.setattr(web_panel, "COOKIE_FILE", tmp_path / "bilibili_cookies.json")
    monkeypatch.setattr(web_panel, "QR_CODES_DIR", tmp_path / "qr_codes")

    async def complete_done_event(_qr):
        return {
            "code": 0,
            "url": (
                "https://www.bilibili.com/?SESSDATA=abc%2Cdef%3Aghi"
                "&bili_jct=csrf-token-123&DedeUserID=10001"
            ),
            "refresh_token": "refresh-token-123",
        }

    monkeypatch.setattr(web_panel, "_poll_qr_login_event", complete_done_event)
    web_panel.do_qr_login()

    saved = web_panel.read_json(web_panel.COOKIE_FILE)
    assert saved["SESSDATA"] == "abc%2Cdef%3Aghi"
    assert saved["bili_jct"] == "csrf-token-123"
    assert saved["DedeUserID"] == "10001"
    assert web_panel.qr_state["status"] == "success"


def test_qr_login_exchanges_modern_callback_for_cookies(monkeypatch, tmp_path):
    import sys
    import types
    import web_panel

    class FakeQr:
        def __init__(self):
            self._QrCodeLogin__qr_link = "https://passport.bilibili.com/qrcode"
            self._QrCodeLogin__qr_key = "test-key"

        async def generate_qrcode(self):
            return None

    fake_module = types.ModuleType("bilibili_api.login_v2")
    fake_module.QrCodeLogin = FakeQr
    monkeypatch.setitem(sys.modules, "bilibili_api.login_v2", fake_module)
    monkeypatch.setattr(web_panel, "COOKIE_FILE", tmp_path / "bilibili_cookies.json")
    monkeypatch.setattr(web_panel, "QR_CODES_DIR", tmp_path / "qr_codes")

    async def modern_done_event(_qr):
        return {"code": 0, "url": "https://passport.bilibili.com/modern-callback", "refresh_token": "refresh-token-123"}

    monkeypatch.setattr(web_panel, "_poll_qr_login_event", modern_done_event)
    monkeypatch.setattr(web_panel, "_cookies_from_qr_callback_redirect", lambda _url: {
        "SESSDATA": "abc%2Cdef%3Aghi",
        "bili_jct": "csrf-token-123",
        "DedeUserID": "10001",
        "buvid3": "",
    })
    web_panel.do_qr_login()

    saved = web_panel.read_json(web_panel.COOKIE_FILE)
    assert saved["SESSDATA"] == "abc%2Cdef%3Aghi"
    assert saved["bili_jct"] == "csrf-token-123"
    assert saved["DedeUserID"] == "10001"


def test_qr_start_reports_missing_image(monkeypatch):
    import web_panel

    _allow_web_request(monkeypatch, web_panel)
    def fake_failed_qr_login(*_args):
        state = dict(web_panel.qr_state)
        state.update({
            "active": False,
            "status": "error",
            "message": "二维码服务不可用",
            "img_b64": "",
        })
        web_panel.qr_state = state

    monkeypatch.setattr(web_panel, "do_qr_login", fake_failed_qr_login)
    web_panel.qr_state = {"active": False, "status": "idle", "message": "", "img_b64": ""}
    client = web_panel.app.test_client()

    response = client.post("/api/bili/qr/start")
    assert response.status_code == 503
    assert response.get_json()["ok"] is False
