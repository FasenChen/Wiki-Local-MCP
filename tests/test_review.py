import io
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone

import pytest

from confluence_mcp import queue, review, writes


class TTYInput(io.StringIO):
    def isatty(self):
        return True


@pytest.fixture(autouse=True)
def _console(monkeypatch):
    monkeypatch.setattr(review, "_console_attached", lambda: True)


@pytest.fixture(autouse=True)
def _writes(monkeypatch, tmp_path, fake_client):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")
    # fake_client only patches server.get_client; review imports its own.
    monkeypatch.setattr(review, "get_client", lambda: fake_client, raising=False)


def _pending():
    return queue.enqueue(
        "update_page",
        kind="update",
        page_id="42",
        space_key="OPS",
        version_before=3,
        summary="Guide",
        preview="-old\n+new",
        payload={"version": {"number": 4}},
    )


def test_approve_refuses_without_tty(monkeypatch, capsys):
    op = _pending()
    monkeypatch.setattr("sys.stdin", io.StringIO("yes\n"))
    assert review.main(["approve", op]) == 2
    assert queue.list_ops()[0]["status"] == "pending"


def test_approve_refuses_when_isatty_is_not_a_console(monkeypatch, capsys):
    op = _pending()
    monkeypatch.setattr("sys.stdin", TTYInput("yes\n"))
    monkeypatch.setattr("sys.platform", "win32")
    monkeypatch.setattr(review, "_console_attached", lambda: False, raising=False)

    assert review.main(["approve", op]) == 2
    assert queue.list_ops()[0]["status"] == "pending"
    assert "interactive terminal" in capsys.readouterr().err


def test_approve_requires_exact_yes(monkeypatch):
    op = _pending()
    monkeypatch.setattr("sys.stdin", TTYInput("y\n"))
    assert review.main(["approve", op]) == 1
    assert queue.list_ops()[0]["status"] == "pending"


def test_approve_without_ids_approves_and_writes_all_pending(monkeypatch, capsys, fake_client):
    a, b = _pending(), _pending()
    fake_client.update_response = {"id": "42", "version": {"number": 4}}
    monkeypatch.setattr("sys.stdin", TTYInput("yes\n"))
    assert review.main(["approve"]) == 0
    assert {r["status"] for r in queue.list_ops()} == {"succeeded"}
    assert len(fake_client.updated) == 2
    assert "-old" in capsys.readouterr().out  # reviewer saw the preview


def test_approve_refuses_when_writes_disabled(monkeypatch, capsys, fake_client):
    op = _pending()
    monkeypatch.delenv("CONFLUENCE_ENABLE_WRITES")
    monkeypatch.setattr("sys.stdin", TTYInput("yes\n"))
    assert review.main(["approve", op]) == 2
    assert queue.list_ops()[0]["status"] == "pending"
    assert "CONFLUENCE_ENABLE_WRITES" in capsys.readouterr().err


def test_approve_reports_non_pending_ids(monkeypatch, capsys):
    op = _pending()
    queue.reject([op])
    monkeypatch.setattr("sys.stdin", TTYInput("yes\n"))
    review.main(["approve", op])
    assert f"not pending: {op}" in capsys.readouterr().out


def test_reject_works_without_tty(monkeypatch):
    op = _pending()
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert review.main(["reject", op]) == 0
    assert queue.list_ops()[0]["status"] == "rejected"


def test_list_hides_finished_unless_all(capsys):
    op = _pending()
    queue.reject([op])
    review.main(["list"])
    assert op not in capsys.readouterr().out
    review.main(["list", "--all"])
    assert op in capsys.readouterr().out


def test_approve_marks_stale_executing_indeterminate_first(monkeypatch, capsys, fake_client):
    stuck = _pending()
    queue.approve([stuck])
    queue.claim_approved(stuck)
    old = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    with closing(sqlite3.connect(queue.QUEUE_PATH)) as conn:
        conn.execute("UPDATE operations SET updated_at = ? WHERE id = ?", (old, stuck))
        conn.commit()
    monkeypatch.setattr("sys.stdin", TTYInput("yes\n"))
    review.main(["approve"])
    assert queue.get_op(stuck)["status"] == "indeterminate"
    assert stuck in capsys.readouterr().out


def test_web_refuses_without_tty(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert review.main(["web"]) == 2
    assert "interactive terminal" in capsys.readouterr().err


def test_web_refuses_when_writes_disabled(monkeypatch, capsys):
    monkeypatch.delenv("CONFLUENCE_ENABLE_WRITES", raising=False)
    monkeypatch.setattr("sys.stdin", TTYInput(""))
    assert review.main(["web"]) == 2
    assert "CONFLUENCE_ENABLE_WRITES" in capsys.readouterr().err


def test_web_sweeps_stale_ops_then_serves(monkeypatch, fake_client):
    served = []
    monkeypatch.setattr("sys.stdin", TTYInput(""))
    monkeypatch.setattr(review.web, "serve", served.append)
    monkeypatch.setattr(review.queue, "recover_stale_executing", lambda: served.append("swept"))
    assert review.main(["web"]) == 0
    assert served == ["swept", fake_client]
