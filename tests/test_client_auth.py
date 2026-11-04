import pytest

from confluence_mcp import client
from confluence_mcp.client import ConfluenceConfigurationError, ConfluenceSettings


@pytest.fixture(autouse=True)
def _no_keyring(monkeypatch):
    monkeypatch.setattr(client.keyring, "get_password", lambda *_: None)
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_URL", "https://wiki.example.com/confluence")
    monkeypatch.delenv("ATLASSIAN_CONFLUENCE_PAT", raising=False)


def test_pat_from_environment_is_the_only_credential(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_PAT", "token-123")
    settings = ConfluenceSettings.from_environment()
    assert settings.pat == "token-123"


def test_username_and_password_alone_are_rejected(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_USERNAME", "alice")
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_PASSWORD", "secret")
    with pytest.raises(ConfluenceConfigurationError, match="PAT"):
        ConfluenceSettings.from_environment()
