import pytest
from services.token_observability import TokenStore


@pytest.fixture(autouse=True)
def isolate_default_token_telemetry(tmp_path, monkeypatch):
    initialize = TokenStore.__init__
    def isolated(self, directory=None):
        initialize(self, tmp_path / 'token-telemetry' if directory is None else directory)
    monkeypatch.setattr(TokenStore, '__init__', isolated)
