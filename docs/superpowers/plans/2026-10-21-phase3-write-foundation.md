# Phase 3: 写能力基座（转换器、护栏、create_page、add_comment） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 建立安全的写能力基座：Markdown→storage 转换器、写开关/空间白名单/审计日志，以及风险最低的两个写工具 `create_page` 与 `add_comment`。

**Architecture:** 转换器复用 `markdown` 库生成 XHTML，只把 `<pre><code>` 后处理成 Confluence `code` 宏；护栏集中在 `writes.py`；写工具保持普通 Python 函数，通过 `register_write_tools()` 只在 `CONFLUENCE_ENABLE_WRITES=true` 时注册到 FastMCP。

**Tech Stack:** Python 3.10+、FastMCP（`mcp==1.30.0`）、httpx、markdownify、`markdown>=3.7,<4`、pytest。

**Spec:** `docs/tool-roadmap-v0.2.md`（写工具 #9、#10 与“写操作统一规则”）

## Global Constraints

- 先完成 Phase 1 与 Phase 2；本计划复用 `_validate_page_id`、`_convert_storage`、`_page_summary`、`ConfluenceAPIError.status_code`。
- 写工具默认不可见：环境变量 `CONFLUENCE_ENABLE_WRITES=true`（大小写不敏感，接受 `1` / `true` / `yes`）时才注册。
- 空间白名单：`CONFLUENCE_WRITE_SPACES=OPS,QA`；未设置或为空表示不限制。配置后只允许写列出的 space。
- 所有写工具默认 `dry_run=True`，返回将要发生的变更；只有 `dry_run=False` 才真正请求 Confluence。
- 不提供删除页面工具；不记录 PAT；审计日志不写页面正文。
- 新依赖只允许 `markdown>=3.7,<4`。
- 服务名改为 `confluence`，MCP Host 注册别名统一使用 `wiki-local-mcp`；发行包名改为 `confluence-mcp`，版本 `0.3.0`；**包目录 `confluence_mcp`、keyring service `confluence-readonly-mcp` 保持不变**（改 keyring service 会让已保存的 PAT 失效）。
- 不在代码里自动修改 `~/.claude.json` 或 `~/.codex/config.toml`；只在 README 给出新注册名。
- 测试不访问真实 Confluence。

## Review Focus

1. 代码块里出现 `]]>` 时必须拆成 `]]]]><![CDATA[>`，否则 storage 损坏。
2. Markdown 代码块必须变成 `code` 宏，而不是裸 `<pre><code>`，否则 Confluence 渲染为纯文本。
3. 写开关的值带空格、大小写混用时行为必须正确；关闭时 MCP 客户端看不到任何写工具。
4. 白名单为空时不应误拦截；白名单命中判断区分大小写的 space key。
5. 审计日志写入失败不能吞掉操作结果，也不能让已经成功的写请求变成报错——写 stderr 后继续。
6. 同空间同标题已存在时必须报错并返回已有页面链接，不能创建重复页面。
7. 父页面与目标空间不一致时必须拒绝。
8. 403 必须转成包含“权限/白名单”提示的可读错误，而不是裸 HTTP 码。

## File Structure

- Create `src/confluence_mcp/markdown_storage.py` — `markdown_to_storage`、`contains_macro`，纯函数。
- Create `src/confluence_mcp/writes.py` — 写开关、白名单、审计日志。
- Modify `src/confluence_mcp/client.py` — `_request_json` 重构、`create_content`。
- Modify `src/confluence_mcp/server.py` — `create_page`、`add_comment`、`register_write_tools`。
- Modify `pyproject.toml` — `markdown` 依赖、包名、版本。
- Modify `tests/conftest.py` — `create_content`、`create_response`、`created`。
- Create `tests/test_markdown_storage.py`、`tests/test_writes.py`、`tests/test_create_page.py`、`tests/test_add_comment.py`、`tests/test_registration.py`。
- Modify `README.md`。

---

### Task 1: Markdown→storage 转换器

**Files:**
- Modify: `pyproject.toml`
- Create: `src/confluence_mcp/markdown_storage.py`
- Create: `tests/test_markdown_storage.py`

