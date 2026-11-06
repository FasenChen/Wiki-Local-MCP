import pytest

from confluence_mcp import queue, server
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


def test_update_page_section_dry_run_diffs_only_the_section(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    result = server.update_page_section(
        "42", "Setup", "new body", expected_version=5, dry_run=True
    )

    assert result["dry_run"] is True
    assert "-old" in result["diff"]
    assert "+new body" in result["diff"]
    assert "Notes" not in result["diff"]
    assert fake_client.updated == []


def test_update_page_section_rejects_stale_expected_version(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(version=6)

    with pytest.raises(ConfluenceAPIError, match="current version is 6"):
        server.update_page_section("42", "Setup", "new", expected_version=5)


def test_update_page_section_rejects_same_level_heading(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="level 2"):
        server.update_page_section("42", "Setup", "## Other", expected_version=5)


def test_update_page_section_rejects_unknown_section(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="Available sections: Setup, Notes"):
        server.update_page_section("42", "Missing", "new", expected_version=5)


def test_update_page_section_queues_full_storage(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(
        storage=(
            '<ac:structured-macro ac:name="toc"/>'
            '<h2>Setup</h2><p>old</p>'
            '<h2>Notes</h2><p>keep</p>'
        )
    )

    result = server.update_page_section(
        "42", "Setup", "new body", expected_version=5, dry_run=False
    )

    assert result["queued"] is True and result["status"] == "pending"
    assert fake_client.updated == []
    [op] = queue.list_ops()
    assert op["id"] == result["operation_id"]
    assert op["kind"] == "update" and op["version_before"] == 5
    assert op["summary"] == "Setup"
    assert op["payload"]["version"]["number"] == 6
    assert op["payload"]["body"]["storage"]["value"] == (
        '<ac:structured-macro ac:name="toc"/>'
        '<h2>Setup</h2><p>new body</p>'
        '<h2>Notes</h2><p>keep</p>'
    )


def test_update_page_section_can_clear_the_body(fake_client, monkeypatch, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(storage="<h2>Setup</h2><p>old</p>")

    server.update_page_section("42", "Setup", "", expected_version=5, dry_run=False)

    assert queue.list_ops()[0]["payload"]["body"]["storage"]["value"] == "<h2>Setup</h2>"
