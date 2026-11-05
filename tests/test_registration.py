import asyncio
import importlib

from confluence_mcp import server


def _registered_tool_names(monkeypatch, config_values, value):
    if value is None:
        monkeypatch.delitem(config_values, "CONFLUENCE_ENABLE_WRITES", raising=False)
    else:
        monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", value)
    module = importlib.reload(server)
    return {tool.name for tool in asyncio.run(module.mcp.list_tools())}


def test_write_tools_are_hidden_by_default(monkeypatch, config_values):
    names = _registered_tool_names(monkeypatch, config_values, None)

    assert "create_page" not in names
    assert "add_comment" not in names
    assert "list_queued_operations" not in names
    assert {"search_pages", "get_page", "cql_search"} <= names


def test_write_tools_appear_when_enabled(monkeypatch, config_values):
    names = _registered_tool_names(monkeypatch, config_values, "true")

    assert {
        "create_page",
        "add_comment",
        "update_page",
        "update_page_section",
        "move_page",
        "list_queued_operations",
        "get_queued_operations",
        "cancel_queued_operations",
        "get_execution_log",
    } <= names
    assert "apply_approved_operations" not in names
