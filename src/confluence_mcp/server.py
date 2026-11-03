"""MCP server exposing read-only Confluence page tools."""

from __future__ import annotations

import difflib
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from . import queue, web
from .client import (
    ConfluenceAPIError,
    ConfluenceConfigurationError,
    get_client,
    quote_cql,
)
from .conversion import storage_to_markdown
from .markdown_storage import contains_macro, markdown_to_storage
from .outline import extract_section, find_headings, replace_section
from .writes import ensure_write_allowed, writes_enabled

mcp = FastMCP("confluence")
OutputFormat = Literal["markdown", "html", "storage"]
MAX_CHILD_NODES = 200
PENDING_MESSAGE = (
    "Queued, not executed. A person must approve it outside MCP with "
    "`confluence-mcp-review web` or `confluence-mcp-review approve`, which then writes it."
)


def _queued(op_id: str) -> dict[str, Any]:
    return {
        "dry_run": False,
        "queued": True,
        "operation_id": op_id,
        "status": "pending",
        "message": PENDING_MESSAGE,
    }


def _cql_escape(value: str, name: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{name} must not be empty.")
    if len(value) > 200:
        raise ValueError(f"{name} must be 200 characters or fewer.")
    return quote_cql(value)


def _page_summary(page: dict[str, Any], client: Any) -> dict[str, Any]:
    space = page.get("space") or {}
    version = page.get("version") or {}
    return {
        "page_id": str(page.get("id", "")),
        "title": page.get("title", ""),
        "space_key": space.get("key"),
        "version": version.get("number"),
        "url": client.page_url(page),
    }


def _convert_storage(storage: str, output_format: OutputFormat) -> str:
    if output_format == "storage":
        return storage
    if not storage:
        raise ConfluenceAPIError("The page has no storage body available to convert to Markdown.")
    return storage_to_markdown(storage)


def _page_content(page: dict[str, Any], output_format: OutputFormat) -> str:
    body = page.get("body") or {}
    storage = (body.get("storage") or {}).get("value") or ""
    if output_format == "html":
        # `view` is rendered by Confluence and usually includes macro output.
        # Storage is a useful fallback for deployments that do not expand `body.view`.
        return (body.get("view") or {}).get("value") or storage
    return _convert_storage(storage, output_format)


@mcp.tool()
def search_pages(query: str, space_key: str | None = None, limit: int = 10) -> dict[str, Any]:
    """Search readable Confluence pages by text, optionally within one space.

    Returns page IDs, titles, space keys, versions, and browser URLs. Use a returned
    page_id with get_page to retrieve the full page. The server sends GET requests only.
    """
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50.")
    escaped_query = _cql_escape(query, "query")
    cql = f'type = page AND text ~ "{escaped_query}"'
    if space_key:
        cql += f' AND space = "{_cql_escape(space_key, "space_key")}"'
    client = get_client()
    pages = client.search_pages(cql, limit)
    return {"results": [_page_summary(page, client) for page in pages], "count": len(pages)}


def _search_result_summary(result: dict[str, Any], client: Any) -> dict[str, Any]:
    content = result.get("content") or {}
    space = content.get("space") or {}
    return {
        "page_id": str(content.get("id", "")),
        "title": result.get("title") or content.get("title", ""),
        "space_key": space.get("key"),
        "excerpt": result.get("excerpt", ""),
        "last_modified": result.get("lastModified"),
        "url": client.absolute_url(result.get("url")),
    }


@mcp.tool()
def cql_search(cql: str, limit: int = 25, start: int = 0) -> dict[str, Any]:
    """Run a raw CQL query against Confluence and return matching pages."""
    cql = cql.strip()
    if not cql:
        raise ValueError("cql must not be empty.")
    if len(cql) > 4000:
        raise ValueError("cql must be 4000 characters or fewer.")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50.")
    if start < 0:
        raise ValueError("start must be zero or greater.")

    client = get_client()
    payload = client.search_cql(cql, limit=limit, start=start)
    results = payload.get("results", [])
    total = payload.get("totalSize")
    if isinstance(total, int):
        has_more = start + len(results) < total
    else:
        has_more = len(results) == limit
    return {
        "results": [_search_result_summary(item, client) for item in results],
        "count": len(results),
        "next_start": start + len(results) if has_more else None,
    }


@mcp.tool()
def list_spaces(limit: int = 50, start: int = 0) -> dict[str, Any]:
    """List global Confluence spaces visible to the current account."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")
    if start < 0:
        raise ValueError("start must be zero or greater.")

    client = get_client()
    payload = client.list_spaces(limit=limit, start=start)
    results = payload.get("results", [])
    # `/rest/api/space` returns `size` as the page size, not the total; a full page implies more.
    has_more = len(results) == limit
    return {
        "spaces": [
            {
                "key": space.get("key", ""),
                "name": space.get("name", ""),
                "url": client.absolute_url((space.get("_links") or {}).get("webui")),
            }
            for space in results
        ],
        "count": len(results),
        "next_start": start + len(results) if has_more else None,
    }


def _comment_parent(comment: dict[str, Any]) -> str | None:
    comment_ancestors = [
        ancestor for ancestor in comment.get("ancestors") or [] if ancestor.get("type") == "comment"
    ]
    if not comment_ancestors:
        return None
    return str(comment_ancestors[-1].get("id", ""))


@mcp.tool()
def get_comments(page_id: str, limit: int = 50) -> dict[str, Any]:
    """Read page comments as Markdown, preserving reply parents."""
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50.")

    client = get_client()
    comments = client.get_comments(page_id, limit=limit)
    return {
        "comments": [
            {
                "comment_id": str(comment.get("id", "")),
                "author": ((comment.get("history") or {}).get("createdBy") or {}).get("displayName"),
                "created": (comment.get("history") or {}).get("createdDate"),
                "parent_comment_id": _comment_parent(comment),
                "content": _convert_storage(
                    ((comment.get("body") or {}).get("storage") or {}).get("value") or "",
                    "markdown",
                ),
            }
            for comment in comments
        ],
        "count": len(comments),
    }


def _storage(page: dict[str, Any]) -> str:
    return ((page.get("body") or {}).get("storage") or {}).get("value") or ""


def _unified_diff(old: str, new: str, from_label: str, to_label: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), fromfile=from_label, tofile=to_label, lineterm=""
        )
    )


@mcp.tool()
def get_children(page_id: str, depth: int = 1, limit: int = 50) -> dict[str, Any]:
    """List child pages, optionally recursing up to three levels."""
    if not 1 <= depth <= 3:
        raise ValueError("depth must be between 1 and 3.")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50.")

    client = get_client()
    budget = [MAX_CHILD_NODES]
    truncated = False

    def build(current_id: str, levels_left: int) -> list[dict[str, Any]]:
        nonlocal truncated
        nodes = []
        children = client.get_child_pages(current_id, limit=limit)
        if len(children) == limit:
            truncated = True
        for child in children:
            if budget[0] <= 0:
                truncated = True
                break
            budget[0] -= 1
            node = _page_summary(child, client)
            if levels_left > 1:
                node["children"] = build(str(child.get("id", "")), levels_left - 1)
            nodes.append(node)
        return nodes

    return {"page_id": page_id, "children": build(page_id, depth), "truncated": truncated}


def _version_page(client: Any, page_id: str, version: int) -> dict[str, Any]:
    try:
        return client.get_page_version(page_id, version)
    except ConfluenceAPIError as exc:
        if exc.status_code == 404:
            raise ValueError(f"Version {version} does not exist for page {page_id}.") from exc
        raise


@mcp.tool()
def get_page_history(
    page_id: str,
    from_version: int | None = None,
    to_version: int | None = None,
    limit: int = 25,
    max_chars: int = 4000,
) -> dict[str, Any]:
    """List page versions, or diff two versions as Markdown."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1.")
    if (from_version is None) != (to_version is None):
        raise ValueError("Provide both from_version and to_version, or neither.")
    for version in (from_version, to_version):
        if version is not None and version < 1:
            raise ValueError("version numbers must be at least 1.")
    if from_version is not None and from_version == to_version:
        raise ValueError("from_version and to_version must differ.")

    client = get_client()
    versions = [
        {
            "number": item.get("number"),
            "when": item.get("when"),
            "by": (item.get("by") or {}).get("displayName"),
            "message": item.get("message", ""),
        }
        for item in client.list_versions(page_id)[:limit]
    ]
    result: dict[str, Any] = {"page_id": page_id, "versions": versions}
    if from_version is None:
        return result

    old_storage = _storage(_version_page(client, page_id, from_version))
    new_storage = _storage(_version_page(client, page_id, to_version))
    diff = _unified_diff(
        storage_to_markdown(old_storage),
        storage_to_markdown(new_storage),
        f"v{from_version}",
        f"v{to_version}",
    )
    result["diff"] = diff[:max_chars]
    result["truncated"] = len(diff) > max_chars
    return result


