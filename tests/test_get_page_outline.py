from confluence_mcp import server


def test_get_page_outline_returns_headings(fake_client):
    fake_client.pages["42"] = {
        "id": "42",
        "title": "Guide",
        "space": {"key": "OPS"},
        "version": {"number": 3},
        "_links": {"webui": "/spaces/OPS/pages/42"},
        "body": {"storage": {"value": "<h1>Guide</h1><p>x</p><h2>Setup</h2>"}},
    }

    result = server.get_page_outline("42")

    assert result["headings"] == [
        {"level": 1, "title": "Guide", "anchor": "guide"},
        {"level": 2, "title": "Setup", "anchor": "setup"},
    ]
    assert result["page_id"] == "42"
    assert result["version"] == 3
    assert result["url"] == "https://wiki.example.com/pages/42"
