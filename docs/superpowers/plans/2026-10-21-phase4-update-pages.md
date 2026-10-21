# Phase 4: 页面更新（整页与单节） Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `update_page` 与 `update_page_section`，带版本冲突保护、宏丢失保护和 `dry_run`；单节更新只替换目标章节，页面其余 storage 原样保留。

**Architecture:** 整页更新复用 `markdown_to_storage`；单节更新在 `outline.py` 里定位标题后只拼接正文，不经过整页 Markdown 往返。两个工具都先读当前页、校验 `expected_version` 与空间白名单，再决定 dry-run 返回 diff 或 `PUT`。

**Tech Stack:** Python 3.10+、FastMCP（`mcp==1.30.0`）、httpx、markdown、pytest。

**Spec:** `docs/tool-roadmap-v0.2.md`（写工具 #7、#8 与“写操作统一规则”）

## Global Constraints

- 先完成 Phase 3；本计划复用 `register_write_tools`、`ensure_write_allowed`、`audit_write`、`markdown_to_storage`、`contains_macro`、`_unified_diff`。
- 所有修改必须传 `expected_version`；与当前版本不一致直接报冲突，不自动覆盖。
- `update_page` 在 `content_format="markdown"` 且原页面含 `<ac:structured-macro` 时默认拒绝，只有显式 `force=True` 才允许。
- `version.message` 固定为 `[MCP] <change_message>`；`change_message` 为空时为 `[MCP]`。
- 精确签名：
  - `update_page(page_id: str, expected_version: int, content: str, title: str | None = None, content_format: Literal["markdown", "storage"] = "markdown", dry_run: bool = True, force: bool = False, change_message: str = "", max_chars: int = 4000)`
  - `update_page_section(page_id: str, section_title: str, new_content_markdown: str, expected_version: int, dry_run: bool = True, change_message: str = "", max_chars: int = 4000)`
- 不提供删除页面工具。
- 测试不访问真实 Confluence；409 竞态只能在手动冒烟里验证。

## Review Focus

1. `expected_version` 过期时必须报出当前版本号并停止，不能覆盖别人的修改。
2. 含宏页面用 Markdown 整页覆盖必须被拒绝；`force=True` 才放行。
3. 单节替换不得触碰章节外的任何 storage 字节（宏、其他章节必须原样保留）。
4. 新内容里出现同级或更高级标题时必须拒绝，否则章节边界会被破坏。
5. 章节正文里出现 `<h2>` 的代码宏文本不能被当成标题（依赖 Phase 1 的 CDATA 遮罩）。
6. 空字符串内容用于清空某一节时必须允许；整页更新传空内容应拒绝。
7. 并发更新触发 HTTP 409 时必须提示重新读取版本，而不是笼统的 HTTP 错误。

## File Structure

- Modify `src/confluence_mcp/client.py` — `update_page`、409 映射。
- Modify `src/confluence_mcp/outline.py` — `replace_section`。
- Modify `src/confluence_mcp/server.py` — 两个新工具、注册。
- Modify `tests/conftest.py` — `update_page`、`updated`、`update_response`。
- Modify `tests/test_outline.py` — `replace_section` 测试。
- Create `tests/test_update_page.py`、`tests/test_update_page_section.py`。
- Modify `README.md`、`pyproject.toml`。

---

### Task 1: `update_page`（整页更新）

**Files:**
- Modify: `src/confluence_mcp/client.py`
- Modify: `src/confluence_mcp/server.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_update_page.py`

**Interfaces:**
- Consumes: `_request_json`（Phase 3）、`markdown_to_storage`、`contains_macro`、`ensure_write_allowed`、`audit_write`、`_unified_diff`（Phase 2）、`_storage`（Phase 2）。
- Produces:
  - `ConfluenceClient.update_page(self, page_id: str, payload: dict[str, Any]) -> dict[str, Any]`。
  - 工具 `update_page(...)`，签名见 Global Constraints；dry-run 返回 `{"dry_run": True, "page_id", "title", "version_before", "version_after", "diff", "truncated", "storage_preview"}`，真实写入返回 `{"dry_run": False, **_page_summary(...)}`。

- [ ] **Step 1: 扩展 `tests/conftest.py`**

```python
        self.updated = []
        self.update_response = {}
```

```python
    def update_page(self, page_id, payload):
        self.updated.append(payload)
        return self.update_response
```

- [ ] **Step 2: 写失败测试 `tests/test_update_page.py`**

