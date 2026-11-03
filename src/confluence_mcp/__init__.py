"""Read-only MCP integration for Confluence Data Center."""

import os
from pathlib import Path

from .settings_file import DEFAULT_ENV_FILE, ENV_FILE_VAR, load_env_file

__version__ = "0.1.0"

# Runs before any module reads os.environ, including server.py's import-time write check.
load_env_file(Path(os.environ.get(ENV_FILE_VAR) or DEFAULT_ENV_FILE))
