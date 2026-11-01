"""Local preview of the body a queued write would send.

The body comes from an agent, so the preview is an allowlist: unknown tags are unwrapped
or dropped, attributes are never copied except validated ones, and every text node is
escaped. The HTML is only ever shown inside a sandboxed frame.
"""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urlsplit, urlunsplit

# shortcut: an approximation of Confluence rendering (text, lists, tables, the code macro and
# external images; other macros are labelled, attachments are not fetched). Upgrade if
# reviewers need exact parity, e.g. by rendering Confluence's own body.view.

# An element is (tag, attrs, children); a text node is a str.
Node = Any

_MAX_DEPTH = 100
_CDATA = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)
_VOID = {"br", "hr", "img", "col", "wbr", "meta", "link", "input"}
_KEEP = {
    "p", "div", "span", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "table",
    "thead", "tbody", "tfoot", "tr", "th", "td", "pre", "code", "blockquote", "strong", "b",
    "em", "i", "u", "s", "sub", "sup",
}
_DROP = {
    "script", "style", "iframe", "frame", "frameset", "object", "embed", "applet", "form",
    "input", "button", "select", "textarea", "svg", "math", "noscript", "template", "link",
    "meta", "base", "head",
}
_TRANSPARENT = {"ac:rich-text-body", "ac:plain-text-body", "ac:link-body", "ac:plain-text-link-body"}
_CSS = (
    "body{margin:16px;font:14px/1.6 system-ui,'Microsoft YaHei',sans-serif;color:#111;background:#fff;overflow-wrap:anywhere}"
    "h1,h2,h3,h4,h5,h6{line-height:1.3}"
    "table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #bbb;padding:4px 8px;vertical-align:top}"
    "pre{background:#f4f4f5;padding:10px;border-radius:6px;overflow:auto;white-space:pre-wrap;word-break:break-word}"
    "code{font-family:Consolas,monospace}img{max-width:100%;height:auto}"
    ".cap{font-size:12px;color:#555}.url{color:#666;font-size:12px}"
    ".unsupported{color:#92400e;background:#fef3c7;padding:0 4px;border-radius:3px}"
    ".unsupported-block{border-left:3px solid #d97706;padding:4px 8px;margin:8px 0;color:#92400e}"
)


def proposed_storage(op: dict[str, Any]) -> str:
    """The body that approval would write: the payload's storage, never the diff in `preview`."""
    body = op["payload"].get("body")
    storage = body.get("storage") if isinstance(body, dict) else None
    value = storage.get("value") if isinstance(storage, dict) else None
    return value if isinstance(value, str) else ""


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root: Node = ("", {}, [])
        self._open: list[Node] = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node: Node = (tag, dict(attrs), [])
        self._open[-1][2].append(node)
        if tag not in _VOID and not tag.startswith("ri:") and len(self._open) <= _MAX_DEPTH:
            self._open.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._open[-1][2].append((tag, dict(attrs), []))

    def handle_endtag(self, tag: str) -> None:
        for depth in range(len(self._open) - 1, 0, -1):
            if self._open[depth][0] == tag:
                del self._open[depth:]
                return

    def handle_data(self, data: str) -> None:
        self._open[-1][2].append(data)


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _is(node: Node, tag: str) -> bool:
    return isinstance(node, tuple) and node[0] == tag


def _text(node: Node) -> str:
    if isinstance(node, str):
        return node
    return "".join(_text(child) for child in node[2])


