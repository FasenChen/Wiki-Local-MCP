"""Snapshot Markdown images and replace their HTML with Confluence attachment references."""

from __future__ import annotations

import hashlib
import html
import mimetypes
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

import httpx


@dataclass(frozen=True)
class ImageAttachment:
    filename: str
    source: str
    content_type: str
    data: bytes

    def summary(self) -> dict[str, str | int]:
        return {
            "filename": self.filename,
            "source": self.source,
            "content_type": self.content_type,
            "size_bytes": len(self.data),
        }


def _attachment_image(filename: str, attrs: dict[str, str | None]) -> str:
    attributes = "".join(
        f' ac:{name}="{html.escape(attrs[name], quote=True)}"'
        for name in ("alt", "title", "width", "height") if attrs.get(name)
    )
    return (
        f"<ac:image{attributes}>"
        f'<ri:attachment ri:filename="{html.escape(filename, quote=True)}" />'
        "</ac:image>"
    )


def _read_image(source: str, base_dir: Path | None) -> ImageAttachment:
    if source.startswith("//"):
        source = "https:" + source
    # Windows drive letters must be recognised before interpreting URL schemes.
    path = Path(unquote(source))
    parsed = urlsplit(source)
    if not path.is_absolute() and parsed.scheme in {"http", "https"}:
        if parsed.username or parsed.password:
            raise ValueError("Image URLs must not contain credentials.")
        try:
            # Use a separate client: Wiki credentials must never reach an image host.
            response = httpx.get(source, follow_redirects=True, timeout=30.0)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError("Could not download an image; check its URL and access permissions.") from exc
        data = response.content
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if not content_type or content_type == "application/octet-stream":
            content_type = mimetypes.guess_type(parsed.path)[0] or ""
        suffix = mimetypes.guess_extension(content_type) or ""
    else:
        if parsed.scheme == "file":
            if parsed.netloc not in {"", "localhost"}:
                raise ValueError("Only local file: image URLs are supported.")
            path = Path(url2pathname(parsed.path))
        elif not path.is_absolute():
            if parsed.scheme or parsed.netloc:
                raise ValueError("Images must use local paths, file: URLs, or absolute http(s) URLs.")
            path = Path(unquote(parsed.path))
        if not path.is_absolute():
            if base_dir is None:
                raise ValueError("image_base_dir is required for relative image paths.")
            path = base_dir / path
        try:
            path = path.resolve(strict=True)
            content_type = mimetypes.guess_type(path.name)[0] or ""
            if not content_type.startswith("image/"):
                raise ValueError(f"Not a supported image file: {path.name}")
            data = path.read_bytes()
        except OSError as exc:
            raise ValueError(f"Could not read image file: {path}") from exc
        source = str(path)
        suffix = mimetypes.guess_extension(content_type) or path.suffix.lower()
    if not content_type.startswith("image/") or not data:
        raise ValueError("An image must have an image/* content type and non-empty content.")
    # Content-addressed names never replace another image's bytes on an existing page.
    filename = f"mcp-{hashlib.sha256(data).hexdigest()}{suffix}"
    return ImageAttachment(filename, source, content_type, data)


class _ImageParser(HTMLParser):
    def __init__(self, storage: str, base_dir: Path | None) -> None:
        super().__init__(convert_charrefs=True)
        self.base_dir = base_dir
        self.images: dict[str, ImageAttachment] = {}
        self.sources: dict[str, str] = {}
        self.replacements: list[tuple[int, int, str]] = []
        self.line_offsets = [0]
        for line in storage.split("\n"):
            self.line_offsets.append(self.line_offsets[-1] + len(line) + 1)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "img":
            return
        attributes = dict(attrs)
        source = (attributes.get("src") or "").strip()
        if not source:
            raise ValueError("An image must have a non-empty src.")
        if source.startswith("attachment:"):
            filename = unquote(source[len("attachment:"):])
            if not filename or any(char in filename for char in "/\\\r\n"):
                raise ValueError("An attachment: image must name a file on the target page.")
        else:
            if source not in self.sources:
                image = _read_image(source, self.base_dir)
                self.images.setdefault(image.filename, image)
                self.sources[source] = image.filename
            filename = self.sources[source]
        line, column = self.getpos()
        start = self.line_offsets[line - 1] + column
        self.replacements.append(
            (start, start + len(self.get_starttag_text()), _attachment_image(filename, attributes))
        )


def prepare_images(storage: str, image_base_dir: str | None = None) -> tuple[str, list[ImageAttachment]]:
    """Read/download images now so approval and execution use the same bytes."""
    base_dir = Path(image_base_dir) if image_base_dir is not None else None
    if base_dir is not None and (not base_dir.is_absolute() or not base_dir.is_dir()):
        raise ValueError("image_base_dir must be an existing absolute directory containing the Markdown file.")
    parser = _ImageParser(storage, base_dir)
    parser.feed(storage)
    parser.close()
    for start, end, replacement in reversed(parser.replacements):
        storage = storage[:start] + replacement + storage[end:]
    return storage, list(parser.images.values())
