"""Convert Markdown into Confluence storage XHTML."""

from __future__ import annotations

import html
import re

import markdown

_CODE_BLOCK = re.compile(
    r'<pre><code(?: class="language-([^"]+)")?>(.*?)</code>\s*</pre>',
    re.DOTALL,
)


def markdown_to_storage(markdown_text: str) -> str:
    rendered = markdown.markdown(
        markdown_text,
        extensions=["tables", "fenced_code"],
        output_format="xhtml",
    )
    return _CODE_BLOCK.sub(_code_macro, rendered)


def _code_macro(match: re.Match[str]) -> str:
    language, code = match.group(1), html.unescape(match.group(2))
    # A literal ]]> would close the CDATA section early; split it per the XHTML spec.
    code = code.replace("]]>", "]]]]><![CDATA[>")
    if not code.endswith("\n"):
        code += "\n"
    parameter = (
        f'<ac:parameter ac:name="language">{html.escape(language)}</ac:parameter>'
        if language
        else ""
    )
    return (
        f'<ac:structured-macro ac:name="code">{parameter}'
        f"<ac:plain-text-body><![CDATA[{code}]]></ac:plain-text-body>"
        "</ac:structured-macro>"
    )


def contains_macro(storage: str) -> bool:
    return "<ac:structured-macro" in storage
