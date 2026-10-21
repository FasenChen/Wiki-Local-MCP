"""MCP server exposing read-only Confluence page tools."""

from __future__ import annotations

import difflib
from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .client import ConfluenceAPIError, get_client, quote_cql
from .conversion import storage_to_markdown
from .markdown_storage import markdown_to_storage
from .outline import extract_section, find_headings
from .writes import audit_write, ensure_write_allowed, writes_enabled

mcp = FastMCP("confluence")
OutputFormat = Literal["markdown", "html", "storage"]
MAX_CHILD_NODES = 200


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
        for child in client.get_child_pages(current_id, limit=limit):
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

    old_storage = _storage(client.get_page_version(page_id, from_version))
    new_storage = _storage(client.get_page_version(page_id, to_version or from_version))
    diff = _unified_diff(
        storage_to_markdown(old_storage),
        storage_to_markdown(new_storage),
        f"v{from_version}",
        f"v{to_version}",
    )
    result["diff"] = diff[:max_chars]
    result["truncated"] = len(diff) > max_chars
    return result


def create_page(
    space_key: str,
    title: str,
    content_markdown: str,
    parent_page_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Create a page from Markdown. Defaults to a dry run that posts nothing."""
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
    created = client.create_content(payload)
    audit_write(
        "create_page",
        page_id=str(created.get("id", "")),
        space_key=space_key,
        version_before=None,
        version_after=(created.get("version") or {}).get("number"),
        result="created",
    )
    return {
        "dry_run": False,
        **_page_summary(created, client),
    }


def add_comment(
    page_id: str,
    content_markdown: str,
    parent_comment_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Add a page comment from Markdown. Defaults to a dry run that posts nothing."""
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
    created = client.create_content(payload)
    audit_write(
        "add_comment",
        page_id=page_id,
        space_key=space_key,
        version_before=None,
        version_after=None,
        result="created",
    )
    return {
        "dry_run": False,
        "comment_id": str(created.get("id", "")),
        "page_id": page_id,
        "url": client.page_url(created),
    }


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


def register_write_tools(server: FastMCP) -> None:
    for tool in (create_page, add_comment):
        server.tool()(tool)


if writes_enabled():
    register_write_tools(mcp)


def main() -> None:
    """Run the MCP server over stdio for local MCP hosts."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
