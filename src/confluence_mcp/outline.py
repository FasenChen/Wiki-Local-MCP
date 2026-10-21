"""Locate headings and sections in Confluence storage XHTML."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass

_HEADING = re.compile(r"<h([1-6])(?:\s[^>]*)?>(.*?)</h\1\s*>", re.IGNORECASE | re.DOTALL)
_MASKED = re.compile(r"<!\[CDATA\[.*?\]\]>|<!--.*?-->", re.DOTALL)


@dataclass(frozen=True)
class Heading:
    level: int
    title: str
    anchor: str
    start: int
    end: int


def _mask(storage: str) -> str:
    # Headings inside code macros are literal text, not sections.
    return _MASKED.sub(lambda match: " " * len(match.group(0)), storage)


def _plain_text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", "", fragment)
    return " ".join(html.unescape(text).split())


def find_headings(storage: str) -> list[Heading]:
    masked = _mask(storage)
    headings: list[Heading] = []
    used: dict[str, int] = {}
    for match in _HEADING.finditer(masked):
        title = _plain_text(match.group(2))
        base = re.sub(r"[^\w一-鿿]+", "-", title.lower()).strip("-") or "section"
        used[base] = used.get(base, 0) + 1
        anchor = base if used[base] == 1 else f"{base}-{used[base]}"
        headings.append(
            Heading(int(match.group(1)), title, anchor, match.start(), match.end())
        )
    return headings


def extract_section(storage: str, title: str) -> tuple[Heading, str]:
    headings = find_headings(storage)
    matches = [heading for heading in headings if heading.title.casefold() == title.casefold()]
    if not matches:
        available = ", ".join(heading.title for heading in headings) or "(none)"
        raise ValueError(f'No section titled "{title}". Available sections: {available}')
    if len(matches) > 1:
        candidates = ", ".join(f"{heading.title} ({heading.anchor})" for heading in matches)
        raise ValueError(
            f'more than one section titled "{title}"; use a unique title. '
            f"Candidates: {candidates}"
        )

    heading = matches[0]
    end = len(storage)
    for candidate in headings:
        if candidate.start > heading.start and candidate.level <= heading.level:
            end = candidate.start
            break
    return heading, storage[heading.end : end]


def replace_section(storage: str, title: str, new_body_storage: str) -> str:
    heading, body = extract_section(storage, title)
    if any(item.level <= heading.level for item in find_headings(new_body_storage)):
        raise ValueError(
            f"New content must not contain headings at level {heading.level} or higher; "
            "it would break the section boundary."
        )
    return storage[: heading.end] + new_body_storage + storage[heading.end + len(body) :]
