"""Send approved Confluence writes, at most once each."""

from __future__ import annotations

from typing import Any

from . import queue
from .client import ConfluenceAPIError, ConfluenceConfigurationError
from .writes import audit_write, ensure_write_allowed


def execute(client: Any, op: dict[str, Any]) -> dict[str, Any]:
    """Send one claimed (executing) operation and record how it ended."""
    status = "succeeded"
    result: dict[str, Any] | None = None
    error: str | None = None
    try:
        ensure_write_allowed(op["space_key"])
        if op["action"] == "move_page":
            payload = op["payload"]
            # movepage.action answers with the moved page, not a version, so record the page id only.
            client.move_page(op["page_id"], payload["position"], payload["target_id"])
            result = {"id": op["page_id"], "version": None, "url": None}
        elif op["kind"] == "update":
            response = client.update_page(op["page_id"], op["payload"])
            result = {
                "id": str(response["id"]),
                "version": (response.get("version") or {}).get("number"),
                "url": client.page_url(response),
            }
        else:
            response = client.create_content(op["payload"])
            result = {
                "id": str(response["id"]),
                "version": (response.get("version") or {}).get("number"),
                "url": client.page_url(response),
            }
    except ConfluenceConfigurationError as exc:
        status, error = "failed", str(exc)
    except ConfluenceAPIError as exc:
        # A status code means Confluence answered and rejected; no status means
        # the outcome is unknown, so the operation must never be retried.
        status = "failed" if exc.status_code is not None else "indeterminate"
        error = str(exc)
    except Exception as exc:
        status, error = "indeterminate", str(exc)

    if status == "succeeded":
        queue.finish(op["id"], "succeeded", result=result)
        audit_write(
            op["action"],
            page_id=op["page_id"] or result["id"],
            space_key=op["space_key"],
            version_before=op["version_before"],
            version_after=result["version"],
            result=(
                "moved" if op["action"] == "move_page"
                else "updated" if op["kind"] == "update" else "created"
            ),
        )
    else:
        queue.finish(op["id"], status, error=error)

    return {
        "operation_id": op["id"],
        "action": op["action"],
        "status": status,
        "result": result,
        "error": error,
    }


def approve_and_apply(client: Any, op_ids: list[str]) -> dict[str, Any]:
    """Approve and send operations in the given order.

    Pending operations are approved first; already-approved ones are sent as they are.
    Stops at the first indeterminate outcome and leaves the rest untouched.
    """
    executed: list[dict[str, Any]] = []
    not_pending: list[str] = []
    for index, op_id in enumerate(op_ids):
        op = queue.get_op(op_id)
        if op is not None and op["status"] == "pending":
            queue.approve([op_id])
        claimed = queue.claim_approved(op_id)
        if claimed is None:
            not_pending.append(op_id)
            continue
        outcome = execute(client, claimed)
        executed.append(outcome)
        if outcome["status"] == "indeterminate":
            return {
                "executed": executed,
                "not_pending": not_pending,
                "skipped": list(op_ids[index + 1 :]),
            }
    return {"executed": executed, "not_pending": not_pending, "skipped": []}
