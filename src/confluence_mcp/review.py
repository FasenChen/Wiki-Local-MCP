"""Terminal review for Confluence writes queued by the MCP server."""

from __future__ import annotations

import argparse
import sys
from typing import Any

from . import queue


def _format(op: dict[str, Any]) -> str:
    header = (
        f"{op['id']}  {op['status']}  {op['action']}  "
        f"{op['space_key']}/{op['page_id']}  v{op['version_before']}  {op['summary']}"
    )
    preview = "\n".join(f"    {line}" for line in op["preview"].splitlines())
    return f"{header}\n{preview}" if preview else header


def _show(ops: list[dict[str, Any]]) -> None:
    for op in ops:
        print(_format(op))


def _list(show_all: bool) -> int:
    statuses = None if show_all else ("pending", "approved")
    _show(queue.list_ops(statuses))
    return 0


def _approve(ids: list[str]) -> int:
    if not sys.stdin.isatty():
        print("approve needs an interactive terminal", file=sys.stderr)
        return 2

    pending = queue.list_ops(("pending",))
    targets = [op for op in pending if not ids or op["id"] in ids]
    _show(targets)
    print(f"Approve {len(targets)} operation(s)? Type yes: ", end="", flush=True)
    if sys.stdin.readline().strip() != "yes":
        print("nothing approved")
        return 1

    approved = queue.approve([op["id"] for op in targets])
    for op_id in approved:
        print(f"approved: {op_id}")
    for op_id in ids:
        if op_id not in approved:
            print(f"not pending: {op_id}")
    return 0


def _reject(ids: list[str]) -> int:
    for op_id in queue.reject(ids):
        print(f"rejected: {op_id}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="confluence-mcp-review",
        description="Review Confluence writes queued by the MCP server.",
    )
    subparsers = parser.add_subparsers(dest="command")
    list_parser = subparsers.add_parser("list", help="show pending and approved operations")
    list_parser.add_argument("--all", action="store_true", help="include finished operations")
    approve_parser = subparsers.add_parser("approve", help="approve pending operations")
    approve_parser.add_argument("ids", nargs="*")
    reject_parser = subparsers.add_parser("reject", help="reject pending operations")
    reject_parser.add_argument("ids", nargs="+")

    args = parser.parse_args(argv)
    if args.command == "approve":
        return _approve(args.ids)
    if args.command == "reject":
        return _reject(args.ids)
    return _list(getattr(args, "all", False))
