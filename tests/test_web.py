import http.client
import json
import threading
from types import SimpleNamespace

import pytest

from confluence_mcp import queue, web, web_page, writes

TOKEN = "tok"


@pytest.fixture(autouse=True)
def _writes(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")


@pytest.fixture
def server(fake_client):
    srv = web.make_server(fake_client, TOKEN)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def call(server):
    port = server.server_address[1]

    def _call(method, path, body=None, cookie=True, host=None, origin="auto"):
        headers = {"Host": host or f"127.0.0.1:{port}"}
        if cookie is True:
            headers["Cookie"] = f"cmr_session={TOKEN}"
        elif cookie:
            headers["Cookie"] = f"cmr_session={cookie}"
        if origin == "auto":
            origin = f"http://127.0.0.1:{port}" if method == "POST" else None
        if origin:
            headers["Origin"] = origin
        data = None
        if body is not None:
            data = body if isinstance(body, bytes) else json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        try:
            conn.request(method, path, body=data, headers=headers)
            resp = conn.getresponse()
            payload = resp.read()
            return SimpleNamespace(
                status=resp.status, headers=dict(resp.getheaders()), body=payload
            )
        finally:
            conn.close()

    return _call


def _pending(**overrides):
    args = dict(
        kind="update",
        page_id="42",
        space_key="OPS",
        version_before=3,
        summary="Guide",
        preview="-old\n+new",
        payload={"version": {"number": 4}, "body": "secret storage"},
    )
    args.update(overrides)
    return queue.enqueue("update_page", **args)


def test_token_landing_sets_cookie_and_redirects(call, capsys):
    r = call("GET", f"/?token={TOKEN}", cookie=False)
    assert r.status == 302 and r.headers["Location"] == "/"
    cookie = r.headers["Set-Cookie"]
    assert f"cmr_session={TOKEN}" in cookie
    assert "HttpOnly" in cookie and "SameSite=Strict" in cookie
    assert TOKEN not in capsys.readouterr().err  # request lines carry the token


def test_wrong_token_is_403(call):
    r = call("GET", "/?token=nope", cookie=False)
    assert r.status == 403 and "Set-Cookie" not in r.headers


def test_requests_without_cookie_are_403_and_do_not_touch_queue(call, fake_client):
    op = _pending()
    assert call("POST", "/api/approve", {"ids": [op]}, cookie=False).status == 403
    assert call("POST", "/api/approve", {"ids": [op]}, cookie="wrong").status == 403
    assert call("GET", "/api/state", cookie=False).status == 403
    assert queue.list_ops()[0]["status"] == "pending" and fake_client.updated == []


def test_foreign_host_is_403(call):
    assert call("GET", "/api/state", host="evil.example:80").status == 403


def test_post_with_wrong_or_missing_origin_is_403(call, fake_client):
    op = _pending()
    assert call("POST", "/api/approve", {"ids": [op]}, origin=None).status == 403
    assert call("POST", "/api/approve", {"ids": [op]}, origin="http://evil.example").status == 403
    assert queue.list_ops()[0]["status"] == "pending" and fake_client.updated == []


def test_page_is_served_with_security_headers(call):
    r = call("GET", "/")
    assert r.status == 200 and r.body.decode("utf-8") == web_page.PAGE
    assert "default-src 'none'" in r.headers["Content-Security-Policy"]
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Cache-Control"] == "no-store"


def test_unknown_path_is_404(call):
    assert call("GET", "/nope").status == 404


def test_state_lists_pending_without_payload(call):
    op = _pending()
    r = call("GET", "/api/state")
    [item] = json.loads(r.body)["operations"]
    assert item["id"] == op and item["status"] == "pending"
    assert item["preview"] == "-old\n+new"
    assert "payload" not in item and b"secret storage" not in r.body


def test_state_keeps_only_the_20_most_recent_finished(call):
    ids = [_pending() for _ in range(22)]
    queue.reject(ids)
    active = _pending()
    items = json.loads(call("GET", "/api/state").body)["operations"]
    assert active in [i["id"] for i in items]
    assert len([i for i in items if i["status"] == "rejected"]) == 20


def test_approve_writes_once_even_when_posted_twice(call, fake_client):
    op = _pending()
    fake_client.update_response = {"id": "42", "version": {"number": 4}}
    first = call("POST", "/api/approve", {"ids": [op]})
    second = call("POST", "/api/approve", {"ids": [op]})
    assert first.status == 200
    assert json.loads(first.body)["executed"][0]["status"] == "succeeded"
    assert len(fake_client.updated) == 1
    assert json.loads(second.body)["not_pending"] == [op]


def test_reject_marks_pending_rejected(call):
    op = _pending()
    r = call("POST", "/api/reject", {"ids": [op]})
    assert json.loads(r.body) == {"rejected": [op]}
    assert queue.list_ops()[0]["status"] == "rejected"


@pytest.mark.parametrize(
    "body",
    [{"ids": []}, {"ids": [1]}, {"ids": "abc"}, {"ids": ["x"] * 201}, {"nope": 1}, b"not json"],
)
def test_bad_body_is_400_and_changes_nothing(call, fake_client, body):
    _pending()
    assert call("POST", "/api/approve", body).status == 400
    assert call("POST", "/api/reject", body).status == 400
    assert queue.list_ops()[0]["status"] == "pending" and fake_client.updated == []


def test_page_never_uses_innerhtml():
    assert "innerHTML" not in web_page.PAGE and "outerHTML" not in web_page.PAGE
    assert "textContent" in web_page.PAGE
