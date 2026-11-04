import os

import pytest

from confluence_mcp import settings_file
from confluence_mcp.settings_file import parse_env


def test_parses_keys_comments_and_blank_lines():
    text = "# comment\n\nATLASSIAN_CONFLUENCE_URL=https://wiki.example.com\n"
    assert parse_env(text) == {"ATLASSIAN_CONFLUENCE_URL": "https://wiki.example.com"}


def test_strips_matching_quotes_and_export_prefix():
    text = 'export A="one two"\nB=\'x=y\'\n'
    assert parse_env(text) == {"A": "one two", "B": "x=y"}


def test_malformed_line_reports_line_number_without_value():
    with pytest.raises(ValueError, match="line 2") as info:
        parse_env("A=1\nsecret-without-equals\n")
    assert "secret-without-equals" not in str(info.value)


def test_missing_file_is_a_no_op(tmp_path):
    assert settings_file.load_env_file(tmp_path / "absent.env") == []


def test_loads_keys_but_never_overrides_process_env(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("ATLASSIAN_CONFLUENCE_URL=https://wiki.example.com\nCONFLUENCE_WRITE_SPACES=OPS\n", encoding="utf-8")
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_URL", "https://other.example.com")
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)
    loaded = settings_file.load_env_file(path)
    assert os.environ["ATLASSIAN_CONFLUENCE_URL"] == "https://other.example.com"
    assert os.environ["CONFLUENCE_WRITE_SPACES"] == "OPS"
    assert loaded == ["CONFLUENCE_WRITE_SPACES"]
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)


def test_utf8_bom_does_not_corrupt_first_key(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_bytes("\ufeffATLASSIAN_CONFLUENCE_URL=https://bom.example.com\n".encode("utf-8"))
    monkeypatch.delenv("ATLASSIAN_CONFLUENCE_URL", raising=False)
    assert settings_file.load_env_file(path) == ["ATLASSIAN_CONFLUENCE_URL"]
    assert os.environ["ATLASSIAN_CONFLUENCE_URL"] == "https://bom.example.com"
    monkeypatch.delenv("ATLASSIAN_CONFLUENCE_URL", raising=False)


def test_test_session_never_reads_repo_env_file():
    from pathlib import Path

    assert not Path(os.environ[settings_file.ENV_FILE_VAR]).exists()
