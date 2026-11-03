"""Load MCP settings from a local .env file without overriding the process environment."""

from __future__ import annotations

import os
from pathlib import Path

ENV_FILE_VAR = "CONFLUENCE_MCP_ENV_FILE"
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


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
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
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
