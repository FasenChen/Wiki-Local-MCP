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
        attachments = queue.get_attachments(op["id"])
        if op["action"] == "move_page":
            payload = op["payload"]
            # movepage.action answers with the moved page, not a version, so record the page id only.
            client.move_page(op["page_id"], payload["position"], payload["target_id"])
            result = {"id": op["page_id"], "version": None, "url": None}
        elif attachments:
            payload = op["payload"]
            if op["kind"] == "create":
                # A page id is required before its attachments can be uploaded.
                response = client.create_content({
                    **payload,
                    "body": {"storage": {"representation": "storage", "value": "<p>Image upload in progress.</p>"}},
                })
            else:
                response = client.get_page(op["page_id"])
                if ((response.get("version") or {}).get("number") != op["version_before"]
                        or (response.get("space") or {}).get("key") != op["space_key"]):
                    raise ConfluenceAPIError(
                        "The page version or space changed before image upload. Re-read the page and queue again.",
                        status_code=409,
                    )
            result = {
                "id": str(response["id"]),
                "version": (response.get("version") or {}).get("number"),
                "url": client.page_url(response),
                "page_created": op["kind"] == "create",
                "uploaded_attachments": [],
                "reused_attachments": [],
            }
            queue.record_progress(op["id"], result)
            if op["kind"] == "create":
                if not isinstance(result["version"], int):
                    raise ConfluenceAPIError("The new page version is unknown; check the created page before continuing.")
                payload = {**payload, "id": result["id"], "version": {"number": result["version"] + 1}}
            for image in attachments:
                if client.get_attachment(result["id"], image.filename) is not None:
                    result["reused_attachments"].append(image.filename)
                else:
                    result["uploading_attachment"] = image.filename
                    queue.record_progress(op["id"], result)
                    client.upload_attachment(result["id"], image.filename, image.data, image.content_type)
                    result["uploaded_attachments"].append(image.filename)
                    del result["uploading_attachment"]
                queue.record_progress(op["id"], result)
            response = client.update_page(result["id"], payload)
            result.update(
                version=(response.get("version") or {}).get("number"),
                url=client.page_url(response),
            )
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
        queue.finish(op["id"], status, result=result, error=error)
        if result and (result.get("page_created") or result.get("uploaded_attachments")):
            audit_write(
                op["action"], page_id=result["id"], space_key=op["space_key"],
                version_before=op["version_before"], version_after=result["version"],
                result="partial",
            )

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
