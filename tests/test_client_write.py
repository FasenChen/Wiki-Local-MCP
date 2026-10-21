import pytest

from confluence_mcp.client import ConfluenceAPIError, ConfluenceClient


class ConflictResponse:
    status_code = 409
    is_redirect = False
    is_error = True


class ConflictHttp:
    def request(self, *args, **kwargs):
        return ConflictResponse()


def test_update_conflict_maps_409_to_readable_error():
    client = ConfluenceClient.__new__(ConfluenceClient)
    client._client = ConflictHttp()

    with pytest.raises(ConfluenceAPIError, match="version changed") as excinfo:
        client.update_page("42", {"id": "42"})

    assert excinfo.value.status_code == 409
