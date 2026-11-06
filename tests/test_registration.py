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


def test_markdown_page_tools_expose_image_directory_and_queue_through_mcp(fake_client, image_file, config_values):
    from mcp.server.fastmcp import FastMCP
    from confluence_mcp import queue

    config_values["CONFLUENCE_ENABLE_WRITES"] = "true"
    mcp = FastMCP("test-images")
    server.register_write_tools(mcp)
    tools = {tool.name: tool for tool in asyncio.run(mcp.list_tools())}
    for name in ("create_page", "update_page", "update_page_section"):
        assert "image_base_dir" in tools[name].inputSchema["properties"]
        assert "image_base_dir" not in tools[name].inputSchema["required"]
    asyncio.run(mcp.call_tool("create_page", {
        "space_key": "OPS", "title": "Images", "content_markdown": f"![图]({image_file.name})",
        "image_base_dir": str(image_file.parent), "dry_run": False,
    }))
    [op] = queue.list_ops()
    assert op["status"] == "pending" and len(queue.get_attachments(op["id"])) == 1
    assert fake_client.uploaded == fake_client.created == []
