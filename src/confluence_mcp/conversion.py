"""Convert Confluence storage XHTML to Markdown."""

from markdownify import markdownify


def storage_to_markdown(storage_xhtml: str) -> str:
    """Convert the storage representation to readable Markdown."""
    return markdownify(storage_xhtml, heading_style="ATX", bullets="-").strip()