def update_page_section(
    page_id: str,
    section_title: str,
    new_content_markdown: str,
    expected_version: int,
    dry_run: bool = True,
    change_message: str = "",
    max_chars: int = 4000,
) -> dict[str, Any]:
    """Replace one heading section, preserving the rest of the page byte for byte.

    A dry run previews the change; dry_run=False queues it for human approval.
    """
    section_title = section_title.strip()
    if not section_title:
        raise ValueError("section_title must not be empty.")
    if expected_version < 1:
        raise ValueError("expected_version must be at least 1.")
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1.")

    client = get_client()
    page = client.get_page(page_id)
    space_key = (page.get("space") or {}).get("key")
    ensure_write_allowed(space_key)

    current = (page.get("version") or {}).get("number")
    if current != expected_version:
        raise ConfluenceAPIError(
            f"Version conflict: current version is {current}, expected_version was {expected_version}. "
            "Re-read the page and retry."
        )

    old_storage = _storage(page)
    heading, body = extract_section(old_storage, section_title)
    new_body = markdown_to_storage(new_content_markdown)
    new_storage = replace_section(old_storage, section_title, new_body)

    old_section = old_storage[heading.start : heading.end] + body
    new_section = old_storage[heading.start : heading.end] + new_body
    diff = _unified_diff(
        storage_to_markdown(old_section),
        storage_to_markdown(new_section),
        f"v{current} {section_title}",
        f"v{current + 1} {section_title}",
    )
    if dry_run:
        return {
            "dry_run": True,
            "page_id": page_id,
            "section_title": heading.title,
            "version_before": current,
            "version_after": current + 1,
            "diff": diff[:max_chars],
            "truncated": len(diff) > max_chars,
            "storage_preview": new_section[:max_chars],
        }

    payload = {
        "id": page_id,
        "type": "page",
        "title": page.get("title", ""),
        "version": {
            "number": current + 1,
            "message": f"[MCP] {change_message}".strip(),
        },
        "body": {"storage": {"representation": "storage", "value": new_storage}},
    }
    return _queued(
        queue.enqueue(
            "update_page_section",
            kind="update",
            page_id=page_id,
            space_key=space_key,
            version_before=current,
            summary=heading.title,
            preview=diff,
            payload=payload,
        )
    )


