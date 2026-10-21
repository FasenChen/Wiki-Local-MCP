import pytest

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