**Interfaces:**
- Produces:
  - `markdown_to_storage(markdown_text: str) -> str`。
  - `contains_macro(storage: str) -> bool`。

- [ ] **Step 1: 添加依赖**

`pyproject.toml` 的 `dependencies` 追加 `"markdown>=3.7,<4"`，运行 `uv sync`。

- [ ] **Step 2: 写失败测试 `tests/test_markdown_storage.py`**

```python
from confluence_mcp.markdown_storage import contains_macro, markdown_to_storage


def test_headings_lists_links_and_emphasis_become_html():
    storage = markdown_to_storage(
        "## Setup\n\n- one\n- two\n\n**bold** and *italic* [docs](https://x)"
    )

    assert "<h2>Setup</h2>" in storage
    assert "<li>one</li>" in storage
    assert "<strong>bold</strong>" in storage
    assert "<em>italic</em>" in storage
    assert '<a href="https://x">docs</a>' in storage


def test_table_becomes_html_table():
    storage = markdown_to_storage("| a | b |\n|---|---|\n| 1 | 2 |")

    assert "<table>" in storage
    assert "<td>1</td>" in storage


def test_fenced_code_becomes_confluence_code_macro():
    storage = markdown_to_storage("```python\nprint(1)\n```")

    assert '<ac:structured-macro ac:name="code">' in storage
    assert '<ac:parameter ac:name="language">python</ac:parameter>' in storage
    assert "<![CDATA[print(1)" in storage


def test_fence_without_language_still_becomes_code_macro():
    storage = markdown_to_storage("```\nplain\n```")

    assert '<ac:structured-macro ac:name="code">' in storage
    assert "ac:parameter" not in storage


def test_cdata_terminator_is_split():
    storage = markdown_to_storage("```\na ]]> b\n```")

    assert "a ]]]]><![CDATA[> b" in storage


def test_contains_macro_detects_structured_macros():
    assert contains_macro('<ac:structured-macro ac:name="toc"/>') is True
    assert contains_macro("<p>plain</p>") is False
```

- [ ] **Step 3: 运行测试，确认失败**

```powershell
uv run pytest tests/test_markdown_storage.py -v
```

Expected: FAIL，`ModuleNotFoundError: No module named 'confluence_mcp.markdown_storage'`。

- [ ] **Step 4: 实现 `src/confluence_mcp/markdown_storage.py`**

```python
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
```

- [ ] **Step 5: 运行测试，确认通过**

```powershell
uv run pytest tests/test_markdown_storage.py -v
```

Expected: 6 passed。

- [ ] **Step 6: 提交**

```powershell
git add pyproject.toml uv.lock src/confluence_mcp/markdown_storage.py tests/test_markdown_storage.py
git commit -m "feat: convert markdown to confluence storage" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 写开关、空间白名单与审计日志

**Files:**
- Create: `src/confluence_mcp/writes.py`
- Create: `tests/test_writes.py`

**Interfaces:**
- Consumes: `ConfluenceConfigurationError`（`client.py`）。
- Produces:
  - `writes_enabled() -> bool`。
  - `ensure_write_allowed(space_key: str | None) -> None`；关闭或不在白名单时抛 `ConfluenceConfigurationError`。
  - `audit_write(action: str, *, page_id: str, space_key: str | None, version_before: int | None, version_after: int | None, result: str) -> None`。
  - 模块常量 `WRITE_FLAG = "CONFLUENCE_ENABLE_WRITES"`、`WRITE_SPACES = "CONFLUENCE_WRITE_SPACES"`、`AUDIT_PATH`（默认 `~/.confluence-mcp/audit.log`）。

- [ ] **Step 1: 写失败测试 `tests/test_writes.py`**

```python
import json

import pytest

from confluence_mcp import writes
from confluence_mcp.client import ConfluenceConfigurationError


@pytest.mark.parametrize("value", ["true", "TRUE", "1", "yes", " true "])
def test_writes_enabled_accepts_truthy_values(monkeypatch, value):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", value)

    assert writes.writes_enabled() is True


@pytest.mark.parametrize("value", ["", "false", "0", "no"])
def test_writes_enabled_rejects_falsy_values(monkeypatch, value):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", value)

    assert writes.writes_enabled() is False


