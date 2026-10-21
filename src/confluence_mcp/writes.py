"""Guardrails for Confluence write operations."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .client import ConfluenceConfigurationError

WRITE_FLAG = "CONFLUENCE_ENABLE_WRITES"
WRITE_SPACES = "CONFLUENCE_WRITE_SPACES"
AUDIT_PATH = Path.home() / ".confluence-mcp" / "audit.log"


def writes_enabled() -> bool:
    return os.environ.get(WRITE_FLAG, "").strip().lower() in {"1", "true", "yes"}


def ensure_write_allowed(space_key: str | None) -> None:
    if not writes_enabled():
        raise ConfluenceConfigurationError(
            f"Writes are disabled. Set {WRITE_FLAG}=true to enable write tools."
        )
    allowed = {item.strip() for item in os.environ.get(WRITE_SPACES, "").split(",") if item.strip()}
    if allowed and space_key not in allowed:
        raise ConfluenceConfigurationError(
            f'Space "{space_key}" is not in {WRITE_SPACES}. Allowed spaces: {", ".join(sorted(allowed))}.'
        )


def audit_write(
    action: str,
    *,
    page_id: str,
    space_key: str | None,
    version_before: int | None,
    version_after: int | None,
    result: str,
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "page_id": page_id,
        "space_key": space_key,
        "version_before": version_before,
        "version_after": version_after,
        "result": result,
    }
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Losing the audit line must not turn a successful write into a failure.
        print(f"confluence-mcp: could not write audit log: {exc}", file=sys.stderr)
