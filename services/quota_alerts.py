"""Local, provider-neutral AI quota and billing email alerts.

This module deliberately does not attempt to query an arbitrary OpenAI-compatible
provider's balance: gateways do not expose a common balance API.  Instead it
alerts on explicit provider billing errors and, when available, the project's
locally recorded cost total.
"""
from __future__ import annotations

import json
import os
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from core.config import DATA_DIR, _cipher_decrypt, _cipher_encrypt, load_config, save_config
from utils.display import redact_sensitive_text

_STATE_FILE = Path(DATA_DIR) / "quota_alert_state.json"
_LOCK = threading.Lock()
_BILLING_MARKERS = (
    "http 402", "payment required", "insufficient balance", "insufficient quota",
    "quota exceeded", "balance exhausted", "余额不足", "配额不足", "配额已用完",
)


def is_billing_error(value: Any) -> bool:
    text = str(value or "").lower()
    return any(marker in text for marker in _BILLING_MARKERS)


def _settings() -> dict:
    cfg = load_config()
    section = cfg.get("quota_alert", {})
    return section if isinstance(section, dict) else {}


def _state() -> dict:
    try:
        value = json.loads(_STATE_FILE.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_state(value: dict) -> None:
    try:
        _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        temp = _STATE_FILE.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, _STATE_FILE)
    except OSError:
        pass


def _redacted_address(value: str) -> str:
    value = str(value or "").strip()
    if "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    return (local[:2] + "***@" + domain) if local else "***@" + domain


def status() -> dict:
    cfg = _settings()
    saved_password = bool(cfg.get("smtp_password_encrypted"))
    env_password = bool(os.getenv("BILI_ALERT_SMTP_PASSWORD", "").strip())
    state = _state()
    return {
        "ok": True,
        "enabled": bool(cfg.get("enabled", False)),
        "email_enabled": bool(cfg.get("email_enabled", False)),
        "review_required": bool(cfg.get("review_required", False)),
        "smtp_host": str(cfg.get("smtp_host", "")).strip(),
        "smtp_port": int(cfg.get("smtp_port", 465) or 465),
        "smtp_security": str(cfg.get("smtp_security", "ssl") or "ssl"),
        "smtp_username": _redacted_address(str(cfg.get("smtp_username", ""))),
        "smtp_sender": _redacted_address(str(cfg.get("smtp_sender", ""))),
        "recipient_email": _redacted_address(str(cfg.get("recipient_email", ""))),
        "password_saved": saved_password or env_password,
        "password_from_environment": env_password,
        "alert_on_balance_error": bool(cfg.get("alert_on_balance_error", True)),
        "spend_limit": float(cfg.get("spend_limit", 0) or 0),
        "balance_threshold": float(cfg.get("balance_threshold", 0) or 0),
        "cooldown_minutes": int(cfg.get("cooldown_minutes", 60) or 60),
        "last_sent_at": state.get("last_sent_at", ""),
        "last_reason": state.get("last_reason", ""),
        "provider_balance_supported": False,
    }


