"""MCP server exposing read-only Confluence page tools."""

from __future__ import annotations

from typing import Any, Literal

from mcp.server.fastmcp import FastMCP

from .client import ConfluenceAPIError, get_client, quote_cql
from .conversion import storage_to_markdown
from .outline import find_headings

mcp = FastMCP("confluence-readonly")
OutputFormat = Literal["markdown", "html", "storage"]


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


def _page_content(page: dict[str, Any], output_format: OutputFormat) -> str:
    body = page.get("body") or {}
    storage = (body.get("storage") or {}).get("value") or ""
    if output_format == "storage":
        return storage
    if output_format == "html":
        # `view` is rendered by Confluence and usually includes macro output.
        # Storage is a useful fallback for deployments that do not expand `body.view`.
        return (body.get("view") or {}).get("value") or storage
    if not storage:
        raise ConfluenceAPIError("The page has no storage body available to convert to Markdown.")
    return storage_to_markdown(storage)


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
def get_page(page_id: str, output_format: OutputFormat = "markdown") -> dict[str, Any]:
    """Read one Confluence page by ID as Markdown, rendered HTML, or storage XHTML."""
    client = get_client()
    page = client.get_page(page_id)
    return {
        **_page_summary(page, client),
        "format": output_format,
        "content": _page_content(page, output_format),
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


def main() -> None:
    """Run the MCP server over stdio for local MCP hosts."""
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
