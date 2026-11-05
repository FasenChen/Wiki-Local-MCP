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


def test_missing_file_returns_empty_settings(tmp_path):
    assert settings_file.load_env_file(tmp_path / "absent.env") == {}


def test_file_settings_do_not_modify_process_environment(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "ATLASSIAN_CONFLUENCE_URL=https://file.example.com/confluence\n"
        "CONFLUENCE_WRITE_SPACES=OPS\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_URL", "https://process.example.com")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "QA")
    before = dict(os.environ)
    result = settings_file.load_env_file(path)
    assert result == {
        "ATLASSIAN_CONFLUENCE_URL": "https://file.example.com/confluence",
        "CONFLUENCE_WRITE_SPACES": "OPS",
    }
    assert dict(os.environ) == before


def test_utf8_bom_does_not_corrupt_first_key(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_bytes("\ufeffATLASSIAN_CONFLUENCE_URL=https://bom.example.com\n".encode("utf-8"))
    monkeypatch.setenv("ATLASSIAN_CONFLUENCE_URL", "https://process.example.com")
    assert settings_file.load_env_file(path) == {"ATLASSIAN_CONFLUENCE_URL": "https://bom.example.com"}
    assert os.environ["ATLASSIAN_CONFLUENCE_URL"] == "https://process.example.com"


def test_strips_trailing_comment_after_whitespace():
    text = "A=hello # comment\nKEY= # only a comment\n"
    assert parse_env(text) == {"A": "hello", "KEY": ""}


def test_hash_inside_quotes_is_kept():
    text = 'B="value # not comment"\nC=\'x\' # note\n'
    assert parse_env(text) == {"B": "value # not comment", "C": "x"}


def test_hash_without_leading_space_is_part_of_value():
    assert parse_env("URL=https://wiki.example.com/x#top\n") == {
        "URL": "https://wiki.example.com/x#top"
    }


def test_pat_and_unknown_keys_are_excluded(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "ATLASSIAN_CONFLUENCE_PAT=file-token\n"
        "UNUSED_SETTING=ignored\n"
        "CONFLUENCE_WRITE_SPACES=OPS\n",
        encoding="utf-8",
    )
    for key in ("ATLASSIAN_CONFLUENCE_PAT", "UNUSED_SETTING", "CONFLUENCE_WRITE_SPACES"):
        monkeypatch.setenv(key, "")
        monkeypatch.delenv(key)
    before = dict(os.environ)
    assert settings_file.load_env_file(path) == {"CONFLUENCE_WRITE_SPACES": "OPS"}
    assert dict(os.environ) == before