def test_ensure_write_allowed_rejects_when_disabled(monkeypatch):
    monkeypatch.delenv("CONFLUENCE_ENABLE_WRITES", raising=False)

    with pytest.raises(ConfluenceConfigurationError, match="CONFLUENCE_ENABLE_WRITES"):
        writes.ensure_write_allowed("OPS")


def test_whitelist_allows_listed_space(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "OPS, QA")

    writes.ensure_write_allowed("OPS")
    writes.ensure_write_allowed("QA")


def test_whitelist_rejects_unlisted_space(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "OPS,QA")

    with pytest.raises(ConfluenceConfigurationError, match="not in CONFLUENCE_WRITE_SPACES"):
        writes.ensure_write_allowed("DEV")


def test_whitelist_is_case_sensitive(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "OPS")

    with pytest.raises(ConfluenceConfigurationError):
        writes.ensure_write_allowed("ops")


def test_empty_whitelist_allows_every_space(monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "  ,  ")

    writes.ensure_write_allowed("ANY")


def test_audit_write_appends_one_json_line(monkeypatch, tmp_path):
    log = tmp_path / "audit.log"
    monkeypatch.setattr(writes, "AUDIT_PATH", log)

    writes.audit_write(
        "create_page",
        page_id="42",
        space_key="OPS",
        version_before=None,
        version_after=1,
        result="created",
    )

    record = json.loads(log.read_text(encoding="utf-8").strip())
    assert record["action"] == "create_page"
    assert record["page_id"] == "42"
    assert record["space_key"] == "OPS"
    assert record["version_before"] is None
    assert record["version_after"] == 1
    assert record["result"] == "created"
    assert record["ts"]


