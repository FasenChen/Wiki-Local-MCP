from confluence_mcp import queue


def _enqueue(**overrides):
    args = dict(
        kind="update",
        page_id="42",
        space_key="OPS",
        version_before=3,
        summary="Guide",
        preview="-old\n+new",
        payload={"version": {"number": 4}},
    )
    args.update(overrides)
    return queue.enqueue("update_page", **args)


def test_enqueue_stores_pending_row_with_payload():
    op_id = _enqueue()
    [row] = queue.list_ops()
    assert row["id"] == op_id and len(op_id) == 8
    assert row["status"] == "pending"
    assert row["payload"] == {"version": {"number": 4}}
    assert row["result"] is None


def test_approve_and_reject_only_touch_pending():
    a, b = _enqueue(), _enqueue()
    assert queue.reject([b]) == [b]
    assert queue.approve([a, b, "deadbeef"]) == [a]
    assert [r["status"] for r in queue.list_ops()] == ["approved", "rejected"]


def test_claim_next_approved_is_single_use():
    a, b = _enqueue(), _enqueue()
    queue.approve([a, b])
    assert queue.claim_next_approved()["id"] == a
    assert queue.claim_next_approved()["id"] == b
    assert queue.claim_next_approved() is None
    assert {r["status"] for r in queue.list_ops()} == {"executing"}


def test_finish_records_result_and_list_filters_by_status():
    a = _enqueue()
    queue.approve([a])
    queue.claim_next_approved()
    queue.finish(a, "succeeded", result={"id": "42", "version": 4})
    assert queue.list_ops(("pending",)) == []
    assert queue.list_ops(("succeeded",))[0]["result"] == {"id": "42", "version": 4}
