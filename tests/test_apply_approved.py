import pytest

from confluence_mcp import queue, server, writes
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


def _approved_update(**overrides):
    op_id = _enqueue(**overrides)
    queue.approve([op_id])
    return op_id


def test_apply_sends_stored_payload_and_audits(fake_client, audit_log):
    _approved_update(payload={"version": {"number": 4}})
    fake_client.update_response = {"id": "42", "version": {"number": 4}}

    out = server.apply_approved_operations()

    assert fake_client.updated == [{"version": {"number": 4}}]
    assert out["executed"][0]["status"] == "succeeded"
    assert out["executed"][0]["result"]["version"] == 4
    assert "update_page" in audit_log.read_text(encoding="utf-8")


def test_apply_ignores_pending_and_reports_count(fake_client):
    _enqueue()

    assert server.apply_approved_operations() == {"executed": [], "pending_approval": 1}


def test_apply_marks_version_conflict_failed(fake_client):
    _approved_update()

    def conflict(page_id, payload):
        raise ConfluenceAPIError("conflict", status_code=409)

    fake_client.update_page = conflict

    assert server.apply_approved_operations()["executed"][0]["status"] == "failed"


def test_apply_timeout_is_indeterminate_and_stops(fake_client):
    _approved_update()
    _approved_update()

    def timeout(page_id, payload):
        raise ConfluenceAPIError("timed out")

    fake_client.update_page = timeout

    out = server.apply_approved_operations()

    assert [e["status"] for e in out["executed"]] == ["indeterminate"]
    assert [r["status"] for r in queue.list_ops()] == ["indeterminate", "approved"]
    server.apply_approved_operations()
    assert queue.list_ops()[0]["status"] == "indeterminate"


def test_apply_rechecks_space_whitelist(fake_client, monkeypatch):
    _approved_update(space_key="OPS")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "QA")

    out = server.apply_approved_operations()

    assert out["executed"][0]["status"] == "failed"
    assert fake_client.updated == []


def test_apply_create_records_new_page_id(fake_client):
    _approved_update(kind="create", page_id=None, version_before=None)
    fake_client.create_response = {"id": "77", "version": {"number": 1}}

    assert server.apply_approved_operations()["executed"][0]["result"]["id"] == "77"