def test_audit_write_never_raises(monkeypatch, tmp_path):
    blocker = tmp_path / "audit.log"
    blocker.mkdir()
    monkeypatch.setattr(writes, "AUDIT_PATH", blocker)

    writes.audit_write(
        "add_comment",
        page_id="42",
        space_key="OPS",
        version_before=None,
        version_after=None,
        result="created",
    )
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
uv run pytest tests/test_writes.py -v
```

Expected: FAIL，`ModuleNotFoundError: No module named 'confluence_mcp.writes'`。

- [ ] **Step 3: 实现 `src/confluence_mcp/writes.py`**

```python
"""Guardrails for Confluence write operations."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .client import ConfluenceConfigurationError

WRITE_FLAG = "CONFLUENCE_ENABLE_WRITES"
WRITE_SPACES = "CONFLUENCE_WRITE_SPACES"
AUDIT_PATH = Path.home() / ".confluence-mcp" / "audit.log"


def writes_enabled() -> bool:
    return os.environ.get(WRITE_FLAG, "").strip().lower() in {"1", "true", "yes"}


def ensure_write_allowed(space_key: str | None) -> None:
    if not writes_enabled():
        raise ConfluenceConfigurationError(
            f"Writes are disabled. Set {WRITE_FLAG}=true to enable write tools."
        )
    allowed = {item.strip() for item in os.environ.get(WRITE_SPACES, "").split(",") if item.strip()}
    if allowed and space_key not in allowed:
        raise ConfluenceConfigurationError(
            f'Space "{space_key}" is not in {WRITE_SPACES}. Allowed spaces: {", ".join(sorted(allowed))}.'
        )


def audit_write(
    action: str,
    *,
    page_id: str,
    space_key: str | None,
    version_before: int | None,
    version_after: int | None,
    result: str,
) -> None:
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "action": action,
        "page_id": page_id,
        "space_key": space_key,
        "version_before": version_before,
        "version_after": version_after,
        "result": result,
    }
    try:
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with AUDIT_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError as exc:
        # Losing the audit line must not turn a successful write into a failure.
        print(f"confluence-mcp: could not write audit log: {exc}", file=sys.stderr)
```

- [ ] **Step 4: 运行测试，确认通过**

```powershell
uv run pytest tests/test_writes.py -v
```

Expected: 10 passed。

- [ ] **Step 5: 提交**

```powershell
git add src/confluence_mcp/writes.py tests/test_writes.py
git commit -m "feat: add write switch, space whitelist, and audit log" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: `create_page`

**Files:**
- Modify: `src/confluence_mcp/client.py`
- Modify: `src/confluence_mcp/server.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_create_page.py`

**Interfaces:**
- Consumes: `markdown_to_storage`、`ensure_write_allowed`、`audit_write`。
- Produces:
  - `ConfluenceClient._request_json(method, path, *, params=None, json_body=None) -> dict[str, Any]`；`_get_json` 改为调用它。
  - `ConfluenceClient.create_content(payload: dict[str, Any]) -> dict[str, Any]`。
  - 工具 `create_page(space_key: str, title: str, content_markdown: str, parent_page_id: str | None = None, dry_run: bool = True) -> dict[str, Any]`。

- [ ] **Step 1: 扩展 `tests/conftest.py`**

```python
        self.created = []
        self.create_response = {}
```

```python
    def create_content(self, payload):
        self.created.append(payload)
        return self.create_response
```

- [ ] **Step 2: 写失败测试 `tests/test_create_page.py`**

```python
import pytest

from confluence_mcp import server, writes
from confluence_mcp.client import ConfluenceAPIError, ConfluenceConfigurationError


def test_create_page_dry_run_previews_without_posting(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)

    result = server.create_page("OPS", "Release", "## Notes\n\nhello", dry_run=True)

    assert result["dry_run"] is True
    assert result["target"] == {"space_key": "OPS", "title": "Release", "parent_page_id": None}
    assert "<h2>Notes</h2>" in result["storage_preview"]
    assert fake_client.created == []


def test_create_page_rejects_existing_title(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.search_response = {
        "results": [
            {
                "id": "7",
                "title": "Release",
                "space": {"key": "OPS"},
                "_links": {"webui": "/spaces/OPS/pages/7"},
            }
        ]
    }

    with pytest.raises(ConfluenceAPIError, match="already exists") as excinfo:
        server.create_page("OPS", "Release", "x", dry_run=True)

    assert "https://wiki.example.com/pages/7" in str(excinfo.value)


def test_create_page_rejects_parent_in_another_space(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["5"] = {"id": "5", "title": "Parent", "space": {"key": "QA"}}

    with pytest.raises(ValueError, match="different space"):
        server.create_page("OPS", "Release", "x", parent_page_id="5")


def test_create_page_respects_whitelist(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "QA")

    with pytest.raises(ConfluenceConfigurationError):
        server.create_page("OPS", "Release", "x")


def test_create_page_posts_and_audits(fake_client, monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")
    fake_client.create_response = {
        "id": "77",
        "title": "Release",
        "space": {"key": "OPS"},
        "version": {"number": 1},
        "_links": {"webui": "/spaces/OPS/pages/77"},
    }

    result = server.create_page("OPS", "Release", "hello", dry_run=False)

    payload = fake_client.created[0]
    assert payload["type"] == "page"
    assert payload["title"] == "Release"
    assert payload["space"] == {"key": "OPS"}
    assert payload["body"]["storage"]["representation"] == "storage"
    assert result["page_id"] == "77"
    assert result["version"] == 1
    assert "create_page" in (tmp_path / "audit.log").read_text(encoding="utf-8")
```

- [ ] **Step 3: 运行测试，确认失败**

```powershell
uv run pytest tests/test_create_page.py -v
```

Expected: FAIL，`AttributeError: ... has no attribute 'create_page'`。

- [ ] **Step 4: 重构 `client.py` 并添加 `create_content`**

把 `_get_json` 改为：

```python
    def _get_json(self, path: str, *, params: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("GET", path, params=params)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        try:
            response = self._client.request(method, path, params=params, json=json_body)
        except httpx.TimeoutException as exc:
            raise ConfluenceAPIError("The Confluence request timed out.") from exc
        except httpx.ConnectError as exc:
            raise ConfluenceAPIError(
                "Could not connect to Confluence. Check the URL, network/VPN, and TLS CA settings."
            ) from exc
        # ... 其余状态码处理保持原样，403 文案改为同时提到读取权限与写白名单 ...
```

403 文案：

```python
        if response.status_code == 403:
            raise ConfluenceAPIError(
                "Confluence returned 403: the account lacks permission for this operation. "
                "For writes, also check CONFLUENCE_WRITE_SPACES and the space's edit restrictions.",
                status_code=403,
            )
```

新增：

```python
    def create_content(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._request_json("POST", "content", json_body=payload)
```

删除 `client.py` 顶部 “deliberately GET-only” 与 “only HTTP operation” 两处注释。

- [ ] **Step 5: 在 `server.py` 实现 `create_page`**

```python
@mcp.tool()
def create_page(
    space_key: str,
    title: str,
    content_markdown: str,
    parent_page_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Create a page from Markdown. Defaults to a dry run that posts nothing."""
    space_key = space_key.strip()
    title = title.strip()
    if not space_key:
        raise ValueError("space_key must not be empty.")
    if not title:
        raise ValueError("title must not be empty.")
    if not content_markdown.strip():
        raise ValueError("content_markdown must not be empty.")
    ensure_write_allowed(space_key)

    client = get_client()
    cql = (
        f'type = page AND space = "{quote_cql(space_key)}" '
        f'AND title = "{quote_cql(title)}"'
    )
    existing = client.search_pages(cql, 5)
    if existing:
        raise ConfluenceAPIError(
            f'A page titled "{title}" already exists in space {space_key}: '
            f"{_page_summary(existing[0], client)['url']}"
        )

    ancestors = None
    if parent_page_id is not None:
        if not parent_page_id.isdigit():
            raise ValueError("parent_page_id must contain only digits.")
        parent = client.get_page(parent_page_id)
        parent_space = (parent.get("space") or {}).get("key")
        if parent_space != space_key:
            raise ValueError(
                f"Parent page {parent_page_id} is in a different space ({parent_space})."
            )
        ancestors = [{"id": parent_page_id}]

    storage = markdown_to_storage(content_markdown)
    target = {"space_key": space_key, "title": title, "parent_page_id": parent_page_id}
    if dry_run:
        return {
            "dry_run": True,
            "action": "create_page",
            "target": target,
            "storage_preview": storage[:4000],
        }

    payload: dict[str, Any] = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {"storage": {"representation": "storage", "value": storage}},
    }
    if ancestors:
        payload["ancestors"] = ancestors
    created = client.create_content(payload)
    audit_write(
        "create_page",
        page_id=str(created.get("id", "")),
        space_key=space_key,
        version_before=None,
        version_after=(created.get("version") or {}).get("number"),
        result="created",
    )
    return {
        "dry_run": False,
        **_page_summary(created, client),
    }