def save_settings(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Settings must be a JSON object")
    current = _settings().copy()
    for key in (
        "enabled", "email_enabled", "review_required", "alert_on_balance_error", "smtp_host",
        "smtp_port", "smtp_security", "smtp_username", "smtp_sender",
        "recipient_email", "spend_limit", "balance_threshold", "cooldown_minutes",
    ):
        if key in payload:
            current[key] = payload[key]

    current["enabled"] = bool(current.get("enabled", False))
    current["email_enabled"] = bool(current.get("email_enabled", False))
    current["review_required"] = bool(current.get("review_required", False))
    current["alert_on_balance_error"] = bool(current.get("alert_on_balance_error", True))
    current["smtp_host"] = str(current.get("smtp_host", "")).strip()
    current["smtp_username"] = str(current.get("smtp_username", "")).strip()
    current["smtp_sender"] = str(current.get("smtp_sender", "")).strip()
    current["recipient_email"] = str(current.get("recipient_email", "")).strip()
    current["smtp_security"] = str(current.get("smtp_security", "ssl")).lower().strip()
    if current["smtp_security"] not in {"ssl", "starttls", "none"}:
        raise ValueError("SMTP security must be ssl, starttls, or none")
    try:
        current["smtp_port"] = int(current.get("smtp_port", 465))
        current["cooldown_minutes"] = max(1, min(10080, int(current.get("cooldown_minutes", 60))))
        current["spend_limit"] = max(0, float(current.get("spend_limit", 0) or 0))
        current["balance_threshold"] = max(0, float(current.get("balance_threshold", 0) or 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("SMTP port, cooldown, and thresholds must be numeric") from exc
    if not 1 <= current["smtp_port"] <= 65535:
        raise ValueError("SMTP port must be between 1 and 65535")
    if current["email_enabled"]:
        if not current["smtp_host"]:
            raise ValueError("SMTP host is required when email alerts are enabled")
        if "@" not in current["recipient_email"]:
            raise ValueError("A valid recipient email is required when email alerts are enabled")
        if not current["smtp_sender"]:
            current["smtp_sender"] = current["smtp_username"]
        if "@" not in current["smtp_sender"]:
            raise ValueError("SMTP sender or username must be a valid email address")
    password = str(payload.get("smtp_password", ""))
    if password:
        current["smtp_password_encrypted"] = _cipher_encrypt(password)
    cfg = load_config()
    cfg["quota_alert"] = current
    if not save_config(cfg):
        raise RuntimeError("Unable to save quota alert settings")
    return status()


def _smtp_password(cfg: dict) -> str:
    return os.getenv("BILI_ALERT_SMTP_PASSWORD", "").strip() or _cipher_decrypt(str(cfg.get("smtp_password_encrypted", "")))


def _send(subject: str, body: str) -> None:
    cfg = _settings()
    if not (cfg.get("enabled") and cfg.get("email_enabled")):
        raise ValueError("Email quota alerts are not enabled")
    password = _smtp_password(cfg)
    if not password:
        raise ValueError("SMTP password is not configured")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = str(cfg.get("smtp_sender") or cfg.get("smtp_username"))
    message["To"] = str(cfg.get("recipient_email"))
    message.set_content(body)
    host, port = str(cfg["smtp_host"]), int(cfg["smtp_port"])
    security = str(cfg.get("smtp_security", "ssl"))
    if security == "ssl":
        with smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context()) as client:
            client.login(str(cfg.get("smtp_username") or message["From"]), password)
            client.send_message(message)
    else:
        with smtplib.SMTP(host, port, timeout=20) as client:
            client.ehlo()
            if security == "starttls":
                client.starttls(context=ssl.create_default_context())
                client.ehlo()
            client.login(str(cfg.get("smtp_username") or message["From"]), password)
            client.send_message(message)


def _allowed(reason: str) -> bool:
    cfg = _settings()
    cooldown = max(60, int(cfg.get("cooldown_minutes", 60) or 60) * 60)
    state = _state()
    last = float((state.get("sent", {}) or {}).get(reason, 0) or 0)
    return time.time() - last >= cooldown


def _mark_sent(reason: str) -> None:
    state = _state()
    sent = state.setdefault("sent", {})
    sent[reason] = time.time()
    state["last_sent_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
    state["last_reason"] = reason
    _save_state(state)


def _queue_for_review(reason: str, subject: str, body: str) -> None:
    """Persist a redacted pending mail without contacting SMTP."""
    state = _state()
    rows = state.setdefault("pending_review", [])
    rows.append({
        "reason": reason,
        "subject": subject,
        "body": redact_sensitive_text(body)[:1000],
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    })
    state["pending_review"] = rows[-50:]
    state.setdefault("sent", {})[reason] = time.time()
    state["last_reason"] = f"pending_review:{reason}"
    _save_state(state)


def alert_billing_error(error_text: Any) -> bool:
    cfg = _settings()
    if not (cfg.get("enabled") and cfg.get("email_enabled") and cfg.get("alert_on_balance_error", True)):
        return False
    if not is_billing_error(error_text) or not _allowed("billing_error"):
        return False
    detail = redact_sensitive_text(str(error_text or "AI provider reported a quota or balance error"))[:500]
    subject = "BiliLearn AI quota/balance alert"
    body = "BiliLearn stopped AI work after a provider billing error.\n\n" + detail
    if cfg.get("review_required", False):
        _queue_for_review("billing_error", subject, body)
        return True
    _send(subject, body)
    _mark_sent("billing_error")
    return True


def alert_billing_error_async(error_text: Any) -> None:
    def worker() -> None:
        try:
            with _LOCK:
                alert_billing_error(error_text)
        except Exception:
            # Alert delivery must never crash or block the bot. Do not log SMTP details.
            pass
    threading.Thread(target=worker, name="quota-alert-email", daemon=True).start()


def maybe_alert_recorded_spend(total: float) -> bool:
    cfg = _settings()
    limit = float(cfg.get("spend_limit", 0) or 0)
    if not (cfg.get("enabled") and cfg.get("email_enabled") and limit > 0 and float(total or 0) >= limit):
        return False
    if not _allowed("recorded_spend"):
        return False
    subject = "BiliLearn recorded spend limit reached"
    body = f"Recorded local AI spend is {float(total):.4f}, reaching the configured limit of {limit:.4f}.\n\nThis is based on BiliLearn's local web_costs.json record, not a provider balance query."
    if cfg.get("review_required", False):
        _queue_for_review("recorded_spend", subject, body)
        return True
    _send(subject, body)
    _mark_sent("recorded_spend")
    return True


def maybe_alert_recorded_spend_async(total: float) -> None:
    def worker() -> None:
        try:
            with _LOCK:
                maybe_alert_recorded_spend(total)
        except Exception:
            # Dashboard reads must remain independent from mail availability.
            pass
    threading.Thread(target=worker, name="quota-spend-alert", daemon=True).start()


def send_test_email() -> None:
    _send("BiliLearn email alert test", "This is a test email from BiliLearn. SMTP email alerts are configured correctly.")
