# Repository Guidelines

## Project Structure & Module Organization

`src/confluence_mcp/` contains the Python MCP package. `server.py` registers tools; `client.py` handles Confluence requests. `queue.py`, `apply.py`, and `writes.py` manage queued writes. `review.py`, `web.py`, and `web_page.py` provide the approval CLI, HTTP server, and embedded UI assets. `tests/` contains pytest tests and shared fixtures in `conftest.py`. `pyproject.toml` defines dependencies and entry points; `constraints.txt` pins dependency versions for pip.

## Build, Test, and Development Commands

Run from the repository root with Python 3.10+ and the project's `.venv`. On macOS/Linux, replace `.venv\Scripts\python.exe` with `.venv/bin/python` and use executables under `.venv/bin/`:

- `python -m venv .venv`: create the project virtual environment if it does not exist.
- `.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev]"`: install the project and development dependencies at pinned versions.
- `.venv\Scripts\python.exe -m confluence_mcp.server`: start the stdio server, normally managed by an MCP host.
- `.venv\Scripts\python.exe -m pytest`: run the test suite.
- `.venv\Scripts\python.exe -m pytest tests/test_move_page.py -q`: run focused tests.
- `.venv\Scripts\python.exe -m pip wheel . --no-deps --wheel-dir dist`: build a wheel distribution in `dist/`.
- `.venv\Scripts\confluence-mcp-review.exe list`: inspect the local approval queue.

## Coding Style & Naming Conventions

Use four-space indentation, `snake_case` for modules/functions/variables, `PascalCase` for classes, and `UPPER_SNAKE_CASE` for constants. Follow existing type annotations and package-relative imports. Keep HTTP behavior in `client.py` and tool orchestration in `server.py`. No formatter, linter, or type checker is configured; follow surrounding style.

## Testing Guidelines

Use pytest with `test_*.py` files and descriptive `test_<behavior>` functions. Reuse `fake_client`, `monkeypatch`, and `tmp_path`; shared fixtures isolate `.env` loading and SQLite queues. Cover changed behavior and reachable failures, including version conflicts and duplicate execution. Run focused tests first; run the full suite when shared contracts change. No numeric coverage threshold is configured.

## Commit & Pull Request Guidelines

History includes unscoped (`docs: ...`) and scoped (`fix(config): ...`) messages. For new commits, use `type(scope): summary`, for example `fix(queue): prevent duplicate execution`. Keep changes focused. PRs should describe behavior, link relevant issues, and report validation commands and results. Include screenshots for approval UI changes.

## Security & Configuration

Use the source project root's `.env` for Confluence settings and PAT, based on `.env.example`. Process environment variables do not supply these settings. The PAT is plaintext in `.env`: never read or output the user's token, and never commit credentials, private page content, or runtime queue/audit files. Preserve `dry_run=true` defaults, version checks, and human approval: `dry_run=false` only queues writes. Agents must not bypass interactive review.