```

导入：`from .markdown_storage import markdown_to_storage`、`from .writes import audit_write, ensure_write_allowed`。

- [ ] **Step 6: 运行测试，确认通过**

```powershell
uv run pytest tests/test_create_page.py -v
```

Expected: 5 passed。

- [ ] **Step 7: 提交**

```powershell
git add src/confluence_mcp/client.py src/confluence_mcp/server.py tests/conftest.py tests/test_create_page.py
git commit -m "feat: add create_page tool with dry run" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: `add_comment`

**Files:**
- Modify: `src/confluence_mcp/server.py`
- Modify: `tests/test_add_comment.py`（新建）

**Interfaces:**
- Consumes: `get_comments` 的页面读取路径、`ensure_write_allowed`、`markdown_to_storage`。
- Produces: 工具 `add_comment(page_id: str, content_markdown: str, parent_comment_id: str | None = None, dry_run: bool = True) -> dict[str, Any]`。

- [ ] **Step 1: 写失败测试 `tests/test_add_comment.py`**

```python
import pytest

from confluence_mcp import server, writes

PAGE = {
    "id": "42",
    "title": "Guide",
    "space": {"key": "OPS"},
    "version": {"number": 3},
    "_links": {"webui": "/spaces/OPS/pages/42"},
    "body": {"storage": {"value": "<p>x</p>"}},
}


def test_add_comment_dry_run_previews_without_posting(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)
    fake_client.pages["42"] = PAGE

    result = server.add_comment("42", "looks good", dry_run=True)

    assert result["dry_run"] is True
    assert result["target"] == {"page_id": "42", "parent_comment_id": None}
    assert result["storage_preview"] == "<p>looks good</p>"
    assert fake_client.created == []


def test_add_comment_posts_comment_container(fake_client, monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")
    fake_client.pages["42"] = PAGE
    fake_client.create_response = {"id": "100", "_links": {"webui": "/spaces/OPS/pages/42#comment-100"}}

    result = server.add_comment("42", "reply", parent_comment_id="99", dry_run=False)

    payload = fake_client.created[0]
    assert payload["type"] == "comment"
    assert payload["container"] == {"id": "42", "type": "page"}
    assert payload["ancestors"] == [{"id": "99"}]
    assert result["comment_id"] == "100"
    assert "add_comment" in (tmp_path / "audit.log").read_text(encoding="utf-8")


def test_add_comment_respects_whitelist(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "QA")
    fake_client.pages["42"] = PAGE

    from confluence_mcp.client import ConfluenceConfigurationError

    with pytest.raises(ConfluenceConfigurationError):
        server.add_comment("42", "x")


def test_add_comment_rejects_bad_parent_id(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = PAGE

    with pytest.raises(ValueError):
        server.add_comment("42", "x", parent_comment_id="abc")
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
uv run pytest tests/test_add_comment.py -v
```