```python
import pytest

from confluence_mcp import server, writes
from confluence_mcp.client import ConfluenceAPIError


def page(version=3, storage="<p>old</p>"):
    return {
        "id": "42",
        "title": "Guide",
        "space": {"key": "OPS"},
        "version": {"number": version},
        "_links": {"webui": "/spaces/OPS/pages/42"},
        "body": {"storage": {"value": storage}},
    }


def test_update_page_dry_run_diffs_without_putting(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    result = server.update_page("42", expected_version=3, content="new", dry_run=True)

    assert result["dry_run"] is True
    assert result["version_before"] == 3
    assert result["version_after"] == 4
    assert "-old" in result["diff"]
    assert "+new" in result["diff"]
    assert fake_client.updated == []


def test_update_page_rejects_stale_expected_version(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(version=4)

    with pytest.raises(ConfluenceAPIError, match="current version is 4"):
        server.update_page("42", expected_version=3, content="new")


def test_update_page_rejects_markdown_on_macro_page(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(storage='<ac:structured-macro ac:name="toc"/><p>old</p>')

    with pytest.raises(ConfluenceAPIError, match="update_page_section"):
        server.update_page("42", expected_version=3, content="new")


def test_update_page_force_allows_markdown_on_macro_page(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(storage='<ac:structured-macro ac:name="toc"/><p>old</p>')

    result = server.update_page("42", expected_version=3, content="new", dry_run=True, force=True)

    assert result["dry_run"] is True


def test_update_page_accepts_storage_format(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    result = server.update_page(
        "42",
        expected_version=3,
        content="<p>raw</p>",
        content_format="storage",
        dry_run=True,
    )

    assert "+raw" in result["diff"]


def test_update_page_posts_new_version_and_audits(fake_client, monkeypatch, tmp_path):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")
    fake_client.pages["42"] = page()
    fake_client.update_response = page(version=4, storage="<p>new</p>")

    result = server.update_page(
        "42",
        expected_version=3,
        content="new",
        dry_run=False,
        change_message="sync docs",
    )

    payload = fake_client.updated[0]
    assert payload["version"] == {"number": 4, "message": "[MCP] sync docs"}
    assert payload["body"]["storage"] == {"representation": "storage", "value": "<p>new</p>"}
    assert result["dry_run"] is False
    assert result["version"] == 4
    assert "update_page" in (tmp_path / "audit.log").read_text(encoding="utf-8")


def test_update_page_keeps_title_when_not_provided(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()
    fake_client.update_response = page(version=4)

    server.update_page("42", expected_version=3, content="new", dry_run=False)

    assert fake_client.updated[0]["title"] == "Guide"


def test_update_page_rejects_empty_content(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="content"):
        server.update_page("42", expected_version=3, content="   ")
```

- [ ] **Step 3: 运行测试，确认失败**

```powershell
uv run pytest tests/test_update_page.py -v
```

Expected: FAIL，`AttributeError: ... has no attribute 'update_page'`。

- [ ] **Step 4: 修改 `client.py`**

在 `_request_json` 的 `is_error` 分支前加：

```python
        if response.status_code == 409:
            raise ConfluenceAPIError(
                "Confluence rejected the update because the page version changed (HTTP 409). "
                "Re-read the page and retry with the current version.",
                status_code=409,
            )
```

新方法：

```python
    def update_page(self, page_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._validate_page_id(page_id)
        return self._request_json("PUT", f"content/{page_id}", json_body=payload)
```

- [ ] **Step 5: 在 `server.py` 实现 `update_page`**

