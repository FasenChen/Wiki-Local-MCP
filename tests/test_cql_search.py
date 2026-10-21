import pytest

from confluence_mcp import server


def test_cql_search_returns_page_summaries(fake_client):
    fake_client.search_response = {
        "results": [
            {
                "content": {"id": 42, "space": {"key": "OPS"}},
                "title": "Release 1.0",
                "excerpt": "highlights",
                "lastModified": "2026-10-01T10:00:00.000Z",
                "url": "/spaces/OPS/pages/42/Release+1.0",
            }
        ],
        "totalSize": 3,
    }

    result = server.cql_search('label = "release"', limit=25, start=0)

    assert fake_client.search_calls == [('label = "release"', 25, 0)]
    assert result == {
        "results": [
            {
                "page_id": "42",
                "title": "Release 1.0",
                "space_key": "OPS",
                "excerpt": "highlights",
                "last_modified": "2026-10-01T10:00:00.000Z",
                "url": "https://wiki.example.com/spaces/OPS/pages/42/Release+1.0",
            }
        ],
        "count": 1,
        "next_start": 1,
    }


def test_cql_search_has_no_next_start_when_results_are_exhausted(fake_client):
    fake_client.search_response = {"results": [], "totalSize": 0}

    result = server.cql_search("type = page", limit=25, start=0)

    assert result["next_start"] is None


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 51}, {"start": -1}])
def test_cql_search_rejects_invalid_paging(fake_client, kwargs):
    with pytest.raises(ValueError):
        server.cql_search("type = page", **kwargs)


def test_cql_search_rejects_blank_cql(fake_client):
    with pytest.raises(ValueError):
        server.cql_search("   ")
