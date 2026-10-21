import pytest

from confluence_mcp import server
from confluence_mcp.client import ConfluenceAPIError, ConfluenceClient


class FallingBackClient(ConfluenceClient):
    def __init__(self):
        self.paths = []

    def _get_json(self, path, *, params):
        self.paths.append(path)
        if path.startswith("content/"):
            raise ConfluenceAPIError("not found", status_code=404)
        return {
            "results": [
                {
                    "number": 2,
                    "when": "2026-10-01",
                    "by": {"displayName": "A"},
                    "message": "m",
                }
            ]
        }


def test_list_versions_falls_back_to_experimental_endpoint():
    client = FallingBackClient()

    versions = client.list_versions("42")

    assert client.paths == [
        "content/42/version",
        "../experimental/content/42/version",
    ]
    assert versions[0]["number"] == 2


class OnlyExperimentalForbiddenClient(ConfluenceClient):
    def __init__(self):
        pass

    def _get_json(self, path, *, params):
        raise ConfluenceAPIError("forbidden", status_code=403)


def test_list_versions_does_not_swallow_permission_errors():
    with pytest.raises(ConfluenceAPIError, match="forbidden"):
        OnlyExperimentalForbiddenClient().list_versions("42")


def _page(version, storage):
    return {
        "id": "42",
        "title": "Guide",
        "space": {"key": "OPS"},
        "version": {"number": version},
        "body": {"storage": {"value": storage}},
    }


def test_get_page_history_lists_recent_versions(fake_client):
    fake_client.versions["42"] = [
        {"number": 2, "when": "2026-10-02", "by": {"displayName": "Bob"}, "message": "fix"},
        {"number": 1, "when": "2026-10-01", "by": {"displayName": "Alice"}, "message": ""},
    ]

    result = server.get_page_history("42", limit=1)

    assert result["versions"] == [
        {"number": 2, "when": "2026-10-02", "by": "Bob", "message": "fix"}
    ]
    assert "diff" not in result


def test_get_page_history_diffs_two_versions(fake_client):
    fake_client.historical_pages[("42", 1)] = _page(1, "<p>old</p>")
    fake_client.historical_pages[("42", 2)] = _page(2, "<p>new</p>")

    result = server.get_page_history("42", from_version=1, to_version=2)

    assert result["diff"].startswith("--- v1")
    assert "-old" in result["diff"]
    assert "+new" in result["diff"]
    assert result["truncated"] is False


def test_get_page_history_truncates_long_diff(fake_client):
    fake_client.historical_pages[("42", 1)] = _page(1, "<p>old</p>")
    fake_client.historical_pages[("42", 2)] = _page(2, "<p>new</p>")

    result = server.get_page_history("42", from_version=1, to_version=2, max_chars=10)

    assert len(result["diff"]) == 10
    assert result["truncated"] is True


def test_get_page_history_requires_both_versions(fake_client):
    with pytest.raises(ValueError, match="both"):
        server.get_page_history("42", from_version=1)


@pytest.mark.parametrize(
    "kwargs",
    [{"from_version": 0, "to_version": 1}, {"from_version": 1, "to_version": 1}],
)
def test_get_page_history_rejects_invalid_versions(fake_client, kwargs):
    with pytest.raises(ValueError):
        server.get_page_history("42", **kwargs)
