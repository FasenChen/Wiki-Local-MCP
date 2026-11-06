"""Local SQLite queue for Confluence writes awaiting human approval."""

from __future__ import annotations

import json
import secrets
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from .images import ImageAttachment

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

_IMAGE_SCHEMA = """
CREATE TABLE IF NOT EXISTS image_attachments (
    operation_id TEXT NOT NULL REFERENCES operations(id),
    filename TEXT NOT NULL,
    source TEXT NOT NULL,
    content_type TEXT NOT NULL,
    data BLOB NOT NULL,
    PRIMARY KEY (operation_id, filename)
)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA_VERSION = 2
_COLUMNS = {
    "id", "created_at", "updated_at", "action", "kind", "page_id", "space_key",
    "version_before", "summary", "preview", "payload", "status", "result", "error",
}


class QueueSchemaError(RuntimeError):
    """The queue database was written by an incompatible version."""


def _check_version(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    if version == SCHEMA_VERSION:
        return
    if version in {0, 1}:
        # Image snapshots are additive; existing operations and their payloads stay intact.
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(operations)")}
        if columns == _COLUMNS:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            return
        raise QueueSchemaError(
            f"{QUEUE_PATH.name} has an unrecognised table layout. "
            f"Check or move that file: {QUEUE_PATH}"
        )
    raise QueueSchemaError(
        f"{QUEUE_PATH.name} is schema version {version}; this build expects {SCHEMA_VERSION}. "
        f"Check or move that file: {QUEUE_PATH}"
    )


def _connect() -> sqlite3.Connection:
    QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(QUEUE_PATH, timeout=5, isolation_level=None)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(_SCHEMA)
        conn.execute(_IMAGE_SCHEMA)
        _check_version(conn)
    except Exception:
        conn.close()
        raise
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
    attachments: list[ImageAttachment] | None = None,
) -> str:
    """Insert a pending operation and return its id."""
    op_id = secrets.token_hex(4)
    now = _now()
    with closing(_connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
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
            conn.executemany(
                "INSERT INTO image_attachments (operation_id, filename, source, content_type, data) "
                "VALUES (?, ?, ?, ?, ?)",
                [(op_id, image.filename, image.source, image.content_type, image.data)
                 for image in attachments or []],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return op_id


def get_attachments(op_id: str) -> list[ImageAttachment]:
    with closing(_connect()) as conn:
        return [
            ImageAttachment(row["filename"], row["source"], row["content_type"], row["data"])
            for row in conn.execute(
                "SELECT filename, source, content_type, data FROM image_attachments "
                "WHERE operation_id = ? ORDER BY rowid", (op_id,),
            )
        ]


def attachment_summaries(op_id: str) -> list[dict[str, Any]]:
    with closing(_connect()) as conn:
        return [dict(row) for row in conn.execute(
            "SELECT filename, source, content_type, length(data) AS size_bytes FROM image_attachments "
            "WHERE operation_id = ? ORDER BY rowid", (op_id,),
        )]


def record_progress(op_id: str, result: dict[str, Any]) -> None:
    """Keep known remote changes even if execution is interrupted later."""
    with closing(_connect()) as conn:
        conn.execute(
            "UPDATE operations SET result = ?, updated_at = ? WHERE id = ? AND status = 'executing'",
            (json.dumps(result), _now(), op_id),
        )


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


def get_op(op_id: str) -> dict[str, Any] | None:
    """Return one operation by id, or None."""
    with closing(_connect()) as conn:
        row = conn.execute("SELECT * FROM operations WHERE id = ?", (op_id,)).fetchone()
    return _row(row) if row is not None else None


def _claim(select: str, params: tuple[Any, ...]) -> dict[str, Any] | None:
    row = None
    with closing(_connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(select, params).fetchone()
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


def claim_next_approved() -> dict[str, Any] | None:
    """Atomically move the oldest approved operation to executing and return it."""
    return _claim("SELECT * FROM operations WHERE status = 'approved' ORDER BY rowid LIMIT 1", ())


def claim_approved(op_id: str) -> dict[str, Any] | None:
    """Atomically move this operation to executing if it is approved, else return None."""
    return _claim("SELECT * FROM operations WHERE id = ? AND status = 'approved'", (op_id,))


def recover_stale_executing(
    *, now: datetime | None = None, max_age_seconds: int = 300
) -> list[str]:
    """Mark executing rows older than max_age_seconds indeterminate; return their ids.

    A row stuck in executing means a process died mid-write, so the outcome is unknown.
    """
    cutoff = ((now or datetime.now(timezone.utc)) - timedelta(seconds=max_age_seconds)).isoformat()
    with closing(_connect()) as conn:
        conn.execute("BEGIN IMMEDIATE")
        try:
            ids = [
                row["id"]
                for row in conn.execute(
                    "SELECT id FROM operations WHERE status = 'executing' "
                    "AND updated_at < ? ORDER BY rowid",
                    (cutoff,),
                )
            ]
            conn.executemany(
                "UPDATE operations SET status = 'indeterminate', updated_at = ?, error = ? "
                "WHERE id = ?",
                [
                    (
                        _now(),
                        "Interrupted before the result was known; check Confluence before retrying.",
                        op_id,
                    )
                    for op_id in ids
                ],
            )
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    return ids


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
