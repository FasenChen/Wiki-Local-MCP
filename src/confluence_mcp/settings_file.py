"""Load MCP settings from a local .env file without overriding the process environment."""

from __future__ import annotations

import os
import re
from pathlib import Path

ENV_FILE_VAR = "CONFLUENCE_MCP_ENV_FILE"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_COMMENT = re.compile(r"(?:^|\s)#")


def _value(raw: str) -> str:
    value = raw.strip()
    if value[:1] in {'"', "'"}:
        end = value.find(value[0], 1)
        if end != -1:
            return value[1:end]
    # shortcut: "#" starts a comment only after whitespace, so URL fragments survive unquoted.
    match = _COMMENT.search(value)
    return (value[: match.start()] if match else value).strip()


def parse_env(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for number, raw in enumerate(text.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, sep, value = line.partition("=")
        key = key.strip()
        if not sep or not key:
            raise ValueError(f"line {number}: expected KEY=VALUE")
        values[key] = _value(value)
    return values


def load_env_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    loaded = []
    for key, value in parse_env(path.read_text(encoding="utf-8-sig")).items():
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
