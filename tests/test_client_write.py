import pytest
import httpx

from confluence_mcp.client import ConfluenceAPIError, ConfluenceClient
from confluence_mcp.client import ConfluenceSettings


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


def test_attachment_lookup_and_multipart_upload_use_existing_auth_and_context_path(image_file):
    requests = []

    def handle(request):
        requests.append(request)
        assert request.headers["authorization"] == "Bearer example-token"
        assert request.url.path == "/confluence/rest/api/content/42/child/attachment"
        if request.method == "GET":
            assert request.url.params["filename"] == "image.png"
            return httpx.Response(200, json={"results": [{"id": "91", "title": "image.png"}]})
        assert request.method == "POST" and request.headers["x-atlassian-token"] == "no-check"
        assert request.headers["content-type"].startswith("multipart/form-data; boundary=")
        assert b'name="file"; filename="image.png"' in request.content
        assert b"Content-Type: image/png" in request.content
        assert image_file.read_bytes() in request.content
        return httpx.Response(200, json={"results": [{"id": "92", "title": "image.png"}]})

    client = ConfluenceClient(ConfluenceSettings("https://wiki.example/confluence", "example-token", None))
    client._client.close()
    client._client = httpx.Client(
        base_url="https://wiki.example/confluence/rest/api/", headers={"Authorization": "Bearer example-token"},
        transport=httpx.MockTransport(handle),
    )
    try:
        assert client.get_attachment("42", "image.png")["id"] == "91"
        assert client.upload_attachment("42", "image.png", image_file.read_bytes(), "image/png")["id"] == "92"
    finally:
        client.close()
    assert len(requests) == 2


@pytest.mark.parametrize("status,body", [(403, {}), (200, {"results": []}), (200, {"results": [{"id": "1", "title": "wrong.png"}]})])
def test_unconfirmed_attachment_upload_is_not_success(status, body):
    client = ConfluenceClient.__new__(ConfluenceClient)
    client._client = httpx.Client(
        base_url="https://wiki.example/rest/api/",
        transport=httpx.MockTransport(lambda request: httpx.Response(status, json=body)),
    )
    try:
        with pytest.raises(ConfluenceAPIError) as excinfo:
            client.upload_attachment("42", "image.png", b"image", "image/png")
        assert excinfo.value.status_code == (403 if status == 403 else None)
    finally:
        client.close()