def update_page(
    page_id: str,
    expected_version: int,
    content: str,
    title: str | None = None,
    content_format: Literal["markdown", "storage"] = "markdown",
    dry_run: bool = True,
    force: bool = False,
    change_message: str = "",
    max_chars: int = 4000,
) -> dict[str, Any]:
    """Replace a page body, guarded by an expected version.

    A dry run previews the change; dry_run=False queues it for human approval.
    """
    if expected_version < 1:
        raise ValueError("expected_version must be at least 1.")
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1.")
    if content_format not in {"markdown", "storage"}:
        raise ValueError('content_format must be "markdown" or "storage".')
    if not content.strip():
        raise ValueError("content must not be empty.")

    client = get_client()
    page = client.get_page(page_id)
    space_key = (page.get("space") or {}).get("key")
    ensure_write_allowed(space_key)

    current = (page.get("version") or {}).get("number")
    if current != expected_version:
        raise ConfluenceAPIError(
            f"Version conflict: current version is {current}, expected_version was {expected_version}. "
            "Re-read the page and retry."
        )

    old_storage = _storage(page)
    if content_format == "markdown":
        if contains_macro(old_storage) and not force:
            raise ConfluenceAPIError(
                "This page contains Confluence macros; replacing it with Markdown would drop them. "
                'Use update_page_section, content_format="storage", or force=True.'
            )
        new_storage = markdown_to_storage(content)
    else:
        new_storage = content

    new_title = title.strip() if title else page.get("title", "")
    if not new_title:
        raise ValueError("title must not be empty.")

    diff = _unified_diff(
        storage_to_markdown(old_storage),
        storage_to_markdown(new_storage),
        f"v{current}",
        f"v{current + 1}",
    )
    if dry_run:
        return {
            "dry_run": True,
            "page_id": page_id,
            "title": new_title,
            "version_before": current,
            "version_after": current + 1,
            "diff": diff[:max_chars],
            "truncated": len(diff) > max_chars,
            "storage_preview": new_storage[:max_chars],
        }

    payload = {
        "id": page_id,
        "type": "page",
        "title": new_title,
        "version": {
            "number": current + 1,
            "message": f"[MCP] {change_message}".strip(),
        },
        "body": {"storage": {"representation": "storage", "value": new_storage}},
    }
    return _queued(
        queue.enqueue(
            "update_page",
            kind="update",
            page_id=page_id,
            space_key=space_key,
            version_before=current,
            summary=new_title,
            preview=diff,
            payload=payload,
        )
    )


