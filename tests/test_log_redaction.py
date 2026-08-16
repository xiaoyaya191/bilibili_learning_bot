from utils.display import redact_sensitive_text

def test_log_redacts_cookie_and_key():
    value = 'SESSDATA=secret bili_jct:csrf Authorization: Bearer token api_key="sk-secret"'
    masked = redact_sensitive_text(value)
    for secret in ("secret", "csrf", "token", "sk-secret"):
        assert secret not in masked
    assert masked.count("***") >= 4