Expected: FAIL，`AttributeError: ... has no attribute 'add_comment'`。

- [ ] **Step 3: 实现 `add_comment`**

```python
@mcp.tool()
def add_comment(
    page_id: str,
    content_markdown: str,
    parent_comment_id: str | None = None,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Add a page comment from Markdown. Defaults to a dry run that posts nothing."""
    if not content_markdown.strip():
        raise ValueError("content_markdown must not be empty.")
    if parent_comment_id is not None and not parent_comment_id.isdigit():
        raise ValueError("parent_comment_id must contain only digits.")

    client = get_client()
    page = client.get_page(page_id)
    space_key = (page.get("space") or {}).get("key")
    ensure_write_allowed(space_key)

    storage = markdown_to_storage(content_markdown)
    if dry_run:
        return {
            "dry_run": True,
            "action": "add_comment",
            "target": {"page_id": page_id, "parent_comment_id": parent_comment_id},
            "storage_preview": storage[:4000],
        }

    payload: dict[str, Any] = {
        "type": "comment",
        "container": {"id": page_id, "type": "page"},
        "body": {"storage": {"representation": "storage", "value": storage}},
    }
    if parent_comment_id is not None:
        payload["ancestors"] = [{"id": parent_comment_id}]
    created = client.create_content(payload)
    audit_write(
        "add_comment",
        page_id=page_id,
        space_key=space_key,
        version_before=None,
        version_after=None,
        result="created",
    )
    return {
        "dry_run": False,
        "comment_id": str(created.get("id", "")),
        "page_id": page_id,
        "url": client.page_url(created),
    }
```

`ancestors` 用于回复评论在 8.5 上的行为需实测；若服务器要求 `container` 指向父评论，改为 `{"id": parent_comment_id, "type": "comment"}` 并在 README 记录结论。

- [ ] **Step 4: 运行测试，确认通过**

```powershell
uv run pytest tests/test_add_comment.py -v
```

Expected: 4 passed。

- [ ] **Step 5: 提交**

```powershell
git add src/confluence_mcp/server.py tests/test_add_comment.py
git commit -m "feat: add add_comment tool with dry run" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: 条件注册、改名与文档

**Files:**
- Modify: `src/confluence_mcp/server.py`
- Modify: `pyproject.toml`
- Create: `tests/test_registration.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `writes_enabled()`。
- Produces: `register_write_tools(server: FastMCP) -> None`；模块导入时仅在 `writes_enabled()` 为真时调用。FastMCP 名称 `confluence`。

- [ ] **Step 1: 写失败测试 `tests/test_registration.py`**