```python
@mcp.tool()
def update_page(
    page_id: str,
    expected_version: int,
    content: str,
    title: str | None = None,
    content_format: Literal["markdown", "storage"] = "markdown",
    dry_run: bool = True,
    force: bool = False,
    change_message: str = "",
    max_chars: int = 4000,
) -> dict[str, Any]:
    """Replace a page body, guarded by an expected version. Defaults to a dry run."""
    if expected_version < 1:
        raise ValueError("expected_version must be at least 1.")
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1.")
    if content_format not in {"markdown", "storage"}:
        raise ValueError('content_format must be "markdown" or "storage".')
    if content_format == "markdown" and not content.strip():
        raise ValueError("content must not be empty when content_format is markdown.")

    client = get_client()
    page = client.get_page(page_id)
    space_key = (page.get("space") or {}).get("key")
    ensure_write_allowed(space_key)

    current = (page.get("version") or {}).get("number")
    if current != expected_version:
        raise ConfluenceAPIError(
            f"Version conflict: current version is {current}, expected_version was {expected_version}. "
            "Re-read the page and retry."
        )

    old_storage = _storage(page)
    if content_format == "markdown":
        if contains_macro(old_storage) and not force:
            raise ConfluenceAPIError(
                "This page contains Confluence macros; replacing it with Markdown would drop them. "
                'Use update_page_section, content_format="storage", or force=True.'
            )
        new_storage = markdown_to_storage(content)
    else:
        new_storage = content

    new_title = title.strip() if title else page.get("title", "")
    if not new_title:
        raise ValueError("title must not be empty.")

    diff = _unified_diff(
        storage_to_markdown(old_storage),
        storage_to_markdown(new_storage),
        f"v{current}",
        f"v{current + 1}",
    )
    if dry_run:
        return {
            "dry_run": True,
            "page_id": page_id,
            "title": new_title,
            "version_before": current,
            "version_after": current + 1,
            "diff": diff[:max_chars],
            "truncated": len(diff) > max_chars,
            "storage_preview": new_storage[:max_chars],
        }

    payload = {
        "id": page_id,
        "type": "page",
        "title": new_title,
        "version": {
            "number": current + 1,
            "message": f"[MCP] {change_message}".strip(),
        },
        "body": {"storage": {"representation": "storage", "value": new_storage}},
    }
    updated = client.update_page(page_id, payload)
    audit_write(
        "update_page",
        page_id=page_id,
        space_key=space_key,
        version_before=current,
        version_after=current + 1,
        result="updated",
    )
    return {"dry_run": False, **_page_summary(updated, client)}
```

`Literal` 已在 `server.py` 导入（`OutputFormat` 使用）。

- [ ] **Step 6: 运行测试，确认通过**

```powershell
uv run pytest tests/test_update_page.py -v
```

Expected: 8 passed。

- [ ] **Step 7: 提交**

```powershell
git add src/confluence_mcp/client.py src/confluence_mcp/server.py tests/conftest.py tests/test_update_page.py
git commit -m "feat: add update_page with version and macro guards" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: `replace_section` 章节替换

**Files:**
- Modify: `src/confluence_mcp/outline.py`
- Modify: `tests/test_outline.py`

**Interfaces:**
- Consumes: `extract_section`、`find_headings`（Phase 1）。
- Produces: `replace_section(storage: str, title: str, new_body_storage: str) -> str`；新正文含 `level <= 目标标题级别` 的标题时抛 `ValueError`。章节外的字节原样保留。

- [ ] **Step 1: 追加失败测试到 `tests/test_outline.py`**

```python
from confluence_mcp.outline import replace_section


def test_replace_section_keeps_heading_and_following_sections():
    storage = '<h2>Setup</h2><p>old</p><h2>Notes</h2><p>keep</p>'

    updated = replace_section(storage, "Setup", "<p>new</p>")

    assert updated == '<h2>Setup</h2><p>new</p><h2>Notes</h2><p>keep</p>'


def test_replace_section_preserves_macros_outside_the_section():
    storage = (
        '<h2>Setup</h2><p>old</p>'
        '<ac:structured-macro ac:name="toc"/>'
        '<h2>Notes</h2><p>keep</p>'
    )

    updated = replace_section(storage, "Setup", "<p>new</p>")

    assert '<ac:structured-macro ac:name="toc"/>' in updated
    assert updated.endswith("<h2>Notes</h2><p>keep</p>")


def test_replace_section_allows_clearing_the_body():
    storage = "<h2>Setup</h2><p>old</p>"

    assert replace_section(storage, "Setup", "") == "<h2>Setup</h2>"


def test_replace_section_rejects_same_level_heading_in_new_body():
    with pytest.raises(ValueError, match="level 2"):
        replace_section("<h2>Setup</h2><p>old</p>", "Setup", "<h2>Other</h2>")


