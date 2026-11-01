import pytest

from confluence_mcp import apply, queue, writes
from confluence_mcp.client import ConfluenceAPIError


@pytest.fixture(autouse=True)
def audit_log(monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)
    log = tmp_path / "audit.log"
    monkeypatch.setattr(writes, "AUDIT_PATH", log)
    return log


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


def test_approve_and_apply_sends_stored_payload_and_audits(fake_client, audit_log):
    op = _enqueue(payload={"version": {"number": 4}})
    fake_client.update_response = {"id": "42", "version": {"number": 4}}
    out = apply.approve_and_apply(fake_client, [op])
    assert fake_client.updated == [{"version": {"number": 4}}]
    assert out["executed"][0]["status"] == "succeeded"
    assert out["executed"][0]["result"]["version"] == 4
    assert "update_page" in audit_log.read_text(encoding="utf-8")


def test_second_approval_of_same_op_sends_nothing(fake_client):
    op = _enqueue()
    fake_client.update_response = {"id": "42", "version": {"number": 4}}
    apply.approve_and_apply(fake_client, [op])
    out = apply.approve_and_apply(fake_client, [op])
    assert out["executed"] == [] and out["not_pending"] == [op]
    assert len(fake_client.updated) == 1


def test_leftover_approved_op_is_applied(fake_client):
    op = _enqueue()
    queue.approve([op])
    fake_client.update_response = {"id": "42", "version": {"number": 4}}
    assert apply.approve_and_apply(fake_client, [op])["executed"][0]["status"] == "succeeded"


def test_version_conflict_is_failed_and_batch_continues(fake_client):
    a, b = _enqueue(), _enqueue()
    calls = []

    def update(page_id, payload):
        calls.append(page_id)
        if len(calls) == 1:
            raise ConfluenceAPIError("conflict", status_code=409)
        return {"id": "42", "version": {"number": 4}}

    fake_client.update_page = update
    out = apply.approve_and_apply(fake_client, [a, b])
    assert [e["status"] for e in out["executed"]] == ["failed", "succeeded"]


def test_timeout_is_indeterminate_and_rest_stay_pending(fake_client):
    a, b, c = _enqueue(), _enqueue(), _enqueue()

    def timeout(page_id, payload):
        raise ConfluenceAPIError("timed out")

    fake_client.update_page = timeout
    out = apply.approve_and_apply(fake_client, [a, b, c])
    assert [e["status"] for e in out["executed"]] == ["indeterminate"]
    assert out["skipped"] == [b, c]
    assert [r["status"] for r in queue.list_ops()] == ["indeterminate", "pending", "pending"]


def test_whitelist_is_rechecked(fake_client, monkeypatch):
    op = _enqueue(space_key="OPS")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "QA")
    assert apply.approve_and_apply(fake_client, [op])["executed"][0]["status"] == "failed"
    assert fake_client.updated == []


def test_create_records_new_page_id(fake_client):
    op = _enqueue(kind="create", page_id=None, version_before=None)
    fake_client.create_response = {"id": "77", "version": {"number": 1}}
    assert apply.approve_and_apply(fake_client, [op])["executed"][0]["result"]["id"] == "77"
