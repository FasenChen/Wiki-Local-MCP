import io

from confluence_mcp import queue, review


class TTYInput(io.StringIO):
    def isatty(self):
        return True


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


def test_approve_requires_exact_yes(monkeypatch):
    op = _pending()
    monkeypatch.setattr("sys.stdin", TTYInput("y\n"))
    assert review.main(["approve", op]) == 1
    assert queue.list_ops()[0]["status"] == "pending"


def test_approve_without_ids_approves_all_pending(monkeypatch, capsys):
    a, b = _pending(), _pending()
    monkeypatch.setattr("sys.stdin", TTYInput("yes\n"))
    assert review.main(["approve"]) == 0
    assert {r["status"] for r in queue.list_ops()} == {"approved"}
    assert "-old" in capsys.readouterr().out  # reviewer saw the preview


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
