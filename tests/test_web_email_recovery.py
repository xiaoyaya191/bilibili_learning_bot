# -*- coding: utf-8 -*-
"""邮箱验证找回密码：utils/email_verify 单元测试 + 面板端点集成测试。"""
import json

import pytest


@pytest.fixture(autouse=True)
def _clear_email_throttle():
    from utils import email_verify

    email_verify._SEND_ATTEMPTS.clear()
    yield
    email_verify._SEND_ATTEMPTS.clear()


# ── utils/email_verify.py ──

def test_mask_email():
    from utils.email_verify import mask_email

    assert mask_email("791433443@qq.com") == "79****43@qq.com"
    assert mask_email("ab@c.com") == "a*@c.com"
    assert mask_email("") == "****"
    assert mask_email("not-an-email") == "****"


def test_is_valid_email():
    from utils.email_verify import is_valid_email

    assert is_valid_email("791433443@qq.com") is True
    assert is_valid_email("user.name@example.co.uk") is True
    assert is_valid_email("no-at-sign") is False
    assert is_valid_email("a@b") is False
    assert is_valid_email("") is False


def test_send_throttled_cooldown_and_window():
    from utils.email_verify import send_throttled

    limited, _ = send_throttled("k1")
    assert limited is False
    limited, wait = send_throttled("k1")
    assert limited is True
    assert 0 < wait <= 60


# ── 面板端点 ──

def _setup_panel(monkeypatch, tmp_path):
    import web_panel
    import core.config as core_config

    data_dir = tmp_path / "Data"
    config_file = data_dir / "config.json"
    data_dir.mkdir()
    config_file.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(web_panel, "DATA_DIR", data_dir)
    monkeypatch.setattr(web_panel, "CONFIG_FILE", str(config_file))
    # /api/account/email 走 core.config 读写，必须同样指向临时目录
    monkeypatch.setattr(core_config, "CONFIG_FILE", str(config_file))
    web_panel.app.config.update(TESTING=True, SECRET_KEY="test-secret")
    return web_panel, web_panel.app.test_client(), config_file


def test_setup_saves_email_with_verified_code(monkeypatch, tmp_path):
    web_panel, client, config_file = _setup_panel(monkeypatch, tmp_path)
    monkeypatch.setattr(web_panel, "_email_verify_code", lambda e, c: (True, "验证通过"))
    r = client.post("/api/auth/setup", json={
        "username": "researcher", "password": "normal-password",
        "email": "791433443@qq.com", "email_code": "668873",
    })
    assert r.get_json()["ok"] is True
    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert config["web"]["email"] == "791433443@qq.com"
    assert config["web"]["email_verified"] is True


def test_setup_rejects_wrong_email_code(monkeypatch, tmp_path):
    web_panel, client, _ = _setup_panel(monkeypatch, tmp_path)
    monkeypatch.setattr(web_panel, "_email_verify_code", lambda e, c: (False, "验证码错误或已过期"))
    r = client.post("/api/auth/setup", json={
        "username": "researcher", "password": "normal-password",
        "email": "791433443@qq.com", "email_code": "000000",
    })
    assert r.get_json()["ok"] is False


def test_setup_allows_skip_email(monkeypatch, tmp_path):
    web_panel, client, config_file = _setup_panel(monkeypatch, tmp_path)
    r = client.post("/api/auth/setup", json={
        "username": "researcher", "password": "normal-password",
    })
    assert r.get_json()["ok"] is True
    config = json.loads(config_file.read_text(encoding="utf-8"))
    assert "email" not in config["web"]


def test_email_status_masks_address(monkeypatch, tmp_path):
    web_panel, client, _ = _setup_panel(monkeypatch, tmp_path)
    monkeypatch.setattr(web_panel, "_email_verify_code", lambda e, c: (True, "验证通过"))
    client.post("/api/auth/setup", json={
        "username": "researcher", "password": "normal-password",
        "email": "791433443@qq.com", "email_code": "668873",
    })
    client.post("/api/auth/logout")
    r = client.post("/api/auth/email-status", json={"username": "researcher"})
    data = r.get_json()
    assert data["ok"] is True
    assert data["has_primary"] is True
    assert data["primary_masked"] == "79****43@qq.com"
    assert "791433443" not in data["primary_masked"]
    r2 = client.post("/api/auth/email-status", json={"username": "nobody"})
    assert r2.get_json()["ok"] is False


