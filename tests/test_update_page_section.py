import pytest

from confluence_mcp import server, writes
from confluence_mcp.client import ConfluenceAPIError


def page(version=5, storage="<h2>Setup</h2><p>old</p><h2>Notes</h2><p>keep</p>"):
    return {
        "id": "42",
        "title": "Guide",
        "space": {"key": "OPS"},
        "version": {"number": version},
        "_links": {"webui": "/spaces/OPS/pages/42"},
        "body": {"storage": {"value": storage}},
    }


def test_update_page_section_dry_run_diffs_only_the_section(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    result = server.update_page_section(
        "42", "Setup", "new body", expected_version=5, dry_run=True
    )

    assert result["dry_run"] is True
    assert "-old" in result["diff"]
    assert "+new body" in result["diff"]
    assert "Notes" not in result["diff"]
    assert fake_client.updated == []


def test_update_page_section_rejects_stale_expected_version(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(version=6)

    with pytest.raises(ConfluenceAPIError, match="current version is 6"):
        server.update_page_section("42", "Setup", "new", expected_version=5)


def test_update_page_section_rejects_same_level_heading(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="level 2"):
        server.update_page_section("42", "Setup", "## Other", expected_version=5)


def test_update_page_section_rejects_unknown_section(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="Available sections: Setup, Notes"):
        server.update_page_section("42", "Missing", "new", expected_version=5)


def test_update_page_section_preserves_other_sections_and_macros(
    fake_client, monkeypatch, tmp_path
):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")
    fake_client.pages["42"] = page(
        storage=(
            '<ac:structured-macro ac:name="toc"/>'
            '<h2>Setup</h2><p>old</p>'
            '<h2>Notes</h2><p>keep</p>'
        )
    )
    fake_client.update_response = page(version=6)

    server.update_page_section("42", "Setup", "new body", expected_version=5, dry_run=False)

    payload = fake_client.updated[0]
    assert payload["version"] == {"number": 6, "message": "[MCP]"}
    assert payload["body"]["storage"]["value"] == (
        '<ac:structured-macro ac:name="toc"/>'
        '<h2>Setup</h2><p>new body</p>'
        '<h2>Notes</h2><p>keep</p>'
    )
    assert "update_page_section" in (tmp_path / "audit.log").read_text(encoding="utf-8")


def test_update_page_section_can_clear_the_body(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(storage="<h2>Setup</h2><p>old</p>")
    fake_client.update_response = page(version=6)

    server.update_page_section("42", "Setup", "", expected_version=5, dry_run=False)

    assert fake_client.updated[0]["body"]["storage"]["value"] == "<h2>Setup</h2>"