def create_page(
    space_key: str,
    title: str,
    content_markdown: str,
    parent_page_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Create a page from Markdown.

    A dry run previews the change; dry_run=False queues it for human approval.
    """
    space_key = space_key.strip()
    title = title.strip()
    if not space_key:
        raise ValueError("space_key must not be empty.")
    if not title:
        raise ValueError("title must not be empty.")
    if not content_markdown.strip():
        raise ValueError("content_markdown must not be empty.")
    ensure_write_allowed(space_key)

    client = get_client()
    cql = (
        f'type = page AND space = "{quote_cql(space_key)}" '
        f'AND title = "{quote_cql(title)}"'
    )
    existing = client.search_pages(cql, 5)
    if existing:
        raise ConfluenceAPIError(
            f'A page titled "{title}" already exists in space {space_key}: '
            f"{_page_summary(existing[0], client)['url']}"
        )

    ancestors = None
    if parent_page_id is not None:
        if not parent_page_id.isdigit():
            raise ValueError("parent_page_id must contain only digits.")
        parent = client.get_page(parent_page_id)
        parent_space = (parent.get("space") or {}).get("key")
        if parent_space != space_key:
            raise ValueError(
                f"Parent page {parent_page_id} is in a different space ({parent_space})."
            )
        ancestors = [{"id": parent_page_id}]

    storage = markdown_to_storage(content_markdown)
    target = {"space_key": space_key, "title": title, "parent_page_id": parent_page_id}
    if dry_run:
        return {
            "dry_run": True,
            "action": "create_page",
            "target": target,
            "storage_preview": storage[:4000],
        }

    payload: dict[str, Any] = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"representation": "storage", "value": storage}},
    }
    if ancestors:
        payload["ancestors"] = ancestors
    return _queued(
        queue.enqueue(
            "create_page",
            kind="create",
            page_id=None,
            space_key=space_key,
            version_before=None,
            summary=title,
            preview=content_markdown,
            payload=payload,
        )
    )


def add_comment(
    page_id: str,
    content_markdown: str,
    parent_comment_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Add a page comment from Markdown.

    A dry run previews the change; dry_run=False queues it for human approval.
    """
    if not content_markdown.strip():
        raise ValueError("content_markdown must not be empty.")
    if parent_comment_id is not None and not parent_comment_id.isdigit():
        raise ValueError("parent_comment_id must contain only digits.")

    client = get_client()
    page = client.get_page(page_id)
    space_key = (page.get("space") or {}).get("key")
    ensure_write_allowed(space_key)

    storage = markdown_to_storage(content_markdown)
    if dry_run:
        return {
            "dry_run": True,
            "action": "add_comment",
            "target": {"page_id": page_id, "parent_comment_id": parent_comment_id},
            "storage_preview": storage[:4000],
        }

    payload: dict[str, Any] = {
        "type": "comment",
        "container": {"id": page_id, "type": "page"},
        "body": {"storage": {"representation": "storage", "value": storage}},
    }
    if parent_comment_id is not None:
        payload["ancestors"] = [{"id": parent_comment_id}]
    return _queued(
        queue.enqueue(
            "add_comment",
            kind="create",
            page_id=page_id,
            space_key=space_key,
            version_before=None,
            summary=f"comment on page {page_id}",
            preview=content_markdown,
            payload=payload,
        )
    )


MOVE_SIBLING_LIMIT = 200
_POSITION_WORDS = {"before": "之前", "after": "之后", "append": "下（作为最后一个子页面）"}


def _sibling_titles(client: Any, parent_id: str) -> tuple[list[dict[str, str]], bool]:
    children = client.get_child_pages(parent_id, limit=MOVE_SIBLING_LIMIT)
    items = [{"page_id": str(c.get("id", "")), "title": c.get("title", "")} for c in children]
    return items, len(children) >= MOVE_SIBLING_LIMIT


def _planned_order(
    siblings: list[dict[str, str]], moved: dict[str, str], position: str, target_id: str
) -> list[dict[str, str]]:
    order = [item for item in siblings if item["page_id"] != moved["page_id"]]
    if position == "append":
        return order + [moved]
    index = next(i for i, item in enumerate(order) if item["page_id"] == target_id)
    return order[: index + (position == "after")] + [moved] + order[index + (position == "after") :]


def _order_text(items: list[dict[str, str]], moved_id: str) -> str:
    return "\n".join(
        f"{'→' if item['page_id'] == moved_id else ' '} {n}. {item['title']} ({item['page_id']})"
        for n, item in enumerate(items, 1)
    )


def move_page(
    page_id: str,
    position: Literal["before", "after", "append"],
    target_page_id: str,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Reorder or re-parent a page within its space.

    position="before"/"after" places the page next to the sibling target_page_id (it takes
    that sibling's parent); position="append" makes it the last child of target_page_id.
    A dry run shows the sibling order before and after; dry_run=False queues the move for
    human approval. Queue several moves in order to arrange many pages; they run in that order.
    """
    if position not in ("before", "after", "append"):
        raise ValueError('position must be "before", "after" or "append".')
    target_page_id = target_page_id.strip()
    if not target_page_id.isdigit():
        raise ValueError("target_page_id must contain only digits.")
    if target_page_id == page_id:
        raise ValueError("target_page_id must differ from page_id.")

    client = get_client()
    page = client.get_page(page_id)
    target = client.get_page(target_page_id)
    space_key = (page.get("space") or {}).get("key")
    target_space = (target.get("space") or {}).get("key")
    if target_space != space_key:
        raise ValueError(
            f"Target page {target_page_id} is in space {target_space}, not {space_key}; "
            "moving between spaces is not supported."
        )
    if any(str(a.get("id")) == page_id for a in target.get("ancestors") or []):
        raise ValueError("Cannot move a page next to or under one of its own descendants.")
    ensure_write_allowed(space_key)

    old_ancestors = page.get("ancestors") or []
    old_parent = old_ancestors[-1] if old_ancestors else None
    if position == "append":
        new_parent: dict[str, Any] | None = target
    else:
        target_ancestors = target.get("ancestors") or []
        new_parent = target_ancestors[-1] if target_ancestors else None
    if new_parent is None:
        raise ValueError(
            f"Page {target_page_id} is at the top level of space {space_key}; "
            "moving pages to the space root is not supported."
        )

    moved = {"page_id": page_id, "title": page.get("title", "")}
    new_parent_id = str(new_parent.get("id", ""))
    siblings, truncated = _sibling_titles(client, new_parent_id)
    if position != "append" and not any(s["page_id"] == target_page_id for s in siblings):
        raise ConfluenceAPIError(
            f"Page {target_page_id} was not found among the first {MOVE_SIBLING_LIMIT} children "
            f"of its parent {new_parent_id}, so the new order cannot be previewed."
        )
    order_after = _planned_order(siblings, moved, position, target_page_id)
    same_parent = old_parent is not None and str(old_parent.get("id")) == new_parent_id
    if same_parent and [s["page_id"] for s in siblings] == [s["page_id"] for s in order_after]:
        raise ValueError("The page is already in that position; nothing to move.")

    parent_title = new_parent.get("title", "")
    target_title = target.get("title", "")
    preview = (
        f"移动「{moved['title']}」到「{target_title}」{_POSITION_WORDS[position]}\n"
        f"原父页面：{old_parent.get('title', '') if old_parent else '(空间根目录)'}\n"
        f"新父页面：{parent_title}\n\n"
        f"移动后「{parent_title}」的子页面顺序：\n{_order_text(order_after, page_id)}"
    )
    if truncated:
        preview += f"\n（只读取了前 {MOVE_SIBLING_LIMIT} 个子页面）"

    if dry_run:
        return {
            "dry_run": True,
            "action": "move_page",
            "page_id": page_id,
            "title": moved["title"],
            "position": position,
            "target_page_id": target_page_id,
            "old_parent_page_id": str(old_parent.get("id")) if old_parent else None,
            "new_parent_page_id": new_parent_id,
            "order_before": [s["title"] for s in siblings],
            "order_after": [s["title"] for s in order_after],
            "truncated": truncated,
        }

    payload = {"title": moved["title"], "position": position, "target_id": target_page_id}
    return _queued(
        queue.enqueue(
            "move_page",
            kind="update",
            page_id=page_id,
            space_key=space_key,
            version_before=(page.get("version") or {}).get("number"),
            summary=f"{moved['title']} → {target_title} {position}",
            preview=preview,
            payload=payload,
        )
    )


@mcp.tool()
def get_page_outline(page_id: str) -> dict[str, Any]:
    """List the h1-h6 headings of a page without returning its body."""
    client = get_client()
    page = client.get_page(page_id)
    storage = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
    return {
        **_page_summary(page, client),
        "headings": [
            {"level": heading.level, "title": heading.title, "anchor": heading.anchor}
            for heading in find_headings(storage)
        ],
    }


@mcp.tool()
def get_page(
    page_id: str,
    output_format: OutputFormat = "markdown",
    section: str | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Read one Confluence page, optionally only one section, with an optional length cap."""
    if max_chars is not None and max_chars < 1:
        raise ValueError("max_chars must be at least 1.")

    client = get_client()
    page = client.get_page(page_id)
    storage = ((page.get("body") or {}).get("storage") or {}).get("value") or ""

    if section is not None:
        if output_format == "html":
            raise ValueError(
                'section is only supported with output_format "markdown" or "storage".'
            )
        heading, body = extract_section(storage, section)
        content = _convert_storage(storage[heading.start : heading.end] + body, output_format)
    else:
        content = _page_content(page, output_format)

    truncated = False
    if max_chars is not None:
        truncated = len(content) > max_chars
        content = content[:max_chars]

    return {
        **_page_summary(page, client),
        "format": output_format,
        "content": content,
        "truncated": truncated,
    }


@mcp.tool()
def get_page_by_title(
    title: str,
    space_key: str | None = None,
    output_format: OutputFormat = "markdown",
) -> dict[str, Any]:
    """Read a Confluence page by exact title; provide space_key if titles are duplicated."""
    escaped_title = _cql_escape(title, "title")
    cql = f'type = page AND title = "{escaped_title}"'
    if space_key:
        cql += f' AND space = "{_cql_escape(space_key, "space_key")}"'

    client = get_client()
    matches = client.search_pages(cql, 25)
    if not matches:
        raise ConfluenceAPIError(f'No readable Confluence page found with title "{title}".')
    if len(matches) > 1:
        candidates = [
            {"page_id": str(item.get("id", "")), "space_key": (item.get("space") or {}).get("key")}
            for item in matches
        ]
        raise ConfluenceAPIError(
            f"More than one page has this title; provide space_key or call search_pages. "
            f"Candidates: {candidates}"
        )
    page = client.get_page(str(matches[0].get("id", "")))
    return {
        **_page_summary(page, client),
        "format": output_format,
        "content": _page_content(page, output_format),
    }


_QUEUE_FIELDS = (
    "id", "status", "action", "space_key", "page_id", "version_before", "summary", "created_at",
)
_ACTIVE = ("pending", "approved", "executing")
_FINISHED = ("succeeded", "failed", "indeterminate")


def _check_paging(page: int, page_size: int) -> None:
    if page < 1:
        raise ValueError("page must be at least 1.")
    if not 1 <= page_size <= 200:
        raise ValueError("page_size must be between 1 and 200.")


def _check_ids(operation_ids: list[str]) -> None:
    if not 1 <= len(operation_ids) <= 200:
        raise ValueError("operation_ids must contain between 1 and 200 ids.")


def _paged(ops: list[dict[str, Any]], fields: tuple[str, ...], page: int, page_size: int):
    start = (page - 1) * page_size
    return {
        "items": [{key: op[key] for key in fields} for op in ops[start : start + page_size]],
        "total": len(ops),
        "page": page,
        "page_size": page_size,
    }


def list_queued_operations(page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """List queued writes that are pending, approved or executing, without their payloads."""
    _check_paging(page, page_size)
    return _paged(queue.list_ops(_ACTIVE), _QUEUE_FIELDS, page, page_size)


def get_queued_operations(operation_ids: list[str]) -> dict[str, Any]:
    """Read queued writes by id, with their preview, in the order requested."""
    _check_ids(operation_ids)
    fields = _QUEUE_FIELDS + ("preview", "result", "error", "updated_at")
    operations: list[dict[str, Any]] = []
    missing: list[str] = []
    for op_id in operation_ids:
        op = queue.get_op(op_id)
        if op is None:
            missing.append(op_id)
        else:
            operations.append({key: op[key] for key in fields})
    return {"operations": operations, "missing": missing}


def cancel_queued_operations(operation_ids: list[str]) -> dict[str, Any]:
    """Withdraw pending writes. Approved, executing and finished ones are left untouched."""
    _check_ids(operation_ids)
    cancelled = queue.reject(operation_ids)
    not_cancelled = []
    for op_id in operation_ids:
        if op_id not in cancelled:
            op = queue.get_op(op_id)
            not_cancelled.append({"id": op_id, "status": op["status"] if op else "unknown"})
    return {"cancelled": cancelled, "not_cancelled": not_cancelled}


def get_execution_log(page: int = 1, page_size: int = 50) -> dict[str, Any]:
    """List writes that finished (succeeded, failed or indeterminate), newest first."""
    _check_paging(page, page_size)
    finished = sorted(
        reversed(queue.list_ops(_FINISHED)), key=lambda op: op["updated_at"], reverse=True
    )
    return _paged(finished, _QUEUE_FIELDS + ("result", "error", "updated_at"), page, page_size)


def get_review_link() -> dict[str, Any]:
    """Return the approval page URL, token included, so the person can open it and approve.

    Starts the approval page in this MCP process on first call; later calls return the same URL.
    """
    try:
        url = web.review_url(get_client())
    except OSError as exc:
        raise ConfluenceConfigurationError(
            f"审批页端口 {web.review_port()} 无法使用（{exc.strerror or exc}）。"
            "请在 .env 中设置 CONFLUENCE_REVIEW_PORT 为可用端口。"
        ) from exc
    return {"url": url, "pending": len(queue.list_ops(("pending",)))}


def register_write_tools(server: FastMCP) -> None:
    for tool in (
        create_page,
        add_comment,
        update_page,
        update_page_section,
        move_page,
        list_queued_operations,
        get_queued_operations,
        cancel_queued_operations,
        get_execution_log,
        get_review_link,
    ):
        server.tool()(tool)


if writes_enabled():
    register_write_tools(mcp)


def main() -> None:
    """Run the MCP server over stdio for local MCP hosts."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