def test_replace_section_allows_deeper_headings_in_new_body():
    storage = "<h2>Setup</h2><p>old</p>"

    updated = replace_section(storage, "Setup", "<h3>Step 1</h3><p>go</p>")

    assert updated == "<h2>Setup</h2><h3>Step 1</h3><p>go</p>"
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
uv run pytest tests/test_outline.py -v
```

Expected: FAIL，`ImportError: cannot import name 'replace_section'`。

- [ ] **Step 3: 在 `outline.py` 实现**

```python
def replace_section(storage: str, title: str, new_body_storage: str) -> str:
    heading, body = extract_section(storage, title)
    if any(item.level <= heading.level for item in find_headings(new_body_storage)):
        raise ValueError(
            f"New content must not contain headings at level {heading.level} or higher; "
            "it would break the section boundary."
        )
    return storage[: heading.end] + new_body_storage + storage[heading.end + len(body) :]
```

- [ ] **Step 4: 运行测试，确认通过**

```powershell
uv run pytest tests/test_outline.py -v
```

Expected: 12 passed。

- [ ] **Step 5: 提交**

```powershell
git add src/confluence_mcp/outline.py tests/test_outline.py
git commit -m "feat: add section replacement that preserves surrounding storage" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: `update_page_section`

**Files:**
- Modify: `src/confluence_mcp/server.py`
- Create: `tests/test_update_page_section.py`

**Interfaces:**
- Consumes: `extract_section`、`replace_section`、`markdown_to_storage`、`ensure_write_allowed`、`audit_write`、`_unified_diff`、`_storage`。
- Produces: 工具 `update_page_section(...)`，签名见 Global Constraints；dry-run 返回 `{"dry_run": True, "page_id", "section_title", "version_before", "version_after", "diff", "truncated", "storage_preview"}`。

- [ ] **Step 1: 写失败测试 `tests/test_update_page_section.py`**

```python
import pytest

from confluence_mcp import server, writes
from confluence_mcp.client import ConfluenceAPIError


def page(version=5, storage="<h2>Setup</h2><p>old</p><h2>Notes</h2><p>keep</p>"):
    return {
        "id": "42",
        "title": "Guide",
        "space": {"key": "OPS"},
        "version": {"number": version},
        "_links": {"webui": "/spaces/OPS/pages/42"},
        "body": {"storage": {"value": storage}},
    }


def test_update_page_section_dry_run_diffs_only_the_section(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    result = server.update_page_section(
        "42", "Setup", "new body", expected_version=5, dry_run=True
    )

    assert result["dry_run"] is True
    assert "-old" in result["diff"]
    assert "+new body" in result["diff"]
    assert "Notes" not in result["diff"]
    assert fake_client.updated == []


def test_update_page_section_rejects_stale_expected_version(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(version=6)

    with pytest.raises(ConfluenceAPIError, match="current version is 6"):
        server.update_page_section("42", "Setup", "new", expected_version=5)


def test_update_page_section_rejects_same_level_heading(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="level 2"):
        server.update_page_section("42", "Setup", "## Other", expected_version=5)


def test_update_page_section_rejects_unknown_section(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page()

    with pytest.raises(ValueError, match="Available sections: Setup, Notes"):
        server.update_page_section("42", "Missing", "new", expected_version=5)


def test_update_page_section_preserves_other_sections_and_macros(
    fake_client, monkeypatch, tmp_path
):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setattr(writes, "AUDIT_PATH", tmp_path / "audit.log")
    fake_client.pages["42"] = page(
        storage=(
            '<h2>Setup</h2><p>old</p>'
            '<ac:structured-macro ac:name="toc"/>'
            '<h2>Notes</h2><p>keep</p>'
        )
    )
    fake_client.update_response = page(version=6)

    server.update_page_section("42", "Setup", "new body", expected_version=5, dry_run=False)

    payload = fake_client.updated[0]
    assert payload["version"] == {"number": 6, "message": "[MCP]"}
    assert payload["body"]["storage"]["value"] == (
        '<h2>Setup</h2><p>new body</p>'
        '<ac:structured-macro ac:name="toc"/>'
        '<h2>Notes</h2><p>keep</p>'
    )
    assert "update_page_section" in (tmp_path / "audit.log").read_text(encoding="utf-8")


def test_update_page_section_can_clear_the_body(fake_client, monkeypatch):
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    fake_client.pages["42"] = page(storage="<h2>Setup</h2><p>old</p>")
    fake_client.update_response = page(version=6)

    server.update_page_section("42", "Setup", "", expected_version=5, dry_run=False)

    assert fake_client.updated[0]["body"]["storage"]["value"] == "<h2>Setup</h2>"
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
uv run pytest tests/test_update_page_section.py -v
```

Expected: FAIL，`AttributeError: ... has no attribute 'update_page_section'`。

