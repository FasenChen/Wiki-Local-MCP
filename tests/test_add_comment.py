import pytest

from confluence_mcp import queue, server

PAGE = {
    "id": "42",
    "title": "Guide",
    "space": {"key": "OPS"},
    "version": {"number": 3},
    "_links": {"webui": "/spaces/OPS/pages/42"},
    "body": {"storage": {"value": "<p>x</p>"}},
}


def test_add_comment_dry_run_previews_without_posting(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)
    fake_client.pages["42"] = PAGE

    result = server.add_comment("42", "looks good", dry_run=True)

    assert result["dry_run"] is True
    assert result["target"] == {"page_id": "42", "parent_comment_id": None}
    assert result["storage_preview"] == "<p>looks good</p>"
    assert fake_client.created == []


def test_add_comment_queues_comment_payload(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = PAGE

    result = server.add_comment("42", "reply", parent_comment_id="99", dry_run=False)

    assert result["queued"] is True and result["status"] == "pending"
    assert fake_client.created == []
    [op] = queue.list_ops()
    assert op["id"] == result["operation_id"]
    assert op["kind"] == "create" and op["page_id"] == "42"
    assert op["summary"] == "comment on page 42"
    assert op["preview"] == "reply"
    payload = op["payload"]
    assert payload["type"] == "comment"
    assert payload["container"] == {"id": "42", "type": "page"}
    assert payload["ancestors"] == [{"id": "99"}]


def test_add_comment_respects_whitelist(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "QA")
    fake_client.pages["42"] = PAGE

    from confluence_mcp.client import ConfluenceConfigurationError

    with pytest.raises(ConfluenceConfigurationError):
        server.add_comment("42", "x")


def test_add_comment_rejects_bad_parent_id(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = PAGE

    with pytest.raises(ValueError):
        server.add_comment("42", "x", parent_comment_id="abc")
