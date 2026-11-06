import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

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


def test_claim_approved_claims_only_that_approved_op():
    a, b = _enqueue(), _enqueue()
    queue.approve([a, b])
    assert queue.claim_approved(b)["id"] == b
    assert queue.claim_approved(b) is None
    assert [r["status"] for r in queue.list_ops()] == ["approved", "executing"]


def test_claim_approved_ignores_pending():
    a = _enqueue()
    assert queue.claim_approved(a) is None
    assert queue.list_ops()[0]["status"] == "pending"


def test_get_op_returns_row_or_none():
    a = _enqueue()
    assert queue.get_op(a)["id"] == a
    assert queue.get_op("deadbeef") is None


def test_recover_flips_only_stale_executing_to_indeterminate():
    a, b = _enqueue(), _enqueue()
    queue.approve([a, b])
    queue.claim_approved(a)
    now = datetime.now(timezone.utc)
    assert queue.recover_stale_executing(now=now) == []
    assert queue.list_ops()[0]["status"] == "executing"
    assert queue.recover_stale_executing(now=now + timedelta(minutes=6)) == [a]
    rows = queue.list_ops()
    assert [r["status"] for r in rows] == ["indeterminate", "approved"]
    assert "Interrupted" in rows[0]["error"]


def _raw_db(user_version, schema=None):
    queue.QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(queue.QUEUE_PATH)) as conn:
        conn.execute(schema or queue._SCHEMA)
        conn.execute(f"PRAGMA user_version = {user_version}")


def test_new_database_is_stamped_with_schema_version():
    _enqueue()
    with closing(sqlite3.connect(queue.QUEUE_PATH)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == queue.SCHEMA_VERSION


def test_unversioned_database_with_matching_columns_is_stamped():
    _raw_db(0)
    assert queue.list_ops() == []
    with closing(sqlite3.connect(queue.QUEUE_PATH)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == queue.SCHEMA_VERSION


def test_unknown_schema_version_is_refused():
    _raw_db(99)
    with pytest.raises(queue.QueueSchemaError, match="queue.sqlite3"):
        queue.list_ops()


def test_unversioned_database_with_other_columns_is_refused():
    _raw_db(0, "CREATE TABLE operations (id TEXT)")
    with pytest.raises(queue.QueueSchemaError):
        queue.list_ops()


def test_version_one_migration_preserves_operations_and_accepts_image_snapshots(image_file):
    old = _enqueue()
    with closing(sqlite3.connect(queue.QUEUE_PATH)) as conn:
        conn.execute("DROP TABLE image_attachments")
        conn.execute("PRAGMA user_version = 1")
    from confluence_mcp.images import ImageAttachment

    image = ImageAttachment("image.png", str(image_file), "image/png", image_file.read_bytes())
    new = _enqueue(attachments=[image])
    assert [op["id"] for op in queue.list_ops()] == [old, new]
    assert queue.get_attachments(old) == []
    assert queue.get_attachments(new) == [image]
    assert queue.attachment_summaries(new) == [image.summary()]
    queue.reject([new])
    assert queue.get_attachments(new) == [image]


def test_interrupted_execution_keeps_remote_progress():
    op_id = _enqueue()
    queue.approve([op_id])
    queue.claim_approved(op_id)
    result = {"id": "77", "uploaded_attachments": ["image.png"]}
    queue.record_progress(op_id, result)
    queue.recover_stale_executing(now=datetime.now(timezone.utc) + timedelta(minutes=6))
    assert queue.get_op(op_id)["status"] == "indeterminate"
    assert queue.get_op(op_id)["result"] == result


def test_image_snapshot_and_operation_are_inserted_atomically(image_file):
    from confluence_mcp.images import ImageAttachment

    image = ImageAttachment("image.png", str(image_file), "image/png", image_file.read_bytes())
    with pytest.raises(sqlite3.IntegrityError):
        _enqueue(attachments=[image, image])
    assert queue.list_ops() == []
