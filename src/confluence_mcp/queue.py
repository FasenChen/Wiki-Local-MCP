"""Local SQLite queue for Confluence writes awaiting human approval."""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

QUEUE_PATH = Path.home() / ".confluence-mcp" / "queue.sqlite3"

Status = Literal[
    "pending",
    "approved",
    "rejected",
    "executing",
    "succeeded",
    "failed",
    "indeterminate",
]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    action TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('create', 'update')),
    page_id TEXT,
    space_key TEXT,
    version_before INTEGER,
    summary TEXT NOT NULL,
    preview TEXT NOT NULL,
    payload TEXT NOT NULL,
    status TEXT NOT NULL,
    result TEXT,
    error TEXT
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(QUEUE_PATH, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    return conn


def _row(row: sqlite3.Row) -> dict[str, Any]:
    op = dict(row)
    op["payload"] = json.loads(op["payload"])
    op["result"] = json.loads(op["result"]) if op["result"] is not None else None
    return op


def enqueue(
    action: str,
    *,
    kind: Literal["create", "update"],
    page_id: str | None,
    space_key: str | None,
    version_before: int | None,
    summary: str,
    preview: str,
    payload: dict[str, Any],
) -> str:
    """Insert a pending operation and return its id."""
    op_id = secrets.token_hex(4)
    now = _now()
    with closing(_connect()) as conn:
        conn.execute(
            "INSERT INTO operations (id, created_at, updated_at, action, kind, page_id, "
            "space_key, version_before, summary, preview, payload, status) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')",
            (
                op_id,
                now,
                now,
                action,
                kind,
                page_id,
                space_key,
                version_before,
                summary,
                preview,
                json.dumps(payload),
            ),
        )
    return op_id


def list_ops(statuses: tuple[str, ...] | None = None) -> list[dict[str, Any]]:
    """Return operations in insertion order; None means every status."""
    if statuses is not None and not statuses:
        return []
    query = "SELECT * FROM operations"
    params: tuple[str, ...] = ()
    if statuses is not None:
        query += f" WHERE status IN ({', '.join('?' for _ in statuses)})"
        params = statuses
    query += " ORDER BY rowid"
    with closing(_connect()) as conn:
        return [_row(row) for row in conn.execute(query, params)]


def _transition(op_ids: list[str], status: str) -> list[str]:
    changed = []
    now = _now()
    with closing(_connect()) as conn:
        for op_id in op_ids:
            cursor = conn.execute(
                "UPDATE operations SET status = ?, updated_at = ? "
                "WHERE id = ? AND status = 'pending'",
                (status, now, op_id),
            )
            if cursor.rowcount:
                changed.append(op_id)
    return changed


def approve(op_ids: list[str]) -> list[str]:
    """Approve pending operations and return the ids that changed."""
    return _transition(op_ids, "approved")


def reject(op_ids: list[str]) -> list[str]:
    """Reject pending operations and return the ids that changed."""
    return _transition(op_ids, "rejected")


def claim_next_approved() -> dict[str, Any] | None:
    """Atomically move the oldest approved operation to executing and return it."""
    row = None
    with closing(_connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM operations WHERE status = 'approved' ORDER BY rowid LIMIT 1"
            ).fetchone()
            if row is not None:
                conn.execute(
                    "UPDATE operations SET status = 'executing', updated_at = ? "
                    "WHERE id = ? AND status = 'approved'",
                    (_now(), row["id"]),
                )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return {**_row(row), "status": "executing"} if row is not None else None


def finish(
    op_id: str,
    status: Literal["succeeded", "failed", "indeterminate"],
    *,
    result: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """Record the terminal state of a claimed operation."""
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE operations SET status = ?, updated_at = ?, result = ?, error = ? WHERE id = ?",
            (status, _now(), json.dumps(result) if result is not None else None, error, op_id),
        )
