import pytest

from confluence_mcp import queue, server
from confluence_mcp.client import ConfluenceAPIError


def page(version=3, storage="<p>old</p>"):
    return {
        "id": "42",
        "title": "Guide",
        "space": {"key": "OPS"},
        "version": {"number": version},
        "_links": {"webui": "/spaces/OPS/pages/42"},
        "body": {"storage": {"value": storage}},
    }


def test_update_page_dry_run_diffs_without_putting(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    result = server.update_page("42", expected_version=3, content="new", dry_run=True)

    assert result["dry_run"] is True
    assert result["version_before"] == 3
    assert result["version_after"] == 4
    assert "-old" in result["diff"]
    assert "+new" in result["diff"]
    assert fake_client.updated == []


def test_update_page_rejects_stale_expected_version(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(version=4)

    with pytest.raises(ConfluenceAPIError, match="current version is 4"):
        server.update_page("42", expected_version=3, content="new")


def test_update_page_rejects_markdown_on_macro_page(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(storage='<ac:structured-macro ac:name="toc"/><p>old</p>')

    with pytest.raises(ConfluenceAPIError, match="update_page_section"):
        server.update_page("42", expected_version=3, content="new")


def test_update_page_force_allows_markdown_on_macro_page(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(storage='<ac:structured-macro ac:name="toc"/><p>old</p>')

    result = server.update_page("42", expected_version=3, content="new", dry_run=True, force=True)

    assert result["dry_run"] is True


def test_update_page_accepts_storage_format(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    result = server.update_page(
        "42",
        expected_version=3,
        content="<p>raw</p>",
        content_format="storage",
        dry_run=True,
    )

    assert "+raw" in result["diff"]


def test_update_page_queues_bound_payload(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    result = server.update_page("42", expected_version=3, content="new", dry_run=False)

    assert result["queued"] is True and result["status"] == "pending"
    assert fake_client.updated == []
    [op] = queue.list_ops()
    assert op["id"] == result["operation_id"]
    assert op["kind"] == "update" and op["version_before"] == 3
    assert op["payload"]["version"]["number"] == 4
    assert op["payload"]["title"] == "Guide"
    assert "+new" in op["preview"]


def test_update_page_keeps_title_when_not_provided(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    server.update_page("42", expected_version=3, content="new", dry_run=False)

    assert queue.list_ops()[0]["payload"]["title"] == "Guide"


def test_update_page_rejects_empty_content(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="content"):
        server.update_page("42", expected_version=3, content="   ")


def test_update_page_rejects_empty_storage_content(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="content"):
        server.update_page("42", expected_version=3, content="", content_format="storage")
