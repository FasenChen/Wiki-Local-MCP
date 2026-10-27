import pytest

from confluence_mcp import queue, server
from confluence_mcp.client import ConfluenceAPIError, ConfluenceConfigurationError


def test_create_page_dry_run_previews_without_posting(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)

    result = server.create_page("OPS", "Release", "## Notes\n\nhello", dry_run=True)

    assert result["dry_run"] is True
    assert result["target"] == {"space_key": "OPS", "title": "Release", "parent_page_id": None}
    assert "<h2>Notes</h2>" in result["storage_preview"]
    assert fake_client.created == []


def test_create_page_rejects_existing_title(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.search_response = {
        "results": [
            {
                "id": "7",
                "title": "Release",
                "space": {"key": "OPS"},
                "_links": {"webui": "/spaces/OPS/pages/7"},
            }
        ]
    }

    with pytest.raises(ConfluenceAPIError, match="already exists") as excinfo:
        server.create_page("OPS", "Release", "x", dry_run=True)

    assert "https://wiki.example.com/pages/7" in str(excinfo.value)


def test_create_page_rejects_parent_in_another_space(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["5"] = {"id": "5", "title": "Parent", "space": {"key": "QA"}}

    with pytest.raises(ValueError, match="different space"):
        server.create_page("OPS", "Release", "x", parent_page_id="5")


def test_create_page_respects_whitelist(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "QA")

    with pytest.raises(ConfluenceConfigurationError):
        server.create_page("OPS", "Release", "x")


def test_create_page_queues_payload(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")

    result = server.create_page("OPS", "Release", "hello", dry_run=False)

    assert result["queued"] is True and result["status"] == "pending"
    assert fake_client.created == []
    [op] = queue.list_ops()
    assert op["id"] == result["operation_id"]
    assert op["kind"] == "create" and op["page_id"] is None and op["version_before"] is None
    payload = op["payload"]
    assert payload["type"] == "page"
    assert payload["title"] == "Release"
    assert payload["space"] == {"key": "OPS"}
    assert payload["body"]["storage"]["representation"] == "storage"
