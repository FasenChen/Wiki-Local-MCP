from confluence_mcp import queue, server


def _op(**o):
    args = dict(
        kind="update",
        page_id="42",
        space_key="OPS",
        version_before=3,
        summary="Guide",
        preview="-old\n+new",
        payload={"secret": "storage"},
    )
    args.update(o)
    return queue.enqueue("update_page", **args)


def test_list_shows_active_ops_without_payload():
    a = _op()
    b = _op()
    queue.reject([b])
    out = server.list_queued_operations()
    assert [i["id"] for i in out["items"]] == [a] and out["total"] == 1
    assert "payload" not in out["items"][0]


def test_list_paginates():
    ids = [_op() for _ in range(3)]
    out = server.list_queued_operations(page=2, page_size=2)
    assert [i["id"] for i in out["items"]] == ids[2:] and out["total"] == 3


def test_get_returns_preview_in_request_order_and_reports_missing():
    a, b = _op(), _op()
    out = server.get_queued_operations([b, "deadbeef", a])
    assert [o["id"] for o in out["operations"]] == [b, a]
    assert out["operations"][0]["preview"] == "-old\n+new"
    assert "payload" not in out["operations"][0]
    assert out["missing"] == ["deadbeef"]


def test_cancel_only_touches_pending():
    p, ap, ex = _op(), _op(), _op()
    queue.approve([ap, ex])
    queue.claim_approved(ex)
    out = server.cancel_queued_operations([p, ap, ex, "deadbeef"])
    assert out["cancelled"] == [p]
    assert out["not_cancelled"] == [
        {"id": ap, "status": "approved"},
        {"id": ex, "status": "executing"},
        {"id": "deadbeef", "status": "unknown"},
    ]
    assert [r["status"] for r in queue.list_ops()] == ["rejected", "approved", "executing"]


def test_execution_log_lists_finished_newest_first():
    a, b = _op(), _op()
    queue.approve([a, b])
    queue.claim_approved(a)
    queue.claim_approved(b)
    queue.finish(a, "succeeded", result={"id": "42", "version": 4})
    queue.finish(b, "failed", error="conflict")
    out = server.get_execution_log()
    assert [i["id"] for i in out["items"]] == [b, a]
    assert out["items"][0]["error"] == "conflict"
