from unittest.mock import Mock

import pytest

from confluence_mcp import client
from confluence_mcp.client import ConfluenceConfigurationError, ConfluenceSettings


@pytest.fixture(autouse=True)
def _no_keyring(monkeypatch, config_values):
    monkeypatch.setattr(client.keyring, "get_password", lambda *_: None)
    monkeypatch.setitem(config_values, "ATLASSIAN_CONFLUENCE_URL", "https://wiki.example.com/confluence")
    monkeypatch.delenv("ATLASSIAN_CONFLUENCE_PAT", raising=False)


@pytest.mark.parametrize("env_pat", [None, "", "inherited-token"])
def test_pat_comes_from_credential_store(monkeypatch, env_pat, config_values):
    if env_pat is not None:
        monkeypatch.setenv("ATLASSIAN_CONFLUENCE_PAT", env_pat)
    monkeypatch.setitem(config_values, "ATLASSIAN_CONFLUENCE_URL", "https://wiki.example.com/confluence/")
    monkeypatch.setitem(config_values, "ATLASSIAN_CONFLUENCE_CA_BUNDLE", "C:/certs/wiki-ca.pem")
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_URL", "https://process.example.com")
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_CA_BUNDLE", "C:/certs/process-ca.pem")
    lookup = Mock(return_value="stored-token")
    monkeypatch.setattr(client.keyring, "get_password", lookup)
    settings = ConfluenceSettings.from_environment()
    lookup.assert_called_once_with("confluence-mcp", "pat")
    assert settings.pat == "stored-token"
    assert settings.base_url == "https://wiki.example.com/confluence"
    assert settings.ca_bundle == "C:/certs/wiki-ca.pem"


@pytest.mark.parametrize("env_pat", [None, "inherited-token"])
@pytest.mark.parametrize("stored_pat", [None, ""])
def test_missing_credential_store_pat_is_rejected(monkeypatch, env_pat, stored_pat):
    if env_pat is not None:
        monkeypatch.setenv("ATLASSIAN_CONFLUENCE_PAT", env_pat)
    monkeypatch.setattr(client.keyring, "get_password", Mock(return_value=stored_pat))
    with pytest.raises(ConfluenceConfigurationError, match="No Confluence PAT found") as caught:
        ConfluenceSettings.from_environment()
    assert "confluence-mcp-store-pat" in str(caught.value)
    assert "ATLASSIAN_CONFLUENCE_PAT" not in str(caught.value)


def test_credential_store_failure_is_reported(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_PAT", "inherited-token")
    failure = RuntimeError("credential store unavailable")
    monkeypatch.setattr(client.keyring, "get_password", Mock(side_effect=failure))
    with pytest.raises(ConfluenceConfigurationError, match="Could not read") as caught:
        ConfluenceSettings.from_environment()
    assert caught.value.__cause__ is failure
    assert "confluence-mcp-store-pat" in str(caught.value)
    assert "ATLASSIAN_CONFLUENCE_PAT" not in str(caught.value)


def test_username_and_password_alone_are_rejected(monkeypatch):
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_USERNAME", "alice")
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_PASSWORD", "secret")
    with pytest.raises(ConfluenceConfigurationError, match="PAT"):
        ConfluenceSettings.from_environment()


def test_process_url_cannot_replace_missing_file_value(config_values, monkeypatch):
    config_values.pop("ATLASSIAN_CONFLUENCE_URL", None)
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_URL", "https://process.example.com")
    with pytest.raises(ConfluenceConfigurationError, match="ATLASSIAN_CONFLUENCE_URL"):
        ConfluenceSettings.from_environment()
