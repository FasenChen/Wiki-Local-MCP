import pytest

from confluence_mcp import server


def test_list_spaces_returns_key_name_and_url(fake_client):
    fake_client.spaces_response = {
        "results": [{"key": "OPS", "name": "Operations", "_links": {"webui": "/display/OPS"}}],
        "size": 1,
    }

    result = server.list_spaces(limit=10)

    assert result == {
        "spaces": [
            {
                "key": "OPS",
                "name": "Operations",
                "url": "https://wiki.example.com/display/OPS",
            }
        ],
        "count": 1,
        "next_start": None,
    }


def test_list_spaces_reports_next_start_when_page_is_full(fake_client):
    fake_client.spaces_response = {
        "results": [{"key": "OPS", "name": "Operations", "_links": {"webui": "/display/OPS"}}],
        "size": 1,
    }

    result = server.list_spaces(limit=1)

    assert result["next_start"] == 1


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 101}, {"start": -1}])
def test_list_spaces_rejects_invalid_paging(fake_client, kwargs):
    with pytest.raises(ValueError):
        server.list_spaces(**kwargs)


def test_api_error_defaults_to_no_status_code():
    from confluence_mcp.client import ConfluenceAPIError

    assert ConfluenceAPIError("boom").status_code is None