- [ ] **Step 3: 实现工具**

```python
@mcp.tool()
def update_page_section(
    page_id: str,
    section_title: str,
    new_content_markdown: str,
    expected_version: int,
    dry_run: bool = True,
    change_message: str = "",
    max_chars: int = 4000,
) -> dict[str, Any]:
    """Replace one heading section, preserving the rest of the page byte for byte."""
    section_title = section_title.strip()
    if not section_title:
        raise ValueError("section_title must not be empty.")
    if expected_version < 1:
        raise ValueError("expected_version must be at least 1.")
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1.")

    client = get_client()
    page = client.get_page(page_id)
    space_key = (page.get("space") or {}).get("key")
    ensure_write_allowed(space_key)

    current = (page.get("version") or {}).get("number")
    if current != expected_version:
        raise ConfluenceAPIError(
            f"Version conflict: current version is {current}, expected_version was {expected_version}. "
            "Re-read the page and retry."
        )

    old_storage = _storage(page)
    heading, body = extract_section(old_storage, section_title)
    new_body = markdown_to_storage(new_content_markdown)
    new_storage = replace_section(old_storage, section_title, new_body)

    old_section = old_storage[heading.start : heading.end] + body
    new_section = old_storage[heading.start : heading.end] + new_body
    diff = _unified_diff(
        storage_to_markdown(old_section),
        storage_to_markdown(new_section),
        f"v{current} {section_title}",
        f"v{current + 1} {section_title}",
    )
    if dry_run:
        return {
            "dry_run": True,
            "page_id": page_id,
            "section_title": heading.title,
            "version_before": current,
            "version_after": current + 1,
            "diff": diff[:max_chars],
            "truncated": len(diff) > max_chars,
            "storage_preview": new_section[:max_chars],
        }

    payload = {
        "id": page_id,
        "type": "page",
        "title": page.get("title", ""),
        "version": {
            "number": current + 1,
            "message": f"[MCP] {change_message}".strip(),
        },
        "body": {"storage": {"representation": "storage", "value": new_storage}},
    }
    updated = client.update_page(page_id, payload)
    audit_write(
        "update_page_section",
        page_id=page_id,
        space_key=space_key,
        version_before=current,
        version_after=current + 1,
        result="updated",
    )
    return {"dry_run": False, **_page_summary(updated, client)}
```

导入：`from .outline import extract_section, find_headings, replace_section`。

注意：`replace_section` 内部会再次调用 `extract_section`；这是有意的重复解析，换取调用点简单，章节解析是纯本地字符串操作。

- [ ] **Step 4: 运行测试，确认通过**

```powershell
uv run pytest tests/test_update_page_section.py -v
```

Expected: 6 passed。

- [ ] **Step 5: 注册新工具**

在 `server.py` 的 `register_write_tools` 元组中加入 `update_page` 和 `update_page_section`：

```python
    for tool in (create_page, add_comment, update_page, update_page_section):
        server.tool()(tool)
```

更新 `tests/test_registration.py` 的启用断言：

```python
    assert {"create_page", "add_comment", "update_page", "update_page_section"} <= names
```

- [ ] **Step 6: 运行全量测试**

```powershell
uv run pytest -v
```

Expected: 全部通过。

- [ ] **Step 7: 手动冒烟（必须做，覆盖竞态与真实渲染）**

1. `update_page` dry-run 一个普通页面：确认 diff 合理。
2. 用 `expected_version=1` 更新一个当前版本为 3 的页面：确认报“current version is 3”。
3. 在两个 MCP 会话里同时用同一个 `expected_version` 更新：第二个应收到 409 文案。
4. 含 TOC 宏的页面：确认 Markdown 整页更新被拒，`update_page_section` 更新后其余宏仍在原页面存在。
5. 在 Confluence 页面编辑器里打开更新后的页面，确认代码块渲染为代码宏、表格正常。

- [ ] **Step 8: 更新 README 与版本**

- “能力”加入 `update_page` / `update_page_section`，写明“整页更新默认拒绝含宏页面”。
- “启用写操作”补一句：单节更新是日常修改的推荐方式。
- `pyproject.toml` 版本 `0.3.1`。

- [ ] **Step 9: 提交**

```powershell
git add src/confluence_mcp/server.py tests/test_update_page_section.py tests/test_registration.py README.md pyproject.toml uv.lock
git commit -m "feat: add update_page_section and register update tools" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```
