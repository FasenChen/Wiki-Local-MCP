"""Load MCP settings from the project's .env file."""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

PROJECT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"
_COMMENT = re.compile(r"\s#")
_SETTING_KEYS = {
    "ATLASSIAN_CONFLUENCE_URL",
    "ATLASSIAN_CONFLUENCE_PAT",
    "ATLASSIAN_CONFLUENCE_CA_BUNDLE",
    "CONFLUENCE_ENABLE_WRITES",
    "CONFLUENCE_WRITE_SPACES",
}


def _value(raw: str) -> str:
    value = raw.strip()
    if value[:1] in {'"', "'"}:
        end = value.find(value[0], 1)
        if end != -1:
            return value[1:end]
    # shortcut: "#" starts a comment only after whitespace, so URL fragments survive unquoted.
    match = _COMMENT.search(raw)
    return (raw[: match.start()] if match else raw).strip()


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


def load_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = parse_env(path.read_text(encoding="utf-8-sig"))
    return {key: value for key, value in values.items() if key in _SETTING_KEYS}


@lru_cache(maxsize=1)
def get_settings() -> dict[str, str]:
    return load_env_file(PROJECT_ENV_FILE)
