import os
from unittest.mock import MagicMock, patch

from utils.web_launcher import (
    DEFAULT_WEB_PORT,
    WEB_SERVICE_ID,
    find_available_port,
    get_web_port,
    is_our_panel,
)


def test_get_web_port_uses_one_validated_default():
    with patch.dict(os.environ, {"WEB_PORT": "not-a-port"}):
        assert get_web_port() == DEFAULT_WEB_PORT
    with patch.dict(os.environ, {"WEB_PORT": "18090"}):
        assert get_web_port() == 18090
    with patch.dict(os.environ, {"WEB_PORT": "80"}):
        assert get_web_port() == DEFAULT_WEB_PORT


def test_panel_probe_requires_service_identity():
    response = MagicMock()
    response.__enter__.return_value = response
    response.read.return_value = (
        f'{{"ok": true, "service": "{WEB_SERVICE_ID}"}}'.encode("utf-8")
    )
    with patch("urllib.request.urlopen", return_value=response):
        assert is_our_panel(DEFAULT_WEB_PORT)

    response.read.return_value = b'{"ok": true, "service": "another-service"}'
    with patch("urllib.request.urlopen", return_value=response):
        assert not is_our_panel(DEFAULT_WEB_PORT)


def test_find_available_port_skips_occupied_ports():
    with patch("utils.web_launcher.is_port_open", side_effect=[True, True, False]):
        assert find_available_port(DEFAULT_WEB_PORT) == DEFAULT_WEB_PORT + 2