def _external(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def _label(text: str) -> str:
    return f'<span class="unsupported">[{_esc(text)}]</span>'


def _img(src: str | None, alt: str | None) -> str:
    src = (src or "").strip()
    if not _external(src):
        return _label("图片未渲染: 非 http(s) 地址")
    return f'<img src="{_esc(src)}" alt="{_esc(alt or "")}" referrerpolicy="no-referrer">'


def _ac_image(attrs: dict[str, Any], children: list[Node]) -> str:
    for child in children:
        if _is(child, "ri:url"):
            return _img(child[1].get("ri:value"), attrs.get("ac:alt"))
    for child in children:
        if _is(child, "ri:attachment"):
            return _label("图片未渲染: 附件 " + (child[1].get("ri:filename") or ""))
    return _label("图片未渲染: 未知来源")


def _param(children: list[Node], name: str) -> str:
    for child in children:
        if _is(child, "ac:parameter") and child[1].get("ac:name") == name:
            return _text(child).strip()
    return ""


def _macro(attrs: dict[str, Any], children: list[Node]) -> str:
    name = attrs.get("ac:name") or ""
    if name == "code":
        language = _param(children, "language")
        code = next((_text(child) for child in children if _is(child, "ac:plain-text-body")), "")
        caption = "代码" + (f" · {language}" if language else "")
        return (
            f'<div class="code"><div class="cap">{_esc(caption)}</div>'
            f"<pre><code>{_esc(code)}</code></pre></div>"
        )
    inner = "".join(_render(child) for child in children)
    return f'<div class="unsupported-block">宏未渲染：{_esc(name or "未知")}（以 Confluence 页面为准）</div>{inner}'


def _cell_attrs(tag: str, attrs: dict[str, Any]) -> str:
    if tag not in ("td", "th"):
        return ""
    out = ""
    for name in ("colspan", "rowspan"):
        value = attrs.get(name) or ""
        if re.fullmatch(r"[0-9]{1,3}", value):
            out += f' {name}="{value}"'
    return out


def _render(node: Node) -> str:
    if isinstance(node, str):
        return _esc(node)
    tag, attrs, children = node
    if tag in _DROP or tag == "ac:parameter":
        return ""
    if tag == "ac:structured-macro":
        return _macro(attrs, children)
    if tag == "ac:image":
        return _ac_image(attrs, children)
    if tag == "img":
        return _img(attrs.get("src"), attrs.get("alt"))
    inner = "".join(_render(child) for child in children)
    if tag == "a":
        href = (attrs.get("href") or "").strip()
        if not _external(href):
            return inner
        # Links show their address as text instead of being clickable: the frame must not navigate.
        return f'<span class="link">{inner}<span class="url">〔{_esc(href)}〕</span></span>'
    if tag in ("br", "hr"):
        return f"<{tag}>"
    if tag in _KEEP:
        return f"<{tag}{_cell_attrs(tag, attrs)}>{inner}</{tag}>"
    if tag in _TRANSPARENT:
        return inner
    if tag.startswith(("ac:", "ri:")):
        return _label(f"未渲染的 Confluence 元素: {tag}") + inner
    return inner


def storage_to_preview_html(storage: str) -> str:
    """Render storage XHTML as safe HTML: only allowlisted tags, every text node escaped."""
    # HTMLParser does not reliably recognise CDATA outside foreign content, so turn code-macro
    # CDATA into escaped text first. The macro body then reaches _render as ordinary text.
    builder = _TreeBuilder()
    builder.feed(_CDATA.sub(lambda match: html.escape(match.group(1), quote=False), storage))
    builder.close()
    return "".join(_render(child) for child in builder.root[2])


def render_document(storage: str) -> str:
    """A complete, self-contained HTML document for the sandboxed preview frame."""
    body = storage_to_preview_html(storage) if storage.strip() else _label("正文为空")
    return (
        '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
        '<meta name="referrer" content="no-referrer">'
        f"<style>{_CSS}</style></head><body>{body}</body></html>"
    )


_BLOCK = {
    "p", "div", "li", "br", "blockquote", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6",
    "table", "tr", "pre",
}
_PROVENANCE_CHARS = 16000
_COLLECTION_LABEL = "原文归档："
_SOURCE_LABEL = "来源："


def _lines(node: Node, lines: list[list[Node]]) -> None:
    """Split a block into lines; block elements, <br> and newlines start a new line."""
    if isinstance(node, str):
        for index, piece in enumerate(node.split("\n")):
            if index:
                lines.append([])
            lines[-1].append(piece)
    elif node[0] in _BLOCK:
        lines.append([])
        for child in node[2]:
            _lines(child, lines)
        lines.append([])
    else:
        lines[-1].append(node)


def _safe_source(url: str) -> bool:
    if not _external(url) or len(url) > 2000 or any(char.isspace() for char in url):
        return False
    try:
        parsed = urlsplit(url)
        # Accessing port also validates a malformed or out-of-range explicit port.
        _ = parsed.port
        return bool(parsed.hostname) and "@" not in parsed.netloc
    except ValueError:
        return False


def _first_link(nodes: list[Node]) -> tuple[str, str] | None:
    for node in nodes:
        if isinstance(node, str):
            continue
        if node[0] == "a":
            href = (node[1].get("href") or "").strip()
            if _safe_source(href):
                return href, _text(node).strip() or href
        found = _first_link(node[2])
        if found:
            return found
    return None


def _parent_url(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rsplit("/", 1)[0] or "/", "", ""))


def provenance(storage: str) -> dict[str, Any] | None:
    """Explicit provenance from the leading blockquote: collection name and original source link.

    Only lines that start with the exact labels count, and only in the first block, so an
    ordinary link in the body is never taken for its source.
    """
    builder = _TreeBuilder()
    head = _CDATA.sub(lambda match: html.escape(match.group(1), quote=False), storage[:_PROVENANCE_CHARS])
    builder.feed(head)
    builder.close()
    first = next((c for c in builder.root[2] if not (isinstance(c, str) and not c.strip())), None)
    if not _is(first, "blockquote"):
        return None
    lines: list[list[Node]] = [[]]
    _lines(first, lines)
    collection: str | None = None
    source: dict[str, Any] | None = None
    for line in lines:
        text = "".join(_text(node) for node in line).strip()
        if text.startswith(_COLLECTION_LABEL) and collection is None:
            collection = text[len(_COLLECTION_LABEL):].strip()[:100] or None
        elif text.startswith(_SOURCE_LABEL) and source is None:
            link = _first_link(line)
            if link:
                url, label = link
                source = {"label": label[:200], "url": url, "parent": _parent_url(url)}
    if collection is None and source is None:
        return None
    return {"collection": collection, "source": source}
