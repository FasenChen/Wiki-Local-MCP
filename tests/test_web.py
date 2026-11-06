import http.client
import json
import threading
from types import SimpleNamespace

import pytest

from confluence_mcp import queue, web, web_page, writes

TOKEN = "tok"


@pytest.fixture(autouse=True)
def _writes(monkeypatch, tmp_path, config_values):
    monkeypatch.setitem(config_values, "CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.delitem(config_values, "CONFLUENCE_WRITE_SPACES", raising=False)
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


def test_page_never_writes_untrusted_html_into_its_dom():
    # The approval page may not parse HTML from operation data; the body is only ever a
    # sandboxed frame whose src is the server's rendered preview.
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "srcdoc"):
        assert banned not in web_page.PAGE
    assert "textContent" in web_page.PAGE
    assert 'setAttribute("sandbox", "")' in web_page.PAGE
    assert 'frame.src = "/api/render?id="' in web_page.PAGE


def test_split_divider_is_keyboard_operable():
    assert 'role="separator"' in web_page.PAGE and 'tabindex="0"' in web_page.PAGE
    assert 'addEventListener("keydown"' in web_page.PAGE


STATE = "/api/state"


def _with_body(storage, **overrides):
    payload = {
        "title": "Guide",
        "version": {"number": 4},
        "body": {"storage": {"representation": "storage", "value": storage}},
    }
    return _pending(payload=payload, **overrides)


def _page(page_id, title, ancestors=None):
    page = {"id": page_id, "title": title, "space": {"key": "OPS"}}
    if ancestors is not None:
        page["ancestors"] = ancestors
    return page


def _titles(location):
    return [item["title"] for item in location["trail"]]


def test_state_title_comes_from_payload_and_body_stays_hidden(call):
    op = _with_body("<h1>Guide</h1><p>secret body</p>", summary="Install")
    r = call("GET", STATE)
    [item] = json.loads(r.body)["operations"]
    assert item["id"] == op and item["title"] == "Guide" and item["summary"] == "Install"
    assert b"secret body" not in r.body


def test_source_and_preview_use_proposed_body_not_the_diff(call):
    op = _with_body("<h2>New</h2><p>x</p>")  # the stored preview is "-old\n+new"
    body = json.loads(call("GET", f"/api/body?id={op}").body)
    assert body == {"storage": "<h2>New</h2><p>x</p>"}
    rendered = call("GET", f"/api/render?id={op}").body
    assert b"<h2>New</h2>" in rendered and b"-old" not in rendered


def test_render_is_sandboxed_and_framed_only_by_this_origin(call):
    op = _with_body("<p>x</p>")
    r = call("GET", f"/api/render?id={op}")
    assert r.status == 200 and r.headers["Content-Type"].startswith("text/html")
    directives = r.headers["Content-Security-Policy"].split("; ")
    assert "sandbox" in directives and "default-src 'none'" in directives
    assert "frame-ancestors 'self'" in directives
    assert r.headers["X-Frame-Options"] == "SAMEORIGIN"


def test_hostile_body_is_neutralised_in_the_rendered_document(call):
    op = _with_body(
        '<p onclick="x()">hi</p><script>alert(1)</script><img src="x" onerror="alert(1)">'
        '<ac:structured-macro ac:name="jira"/>'
    )
    body = call("GET", f"/api/render?id={op}").body.decode("utf-8")
    assert "<script" not in body and "onclick" not in body and "onerror" not in body
    assert "宏未渲染：jira" in body


def test_preview_body_and_location_need_the_session_cookie(call):
    op = _with_body("<p>x</p>")
    for path in (f"/api/render?id={op}", f"/api/body?id={op}", f"/api/location?id={op}"):
        assert call("GET", path, cookie=False).status == 403


def test_unknown_operation_is_404_on_each_per_operation_route(call):
    for path in ("/api/render?id=nope", "/api/body?id=nope", "/api/location?id=nope"):
        assert call("GET", path).status == 404


def test_queued_images_render_from_snapshot_and_state_lists_only_metadata(call, image_file):
    import base64

    from confluence_mcp.images import ImageAttachment

    data = image_file.read_bytes()
    image = ImageAttachment("queued.png", str(image_file), "image/png", data)
    op_id = _pending(
        payload={"body": {"storage": {"value": (
            '<p><ac:image ac:alt="流程图"><ri:attachment ri:filename="queued.png"/></ac:image></p>'
        )}}},
        attachments=[image],
    )
    image_file.unlink()
    state = json.loads(call("GET", "/api/state").body)
    assert state["operations"][0]["attachments"] == [image.summary()]
    assert "data" not in state["operations"][0]["attachments"][0]
    rendered = call("GET", f"/api/render?id={op_id}")
    body = rendered.body.decode("utf-8")
    assert "data:image/png;base64," + base64.b64encode(data).decode("ascii") in body
    assert 'alt="流程图"' in body and "onerror" not in body
    assert "img-src http: https: data:" in rendered.headers["Content-Security-Policy"]
    assert call("GET", f"/api/render?id={op_id}", cookie=False).status == 403


