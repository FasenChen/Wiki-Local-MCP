import pytest

from confluence_mcp import server


def _page(page_id, title):
    return {"id": page_id, "title": title, "space": {"key": "OPS"}, "version": {"number": 1}}


def test_get_children_returns_tree(fake_client):
    fake_client.children = {"1": [_page("2", "Child")], "2": [_page("3", "Grandchild")]}

    result = server.get_children("1", depth=2)

    assert result["children"][0]["page_id"] == "2"
    assert result["children"][0]["children"][0]["page_id"] == "3"
    assert result["truncated"] is False


def test_get_children_depth_one_has_no_children_key(fake_client):
    fake_client.children = {"1": [_page("2", "Child")]}

    result = server.get_children("1", depth=1)

    assert "children" not in result["children"][0]


@pytest.mark.parametrize("depth", [0, 4])
def test_get_children_rejects_depth_out_of_range(fake_client, depth):
    with pytest.raises(ValueError):
        server.get_children("1", depth=depth)


def test_get_children_stops_at_node_cap(fake_client, monkeypatch):
    monkeypatch.setattr(server, "MAX_CHILD_NODES", 2)
    fake_client.children = {"1": [_page("2", "A"), _page("3", "B")], "2": [_page("4", "C")]}

    result = server.get_children("1", depth=3)

    assert result["truncated"] is True


def test_get_children_flags_truncated_when_level_hits_limit(fake_client):
    fake_client.children = {"1": [_page("2", "A"), _page("3", "B")]}

    result = server.get_children("1", depth=1, limit=1)

    assert len(result["children"]) == 1
    assert result["truncated"] is True
