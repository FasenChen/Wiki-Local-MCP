import pytest

from confluence_mcp import settings_file
from confluence_mcp.client import ConfluenceConfigurationError, ConfluenceSettings


@pytest.fixture(autouse=True)
def _config_defaults(monkeypatch, config_values):
    monkeypatch.setitem(config_values, "ATLASSIAN_CONFLUENCE_URL", "https://wiki.example.com/confluence")
    monkeypatch.delenv("ATLASSIAN_CONFLUENCE_PAT", raising=False)


@pytest.mark.parametrize("env_pat", [None, "", "inherited-token"])
def test_file_settings_are_used_over_process_values(monkeypatch, env_pat, config_values):
    if env_pat is not None:
        monkeypatch.setenv("ATLASSIAN_CONFLUENCE_PAT", env_pat)
    monkeypatch.setitem(config_values, "ATLASSIAN_CONFLUENCE_URL", "https://wiki.example.com/confluence/")
    monkeypatch.setitem(config_values, "ATLASSIAN_CONFLUENCE_CA_BUNDLE", "C:/certs/wiki-ca.pem")
    monkeypatch.setitem(config_values, "ATLASSIAN_CONFLUENCE_PAT", "file-token")
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_URL", "https://process.example.com")
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_CA_BUNDLE", "C:/certs/process-ca.pem")
    settings = ConfluenceSettings.from_environment()
    assert settings.pat == "file-token"
    assert settings.base_url == "https://wiki.example.com/confluence"
    assert settings.ca_bundle == "C:/certs/wiki-ca.pem"


@pytest.mark.parametrize("env_pat", [None, "inherited-token"])
@pytest.mark.parametrize("file_pat", [None, ""])
def test_missing_file_pat_is_rejected(monkeypatch, env_pat, file_pat, config_values):
    if env_pat is not None:
        monkeypatch.setenv("ATLASSIAN_CONFLUENCE_PAT", env_pat)
    if file_pat is not None:
        config_values["ATLASSIAN_CONFLUENCE_PAT"] = file_pat
    with pytest.raises(ConfluenceConfigurationError, match="ATLASSIAN_CONFLUENCE_PAT") as caught:
        ConfluenceSettings.from_environment()
    assert ".env" in str(caught.value)
    assert "inherited-token" not in str(caught.value)


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


def test_pat_comes_from_project_file_and_is_not_exposed(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "ATLASSIAN_CONFLUENCE_URL=https://wiki.example.invalid/confluence\n"
        "ATLASSIAN_CONFLUENCE_PAT=file#token==\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_PAT", "process-token")
    monkeypatch.setattr(settings_file, "get_settings", lambda: settings_file.load_env_file(path))
    settings = ConfluenceSettings.from_environment()
    assert settings.pat == "file#token=="
    assert "file#token==" not in repr(settings)


def test_missing_file_pat_reports_file_without_secrets(config_values, monkeypatch):
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_PAT", "process-token")
    with pytest.raises(ConfluenceConfigurationError) as caught:
        ConfluenceSettings.from_environment()
    assert ".env" in str(caught.value)
    assert "process-token" not in str(caught.value)