def test_update_location_is_the_original_page_path(call, fake_client):
    fake_client.pages["42"] = _page("42", "Guide", [_page("1", "Root"), _page("7", "Ops")])
    op = _pending()
    loc = json.loads(call("GET", f"/api/location?id={op}").body)
    assert loc["mode"] == "update" and loc["partial"] is False
    assert _titles(loc) == ["Root", "Ops", "Guide"]
    assert loc["trail"][-1]["url"] == "https://wiki.example.com/pages/42"


def test_update_location_marks_a_missing_ancestor_list_as_partial(call, fake_client):
    fake_client.pages["42"] = _page("42", "Guide")
    loc = json.loads(call("GET", f"/api/location?id={_pending()}").body)
    assert loc["partial"] is True and _titles(loc) == ["Guide"]


def test_create_location_shows_full_parent_path_and_new_title(call, fake_client):
    fake_client.pages["7"] = _page("7", "Ops", [_page("1", "Root")])
    op = queue.enqueue(
        "create_page", kind="create", page_id=None, space_key="OPS", version_before=None,
        summary="Runbook", preview="# Runbook",
        payload={"type": "page", "title": "Runbook", "ancestors": [{"id": "7"}]},
    )
    loc = json.loads(call("GET", f"/api/location?id={op}").body)
    assert loc["mode"] == "create" and loc["title"] == "Runbook"
    assert _titles(loc) == ["Root", "Ops"]


def test_root_create_location_makes_no_confluence_read(call):
    op = queue.enqueue(
        "create_page", kind="create", page_id=None, space_key="OPS", version_before=None,
        summary="Top", preview="# Top", payload={"title": "Top"},
    )
    loc = json.loads(call("GET", f"/api/location?id={op}").body)
    assert loc == {"mode": "create", "space_key": "OPS", "title": "Top", "trail": [], "partial": False}


def test_comment_location_names_its_container_page(call, fake_client):
    fake_client.pages["42"] = _page("42", "Guide", [_page("1", "Root")])
    op = queue.enqueue(
        "add_comment", kind="create", page_id="42", space_key="OPS", version_before=None,
        summary="comment on page 42", preview="LGTM",
        payload={"type": "comment", "container": {"id": "42", "type": "page"}},
    )
    loc = json.loads(call("GET", f"/api/location?id={op}").body)
    assert loc["mode"] == "comment" and _titles(loc) == ["Root", "Guide"]


def test_move_location_is_the_moved_page_path(call, fake_client):
    fake_client.pages["42"] = _page("42", "Guide", [_page("1", "Root")])
    op = queue.enqueue(
        "move_page", kind="update", page_id="42", space_key="OPS", version_before=3,
        summary="Guide → Other before", preview="order",
        payload={"title": "Guide", "position": "before", "target_id": "43"},
    )
    loc = json.loads(call("GET", f"/api/location?id={op}").body)
    assert loc["mode"] == "move" and _titles(loc) == ["Root", "Guide"]


def test_state_exposes_only_derived_provenance_fields(call):
    storage = (
        "> 原文归档：Android TV Ninja\n"
        "> 来源：[Overview](https://docs.netflixpartners.com/ninja/documentation/overview)\n\n"
        "secret body"
    )
    from confluence_mcp.markdown_storage import markdown_to_storage

    provenance_op = _with_body(markdown_to_storage(storage))
    plain = _with_body("<p>no provenance here</p>")
    r = call("GET", STATE)
    items = {item["id"]: item for item in json.loads(r.body)["operations"]}
    first = items[provenance_op]
    assert first["collection"] == "Android TV Ninja"
    assert first["source"]["url"] == "https://docs.netflixpartners.com/ninja/documentation/overview"
    assert first["source"]["label"] == "Overview"
    assert "secret body" not in r.body.decode("utf-8")
    assert "storage" not in json.dumps(first)
    assert items[plain]["collection"] is None and items[plain]["source"] is None


def test_location_confluence_error_is_502_and_leaves_the_queue_alone(call):
    op = _pending(page_id="99")  # not in FakeClient, so the read fails
    r = call("GET", f"/api/location?id={op}")
    assert r.status == 502 and "error" in json.loads(r.body)
    assert queue.get_op(op)["status"] == "pending"


def test_malformed_source_url_does_not_break_queue_state(call):
    op = _with_body(
        '<blockquote><p>原文归档：Android TV Ninja\n'
        '来源：<a href="http://[">Overview</a></p></blockquote>'
    )
    response = call("GET", STATE)
    assert response.status == 200
    [item] = json.loads(response.body)["operations"]
    assert item["collection"] == "Android TV Ninja" and item["source"] is None
    assert queue.get_op(op)["status"] == "pending"
