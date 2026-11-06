import httpx
import pytest

from confluence_mcp.client import ConfluenceAPIError, ConfluenceSettings


@pytest.fixture
def transport_client(monkeypatch):
    original = httpx.Client
    clients = []

    def install(handler):
        def make_client(**kwargs):
            client = original(transport=httpx.MockTransport(handler), **kwargs)
            clients.append(client)
            return client

        monkeypatch.setattr(httpx, "Client", make_client)
        return clients

    return install


@pytest.fixture
def settings():
    return ConfluenceSettings("https://wiki.example.invalid/confluence", "sample-secret", None)


@pytest.mark.parametrize("identity", [{"username": "alice"}, {"userKey": "user-123"}])
def test_authenticated_user_is_checked_by_one_read_only_request(settings, transport_client, identity):
    from confluence_mcp.healthcheck import verify_wiki_connection

    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, json=identity)

    clients = transport_client(respond)
    verify_wiki_connection(settings)
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/confluence/rest/api/user/current"
    assert requests[0].headers["Authorization"] == "Bearer sample-secret"
    assert clients[0].is_closed


@pytest.mark.parametrize("identity", [
    {"type": "anonymous"},
    {"type": "anonymous", "username": "alice"},
    {},
    {"username": ""},
])
def test_anonymous_or_unidentifiable_response_is_not_reported_as_authenticated(
    settings, transport_client, identity
):
    from confluence_mcp.healthcheck import verify_wiki_connection

    clients = transport_client(lambda request: httpx.Response(200, json=identity))
    with pytest.raises(ConfluenceAPIError, match="confirm"):
        verify_wiki_connection(settings)
    assert clients[0].is_closed


@pytest.mark.parametrize("status", [401, 403])
def test_http_auth_errors_do_not_expose_response_or_token(settings, transport_client, status):
    from confluence_mcp.healthcheck import verify_wiki_connection

    clients = transport_client(lambda request: httpx.Response(status, text="sample-secret private-response"))
    with pytest.raises(ConfluenceAPIError) as caught:
        verify_wiki_connection(settings)
    assert caught.value.status_code == status
    assert "sample-secret" not in str(caught.value)
    assert "private-response" not in str(caught.value)
    assert clients[0].is_closed


def test_timeout_is_reported_and_client_is_closed(settings, transport_client):
    from confluence_mcp.healthcheck import verify_wiki_connection

    def timeout(request):
        raise httpx.ReadTimeout("sample-secret", request=request)

    clients = transport_client(timeout)
    with pytest.raises(ConfluenceAPIError, match="timed out") as caught:
        verify_wiki_connection(settings)
    assert "sample-secret" not in str(caught.value)
    assert clients[0].is_closed


def test_connection_reset_is_reported_without_exposing_error(config_values, transport_client, capsys):
    from confluence_mcp.healthcheck import main

    config_values.update({
        "ATLASSIAN_CONFLUENCE_URL": "https://wiki.example.invalid/confluence",
        "ATLASSIAN_CONFLUENCE_PAT": "sample-secret",
    })

    def reset(request):
        raise httpx.ReadError("sample-secret private-network-details", request=request)

    clients = transport_client(reset)
    assert main() == 1
    captured = capsys.readouterr()
    assert "Confluence" in captured.err
    assert "sample-secret" not in captured.out + captured.err
    assert "private-network-details" not in captured.out + captured.err
    assert clients[0].is_closed


def test_non_json_is_rejected_without_printing_response(settings, transport_client):
    from confluence_mcp.healthcheck import verify_wiki_connection

    clients = transport_client(lambda request: httpx.Response(200, text="private-response sample-secret"))
    with pytest.raises(ConfluenceAPIError, match="non-JSON") as caught:
        verify_wiki_connection(settings)
    assert "private-response" not in str(caught.value)
    assert "sample-secret" not in str(caught.value)
    assert clients[0].is_closed


def test_healthcheck_cli_returns_failure_without_sensitive_output(config_values, transport_client, capsys):
    from confluence_mcp.healthcheck import main

    config_values.update({
        "ATLASSIAN_CONFLUENCE_URL": "https://wiki.example.invalid/confluence",
        "ATLASSIAN_CONFLUENCE_PAT": "sample-secret",
    })
    clients = transport_client(lambda request: httpx.Response(401, text="private-response sample-secret"))
    assert main() == 1
    captured = capsys.readouterr()
    assert "sample-secret" not in captured.out + captured.err
    assert "private-response" not in captured.out + captured.err
    assert clients[0].is_closed