```python
import asyncio
import importlib

from confluence_mcp import server


def _registered_tool_names(monkeypatch, value):
    if value is None:
        monkeypatch.delenv("CONFLUENCE_ENABLE_WRITES", raising=False)
    else:
        monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", value)
    module = importlib.reload(server)
    return {tool.name for tool in asyncio.run(module.mcp.list_tools())}


def test_write_tools_are_hidden_by_default(monkeypatch):
    names = _registered_tool_names(monkeypatch, None)

    assert "create_page" not in names
    assert "add_comment" not in names
    assert {"search_pages", "get_page", "cql_search"} <= names


def test_write_tools_appear_when_enabled(monkeypatch):
    names = _registered_tool_names(monkeypatch, "true")

    assert {"create_page", "add_comment"} <= names
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
uv run pytest tests/test_registration.py -v
```

Expected: FAIL，启用时 `create_page` 不在工具列表中（当前所有函数都用 `@mcp.tool()` 装饰）。

- [ ] **Step 3: 改造注册方式**

把 `create_page`、`add_comment` 上的 `@mcp.tool()` 去掉，函数体保持不变。在文件末尾 `main()` 之前加：

```python
def register_write_tools(server: FastMCP) -> None:
    for tool in (create_page, add_comment):
        server.tool()(tool)


if writes_enabled():
    register_write_tools(mcp)
```

`mcp = FastMCP("confluence")`。

导入：`from .writes import ..., writes_enabled`。

注意：Phase 4 的 `update_page` / `update_page_section` 也要加进 `register_write_tools` 的元组。

- [ ] **Step 4: 更新 `pyproject.toml`**

```toml
name = "confluence-mcp"
version = "0.3.0"
description = "MCP server for on-premises Atlassian Confluence Data Center"
```

`[project.scripts]` 保持 `confluence-mcp = "confluence_mcp.server:main"` 不变。

- [ ] **Step 5: 运行测试，确认通过**

```powershell
uv run pytest tests/test_registration.py -v
uv run pytest -v
```

Expected: 2 passed；全量通过。

- [ ] **Step 6: 更新 README**

必须改到的位置：

1. 标题与首段：去掉“只读”；说明默认仍只注册读工具，写工具需显式开启。
2. “能力”一节：加入 `create_page`、`add_comment`，标注“默认 dry_run”。
3. 新小节“启用写操作”：

```markdown
## 启用写操作（可选）

默认情况下服务器不注册任何写工具。启用方式是在 MCP 配置的 `env` 中加入：

```toml
CONFLUENCE_ENABLE_WRITES = "true"
CONFLUENCE_WRITE_SPACES = "OPS,QA"   # 可选；不设置表示不限制空间
```

所有写工具默认 `dry_run=true`：只返回将要发生的变更（目标、storage 预览），
调用方确认后再传 `dry_run=false`。真实写入会追加到
`%USERPROFILE%\.confluence-mcp\audit.log`（JSON Lines，不含页面正文和 PAT）。
```

4. “注册到 Codex Desktop”一节使用 `[mcp_servers.wiki-local-mcp]` 及匹配的 `[mcp_servers.wiki-local-mcp.env]`，Claude Code 配置使用同名 key（只改 key，不改命令）。
5. “官方接口依据”上方补一句：写工具需要 PAT 对应账号在目标 space 有编辑权限。

- [ ] **Step 7: 同步本机 MCP 注册（手动，只改 key）**

这一步不改代码，检查当前服务注册项是否使用 `wiki-local-mcp`：

```powershell
Select-String -LiteralPath "$env:USERPROFILE\.codex\config.toml" -SimpleMatch "wiki-local-mcp"
Select-String -LiteralPath "$env:USERPROFILE\.claude.json" -SimpleMatch "wiki-local-mcp"
```

Codex 的服务段及其 env 子段、Claude Code 中对应服务的 JSON key 均使用 `wiki-local-mcp`；更名时保留命令、参数、cwd、env。改完后重启 MCP host，确认工具列表里出现读工具；只有在 env 里设置了 `CONFLUENCE_ENABLE_WRITES=true` 时才应出现写工具。

- [ ] **Step 8: 提交**

```powershell
git add src/confluence_mcp/server.py pyproject.toml uv.lock tests/test_registration.py README.md
git commit -m "feat: gate write tools behind an explicit switch" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```
