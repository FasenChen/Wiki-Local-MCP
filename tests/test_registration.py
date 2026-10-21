import asyncio
import importlib

from confluence_mcp import server


def _registered_tool_names(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CONFLUENCE_ENABLE_WRITES", raising=False)
    else:
        monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", value)
    module = importlib.reload(server)
    return {tool.name for tool in asyncio.run(module.mcp.list_tools())}


def test_write_tools_are_hidden_by_default(monkeypatch):
    names = _registered_tool_names(monkeypatch, None)

    assert "create_page" not in names
    assert "add_comment" not in names
    assert {"search_pages", "get_page", "cql_search"} <= names


def test_write_tools_appear_when_enabled(monkeypatch):
    names = _registered_tool_names(monkeypatch, "true")

    assert {"create_page", "add_comment", "update_page", "update_page_section"} <= names