def test_send_code_resolves_username_and_target(monkeypatch, tmp_path):
    web_panel, client, _ = _setup_panel(monkeypatch, tmp_path)
    monkeypatch.setattr(web_panel, "_email_verify_code", lambda e, c: (True, "验证通过"))
    client.post("/api/auth/setup", json={
        "username": "researcher", "password": "normal-password",
        "email": "primary@qq.com", "email_code": "111111",
    })
    client.post("/api/auth/logout")

    sent = []

    def _fake_send(email):
        sent.append(email)
        return True, "验证码已发送，请到邮箱查收（注意垃圾箱）"

    monkeypatch.setattr(web_panel, "_email_send_code", _fake_send)
    r = client.post("/api/auth/email/send-code", json={"username": "researcher", "target": "primary"})
    assert r.get_json()["ok"] is True
    assert sent == ["primary@qq.com"]


def test_send_code_relay_protection_when_logged_out(monkeypatch, tmp_path):
    web_panel, client, _ = _setup_panel(monkeypatch, tmp_path)
    client.post("/api/auth/setup", json={"username": "researcher", "password": "normal-password"})
    client.post("/api/auth/logout")

    called = []
    monkeypatch.setattr(web_panel, "_email_send_code", lambda e: called.append(e) or (True, "ok"))
    r = client.post("/api/auth/email/send-code", json={"email": "stranger@example.com"})
    assert r.status_code == 401
    assert r.get_json()["ok"] is False
    assert called == []  # 未登录 + 面板已初始化：不得对外发码


def test_reset_password_via_email_code(monkeypatch, tmp_path):
    web_panel, client, _ = _setup_panel(monkeypatch, tmp_path)
    monkeypatch.setattr(web_panel, "_email_verify_code", lambda e, c: (c == "668873", "验证通过" if c == "668873" else "验证码错误或已过期"))
    client.post("/api/auth/setup", json={
        "username": "researcher", "password": "old-password",
        "email": "791433443@qq.com", "email_code": "668873",
    })
    client.post("/api/auth/logout")

    bad = client.post("/api/auth/reset-password-email", json={
        "username": "researcher", "code": "000000", "password": "new-password",
    })
    assert bad.get_json()["ok"] is False

    good = client.post("/api/auth/reset-password-email", json={
        "username": "researcher", "code": "668873", "password": "new-password",
    })
    assert good.get_json()["ok"] is True

    client.post("/api/auth/logout")
    login = client.post("/api/auth/login", json={"username": "researcher", "password": "new-password"})
    assert login.get_json()["ok"] is True


def test_account_email_requires_code_when_changing_primary(monkeypatch, tmp_path):
    web_panel, client, _ = _setup_panel(monkeypatch, tmp_path)
    client.post("/api/auth/setup", json={"username": "researcher", "password": "normal-password"})

    no_code = client.post("/api/account/email", json={"email": "first@qq.com", "email_backup": ""})
    assert no_code.get_json()["ok"] is False

    monkeypatch.setattr(web_panel, "_email_verify_code", lambda e, c: (True, "验证通过"))
    with_code = client.post("/api/account/email", json={"email": "first@qq.com", "email_backup": "", "code": "123456"})
    assert with_code.get_json()["ok"] is True


def test_account_email_backup_change_without_code(monkeypatch, tmp_path):
    web_panel, client, config_file = _setup_panel(monkeypatch, tmp_path)
    client.post("/api/auth/setup", json={"username": "researcher", "password": "normal-password"})
    # 先通过 core.config 路径补一个已验证的主邮箱
    import core.config as core_config

    cfg = core_config.load_config()
    cfg["web"]["email"] = "primary@qq.com"
    cfg["web"]["email_verified"] = True
    core_config.save_config(cfg)

    r = client.post("/api/account/email", json={"email": "primary@qq.com", "email_backup": "backup@qq.com", "code": ""})
    assert r.get_json()["ok"] is True
    cfg2 = core_config.load_config()
    assert cfg2["web"]["email_backup"] == "backup@qq.com"
