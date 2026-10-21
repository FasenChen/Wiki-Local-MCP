# Phase 1: 只读检索与上下文控制 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `cql_search` 与 `get_page_outline`，并让 `get_page` 支持按章节读取和 `max_chars` 截断，解决长页面撑爆上下文的问题。

**Architecture:** `cql_search` 复用 client，打 `GET /rest/api/search`；章节解析放在新模块 `outline.py`，直接切分 storage XHTML 并保留原始标签，不做 Markdown 往返，因此宏不会丢失。`get_page` 只在本地切分后再转换。

**Tech Stack:** Python 3.10+、FastMCP（`mcp==1.30.0`）、httpx、markdownify、pytest。

**Spec:** `docs/tool-roadmap-v0.2.md`（本计划实现读工具 #1、#2）

## Global Constraints

- Python `>=3.10`，命令统一用 `uv run`。
- 测试依赖 `pytest>=8,<9`，通过 `pyproject.toml` 的 `[dependency-groups] dev` 引入。
- 目标环境 Confluence Data Center 8.5.15，REST API v1（`/rest/api`），PAT 认证。
- 本阶段只发起 `GET` 请求；`ConfluenceClient` 不新增写方法。
- 现有 `search_pages` / `get_page_by_title` 的返回字段和行为保持不变；`get_page` 只新增可选参数和 `truncated` 字段。
- 精确签名为：`cql_search(cql: str, limit: int = 25, start: int = 0)`、`get_page_outline(page_id: str)`、`get_page(page_id: str, output_format: OutputFormat = "markdown", section: str | None = None, max_chars: int | None = None)`。
- 返回字段名逐字固定：`page_id`、`title`、`space_key`、`excerpt`、`last_modified`、`url`、`next_start`；大纲条目为 `level`、`title`、`anchor`；截断标志为 `truncated`。
- 测试不访问真实 Confluence：所有工具测试用 `tests/conftest.py` 里的 fake client。
- 按 Phase 1 → 4 顺序执行；后续阶段依赖本阶段新增的 `client.absolute_url` 和 `outline.py`。

## Review Focus

1. storage 中 `<ac:plain-text-body><![CDATA[...]]>` 和 `<!-- -->` 注释里的 `<h2>...` 不是标题，必须忽略。
2. 同名章节（含仅大小写不同的）必须报错并列出候选，不能静默任选一个。
3. `max_chars` 截断时必须返回 `truncated: true`；未截断时为 `false`，字段始终存在。
4. 目标章节是最后一个标题时，正文一直取到 storage 末尾。
5. `cql_search` 的 CQL 是原样透传，这是设计意图：只校验空值和长度，不要转义或改写 CQL。
6. 页面没有任何标题却请求 `section` 时，错误信息要列出可用标题（空列表也要说清楚）。

## File Structure

- Create `src/confluence_mcp/outline.py` — 标题定位、章节切分，纯函数，无 I/O。
- Create `tests/conftest.py` — fake client fixture。
- Create `tests/test_cql_search.py`、`tests/test_outline.py`、`tests/test_get_page.py`。
- Modify `src/confluence_mcp/client.py` — `search_cql`、`absolute_url`。
- Modify `src/confluence_mcp/server.py` — 两个新工具、`get_page` 参数、`_convert_storage`。
- Modify `pyproject.toml` — dev 依赖、版本 `0.2.0`。
- Modify `README.md` — 新工具与参数说明。

---

### Task 1: 测试脚手架与 `cql_search`

**Files:**
- Modify: `pyproject.toml`
- Create: `tests/conftest.py`
- Create: `tests/test_cql_search.py`
- Modify: `src/confluence_mcp/client.py`
- Modify: `src/confluence_mcp/server.py`

**Interfaces:**
- Consumes: `ConfluenceClient._get_json(path, *, params)`、`get_client()`（均为现有实现）。
- Produces:
  - `ConfluenceClient.search_cql(self, cql: str, *, limit: int, start: int) -> dict[str, Any]`，返回 `/rest/api/search` 的原始 JSON。
  - `ConfluenceClient.absolute_url(self, path: str | None) -> str | None`。
  - `_search_result_summary(result: dict[str, Any], client: Any) -> dict[str, Any]`。
  - 工具 `cql_search(cql: str, limit: int = 25, start: int = 0) -> dict[str, Any]`，返回 `{"results": [...], "count": int, "next_start": int | None}`。

- [ ] **Step 1: 添加测试依赖并同步环境**

在 `pyproject.toml` 追加：

```toml
[dependency-groups]
dev = ["pytest>=8,<9"]
```

运行：

```powershell
uv sync
uv run pytest --version
```

Expected: 输出 pytest 8.x 版本号。

- [ ] **Step 2: 创建 `tests/conftest.py` 的 fake client**

```python
import pytest


class FakeClient:
    def __init__(self):
        self.pages = {}
        self.search_response = {"results": [], "totalSize": 0}
        self.search_calls = []

    def get_page(self, page_id):
        return self.pages[page_id]

    def search_pages(self, cql, limit):
        self.search_calls.append((cql, limit, 0))
        return self.search_response.get("results", [])

    def search_cql(self, cql, *, limit, start):
        self.search_calls.append((cql, limit, start))
        return self.search_response

    def absolute_url(self, path):
        return f"https://wiki.example.com{path}"

    def page_url(self, page):
        return f"https://wiki.example.com/pages/{page['id']}"


@pytest.fixture
def fake_client(monkeypatch):
    from confluence_mcp import server

    client = FakeClient()
    monkeypatch.setattr(server, "get_client", lambda: client)
    return client
```

- [ ] **Step 3: 写失败测试 `tests/test_cql_search.py`**

```python
import pytest

from confluence_mcp import server


def test_cql_search_returns_page_summaries(fake_client):
    fake_client.search_response = {
        "results": [
            {
                "content": {"id": 42, "space": {"key": "OPS"}},
                "title": "Release 1.0",
                "excerpt": "highlights",
                "lastModified": "2026-10-01T10:00:00.000Z",
                "url": "/spaces/OPS/pages/42/Release+1.0",
            }
        ],
        "totalSize": 3,
    }

    result = server.cql_search('label = "release"', limit=25, start=0)

    assert fake_client.search_calls == [('label = "release"', 25, 0)]
    assert result == {
        "results": [
            {
                "page_id": "42",
                "title": "Release 1.0",
                "space_key": "OPS",
                "excerpt": "highlights",
                "last_modified": "2026-10-01T10:00:00.000Z",
                "url": "https://wiki.example.com/spaces/OPS/pages/42/Release+1.0",
            }
        ],
        "count": 1,
        "next_start": 1,
    }


def test_cql_search_has_no_next_start_when_results_are_exhausted(fake_client):
    fake_client.search_response = {"results": [], "totalSize": 0}

    result = server.cql_search("type = page", limit=25, start=0)

    assert result["next_start"] is None


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 51}, {"start": -1}])
def test_cql_search_rejects_invalid_paging(fake_client, kwargs):
    with pytest.raises(ValueError):
        server.cql_search("type = page", **kwargs)


def test_cql_search_rejects_blank_cql(fake_client):
    with pytest.raises(ValueError):
        server.cql_search("   ")
```

- [ ] **Step 4: 运行测试，确认失败**

```powershell
uv run pytest tests/test_cql_search.py -v
```

Expected: FAIL，`AttributeError: module 'confluence_mcp.server' has no attribute 'cql_search'`。

- [ ] **Step 5: 在 `client.py` 实现 `search_cql` 和 `absolute_url`**

```python
def search_cql(self, cql: str, *, limit: int, start: int) -> dict[str, Any]:
    return self._get_json(
        "search",
        params={"cql": cql, "limit": limit, "start": start, "expand": "content.space,content.version"},
    )

def absolute_url(self, path: str | None) -> str | None:
    if not path:
        return None
    return urljoin(self._base_url.rstrip("/") + "/", path.lstrip("/"))
```

把现有 `page_url` 改为使用它：

```python
def page_url(self, page: dict[str, Any]) -> str | None:
    return self.absolute_url((page.get("_links") or {}).get("webui"))
```

`cql_search` 的 `expand` 参数在 8.5.15 上若返回 400，改为不带 `expand`，并从 `result["resultGlobalContainer"]` 取 space 名称以外的一切字段（space_key 可能为 `None`）；这一条在 Step 8 的实测里确认。

- [ ] **Step 6: 在 `server.py` 实现 `cql_search`**

```python
def _search_result_summary(result: dict[str, Any], client: Any) -> dict[str, Any]:
    content = result.get("content") or {}
    space = content.get("space") or {}
    return {
        "page_id": str(content.get("id", "")),
        "title": result.get("title") or content.get("title", ""),
        "space_key": space.get("key"),
        "excerpt": result.get("excerpt", ""),
        "last_modified": result.get("lastModified"),
        "url": client.absolute_url(result.get("url")),
    }


@mcp.tool()
def cql_search(cql: str, limit: int = 25, start: int = 0) -> dict[str, Any]:
    """Run a raw CQL query against Confluence and return matching pages."""
    cql = cql.strip()
    if not cql:
        raise ValueError("cql must not be empty.")
    if len(cql) > 4000:
        raise ValueError("cql must be 4000 characters or fewer.")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50.")
    if start < 0:
        raise ValueError("start must be zero or greater.")

    client = get_client()
    payload = client.search_cql(cql, limit=limit, start=start)
    results = payload.get("results", [])
    total = payload.get("totalSize")
    if isinstance(total, int):
        has_more = start + len(results) < total
    else:
        has_more = len(results) == limit
    return {
        "results": [_search_result_summary(item, client) for item in results],
        "count": len(results),
        "next_start": start + len(results) if has_more else None,
    }
```

- [ ] **Step 7: 运行测试，确认通过**

```powershell
uv run pytest tests/test_cql_search.py -v
```

Expected: 6 passed。

- [ ] **Step 8: 对真实实例做一次冒烟验证（手动）**

在能访问 Confluence 的环境启动 MCP host，依次调用：

```text
cql_search(cql='type = page AND space = "OPS"', limit=5)
cql_search(cql='label = "release" and lastmodified > now("-7d")', limit=5)
```

Expected: 返回结果里 `space_key` 非空、`url` 是绝对地址；若第一条触发 400，执行 Step 5 的 `expand` 回退说明。把实测结论写进 README 的“能力”一节。

- [ ] **Step 9: 提交**

```powershell
git add pyproject.toml uv.lock tests/conftest.py tests/test_cql_search.py src/confluence_mcp/client.py src/confluence_mcp/server.py
git commit -m "feat: add cql_search tool" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: 章节解析器 `outline.py`

**Files:**
- Create: `src/confluence_mcp/outline.py`
- Create: `tests/test_outline.py`

**Interfaces:**
- Produces:
  - `Heading` dataclass：字段 `level: int`、`title: str`、`anchor: str`、`start: int`、`end: int`（`start` 是标题起始 `<` 的索引，`end` 是闭合标签之后的索引）。
  - `find_headings(storage: str) -> list[Heading]`。
  - `extract_section(storage: str, title: str) -> tuple[Heading, str]`；`str` 是不含标题标签的章节正文；找不到或重名时抛 `ValueError`。

- [ ] **Step 1: 写失败测试 `tests/test_outline.py`**

```python
import pytest

from confluence_mcp.outline import extract_section, find_headings


def test_find_headings_returns_level_title_and_anchor():
    storage = '<h1>Guide</h1><h2>Overview</h2><p>x</p><h3 id="raw">Details &amp; Notes</h3>'

    headings = find_headings(storage)

    assert [(h.level, h.title, h.anchor) for h in headings] == [
        (1, "Guide", "guide"),
        (2, "Overview", "overview"),
        (3, "Details & Notes", "details-notes"),
    ]


def test_find_headings_ignores_headings_inside_cdata_and_comments():
    storage = (
        '<ac:plain-text-body><![CDATA[<h2>Fake</h2>]]></ac:plain-text-body>'
        '<!-- <h2>Commented</h2> --><h2>Real</h2>'
    )

    assert [h.title for h in find_headings(storage)] == ["Real"]


def test_extract_section_stops_at_next_same_or_higher_level():
    storage = '<h1>A</h1><p>a</p><h2>B</h2><p>b</p><h2>C</h2><p>c</p><h1>D</h1>'

    heading, body = extract_section(storage, "A")

    assert heading.title == "A"
    assert body == '<p>a</p><h2>B</h2><p>b</p><h2>C</h2><p>c</p>'


def test_extract_section_last_heading_runs_to_end():
    storage = '<h1>A</h1><h2>Last</h2><p>tail</p>'

    _, body = extract_section(storage, "Last")

    assert body == '<p>tail</p>'


def test_extract_section_is_case_insensitive_when_unique():
    storage = '<h2>Notes</h2><p>n</p>'

    assert extract_section(storage, "notes")[0].title == "Notes"


def test_extract_section_rejects_ambiguous_titles():
    storage = '<h2>Notes</h2><p>1</p><h2>notes</h2><p>2</p>'

    with pytest.raises(ValueError, match="more than one"):
        extract_section(storage, "Notes")


def test_extract_section_lists_available_titles_when_missing():
    storage = '<h1>A</h1><h2>B</h2>'

    with pytest.raises(ValueError, match="Available sections: A, B"):
        extract_section(storage, "C")
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
uv run pytest tests/test_outline.py -v
```

Expected: FAIL，`ModuleNotFoundError: No module named 'confluence_mcp.outline'`。

- [ ] **Step 3: 实现 `src/confluence_mcp/outline.py`**

要点：

- 先用同长度空格遮罩 CDATA（`<!\[CDATA\[.*?\]\]>`）与注释（`<!--.*?-->`），再在遮罩串上跑标题正则，保证索引与原文一致。
- 标题正则：`<h([1-6])(?:\s[^>]*)?>(.*?)</h\1\s*>`，`IGNORECASE | DOTALL`。
- `title`：去掉内层标签、`html.unescape`、折叠空白、strip。
- `anchor`：`re.sub(r"[^\w一-鿿]+", "-", title.lower()).strip("-")`；重名时追加 `-2`、`-3`。
- `extract_section`：先精确匹配 `title`；无匹配再做大小写不敏感匹配；0 个匹配抛 `ValueError(f'No section titled "{title}". Available sections: {", ".join(titles) or "(none)"}')`；多个匹配抛 `ValueError('More than one section titled "..."; use a unique title. Candidates: ...')`。
- 正文结束位置是之后第一个 `level <= heading.level` 的标题的 `start`；没有则 `len(storage)`。
- 一行注释说明为什么遮罩 CDATA：`# Headings inside code macros are literal text, not sections.`

- [ ] **Step 4: 运行测试，确认通过**

```powershell
uv run pytest tests/test_outline.py -v
```

Expected: 7 passed。

- [ ] **Step 5: 提交**

```powershell
git add src/confluence_mcp/outline.py tests/test_outline.py
git commit -m "feat: add storage heading and section parser" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: `get_page_outline` 工具

**Files:**
- Modify: `src/confluence_mcp/server.py`
- Create: `tests/test_get_page_outline.py`

**Interfaces:**
- Consumes: `find_headings`（Task 2）、`_page_summary`、`get_client()`。
- Produces: 工具 `get_page_outline(page_id: str) -> dict[str, Any]`，返回页面摘要字段加 `"headings": [{"level": int, "title": str, "anchor": str}]`。

- [ ] **Step 1: 写失败测试 `tests/test_get_page_outline.py`**

```python
from confluence_mcp import server


def test_get_page_outline_returns_headings(fake_client):
    fake_client.pages["42"] = {
        "id": "42",
        "title": "Guide",
        "space": {"key": "OPS"},
        "version": {"number": 3},
        "_links": {"webui": "/spaces/OPS/pages/42"},
        "body": {"storage": {"value": "<h1>Guide</h1><p>x</p><h2>Setup</h2>"}},
    }

    result = server.get_page_outline("42")

    assert result["headings"] == [
        {"level": 1, "title": "Guide", "anchor": "guide"},
        {"level": 2, "title": "Setup", "anchor": "setup"},
    ]
    assert result["page_id"] == "42"
    assert result["version"] == 3
    assert result["url"] == "https://wiki.example.com/pages/42"
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
uv run pytest tests/test_get_page_outline.py -v
```

Expected: FAIL，`AttributeError: ... has no attribute 'get_page_outline'`。

- [ ] **Step 3: 在 `server.py` 实现工具**

```python
@mcp.tool()
def get_page_outline(page_id: str) -> dict[str, Any]:
    """List the h1-h6 headings of a page without returning its body."""
    client = get_client()
    page = client.get_page(page_id)
    storage = ((page.get("body") or {}).get("storage") or {}).get("value") or ""
    return {
        **_page_summary(page, client),
        "headings": [
            {"level": heading.level, "title": heading.title, "anchor": heading.anchor}
            for heading in find_headings(storage)
        ],
    }
```

导入：`from .outline import find_headings`。

- [ ] **Step 4: 运行测试，确认通过**

```powershell
uv run pytest tests/test_get_page_outline.py -v
```

Expected: 1 passed。

- [ ] **Step 5: 提交**

```powershell
git add src/confluence_mcp/server.py tests/test_get_page_outline.py
git commit -m "feat: add get_page_outline tool" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: `get_page` 的 `section` 与 `max_chars`

**Files:**
- Modify: `src/confluence_mcp/server.py`
- Create: `tests/test_get_page.py`

**Interfaces:**
- Consumes: `extract_section`（Task 2）、`_page_content`（现有）。
- Produces:
  - `_convert_storage(storage: str, output_format: Literal["markdown", "storage"]) -> str`。
  - 新签名 `get_page(page_id: str, output_format: OutputFormat = "markdown", section: str | None = None, max_chars: int | None = None) -> dict[str, Any]`；返回体新增 `"truncated": bool`。
  - `section` 与 `output_format="html"` 同时使用抛 `ValueError`。

- [ ] **Step 1: 写失败测试 `tests/test_get_page.py`**

```python
import pytest

from confluence_mcp import server

PAGE = {
    "id": "42",
    "title": "Guide",
    "space": {"key": "OPS"},
    "version": {"number": 3},
    "_links": {"webui": "/spaces/OPS/pages/42"},
    "body": {
        "storage": {
            "value": (
                "<h1>Guide</h1><p>intro</p>"
                "<h2>Setup</h2><p>run it</p>"
                "<h2>Notes</h2><p>note</p>"
            )
        }
    },
}


def test_get_page_section_returns_only_that_section(fake_client):
    fake_client.pages["42"] = PAGE

    result = server.get_page("42", section="Setup")

    assert result["content"] == "## Setup\n\nrun it"
    assert result["truncated"] is False


def test_get_page_without_section_returns_full_page(fake_client):
    fake_client.pages["42"] = PAGE

    result = server.get_page("42")

    assert result["content"].startswith("# Guide")
    assert "## Notes" in result["content"]
    assert result["truncated"] is False


def test_get_page_max_chars_truncates_and_flags(fake_client):
    fake_client.pages["42"] = PAGE

    result = server.get_page("42", max_chars=5)

    assert result["content"] == "# Gui"
    assert result["truncated"] is True


def test_get_page_section_rejects_html_output(fake_client):
    fake_client.pages["42"] = PAGE

    with pytest.raises(ValueError, match="output_format"):
        server.get_page("42", output_format="html", section="Setup")


def test_get_page_missing_section_lists_available_titles(fake_client):
    fake_client.pages["42"] = PAGE

    with pytest.raises(ValueError, match="Available sections: Guide, Setup, Notes"):
        server.get_page("42", section="Missing")


def test_get_page_rejects_non_positive_max_chars(fake_client):
    fake_client.pages["42"] = PAGE

    with pytest.raises(ValueError):
        server.get_page("42", max_chars=0)
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
uv run pytest tests/test_get_page.py -v
```

Expected: FAIL，`TypeError: get_page() got an unexpected keyword argument 'section'`。

- [ ] **Step 3: 修改 `server.py`**

把 `_page_content` 中 storage/markdown 的分支抽成：

```python
def _convert_storage(storage: str, output_format: OutputFormat) -> str:
    if output_format == "storage":
        return storage
    if not storage:
        raise ConfluenceAPIError("The page has no storage body available to convert to Markdown.")
    return storage_to_markdown(storage)
```

`_page_content` 的 `markdown` / `storage` 分支调用 `_convert_storage`，`html` 分支保持原样。

`get_page` 改为：

```python
@mcp.tool()
def get_page(
    page_id: str,
    output_format: OutputFormat = "markdown",
    section: str | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    """Read one Confluence page, optionally only one section, with an optional length cap."""
    if max_chars is not None and max_chars < 1:
        raise ValueError("max_chars must be at least 1.")

    client = get_client()
    page = client.get_page(page_id)
    storage = ((page.get("body") or {}).get("storage") or {}).get("value") or ""

    if section is not None:
        if output_format == "html":
            raise ValueError('section is only supported with output_format "markdown" or "storage".')
        heading, body = extract_section(storage, section)
        content = _convert_storage(storage[heading.start : heading.end] + body, output_format)
    else:
        content = _page_content(page, output_format)

    truncated = False
    if max_chars is not None:
        truncated = len(content) > max_chars
        content = content[:max_chars]

    return {
        **_page_summary(page, client),
        "format": output_format,
        "content": content,
        "truncated": truncated,
    }
```

导入：`from .outline import extract_section, find_headings`。

- [ ] **Step 4: 运行测试，确认通过**

```powershell
uv run pytest tests/test_get_page.py tests/test_get_page_outline.py -v
```

Expected: 7 passed。

- [ ] **Step 5: 提交**

```powershell
git add src/confluence_mcp/server.py tests/test_get_page.py
git commit -m "feat: read a single page section and cap page length" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: 文档与版本

**Files:**
- Modify: `README.md`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: 前四个任务完成后的工具集合。
- Produces: 版本号 `0.2.0`，README 与实际工具一致。

- [ ] **Step 1: 升版本**

`pyproject.toml`：`version = "0.2.0"`。

- [ ] **Step 2: 更新 README**

在“能力”一节追加：

```markdown
- `cql_search`：直接执行 CQL，支持标签、时间、作者、空间组合查询；返回 excerpt 与分页 `next_start`。
- `get_page_outline`：只返回 h1–h6 标题树，适合先看结构再决定读哪一节。
- `get_page` 新增 `section` 与 `max_chars`：按标题只读一节；超长内容截断并返回 `truncated`。
```

在“常用调用”一节追加：

```markdown
- 按标签检索：`cql_search(cql='label = "release" and lastmodified > now("-7d")')`
- 看页面结构：`get_page_outline(page_id="123456")`
- 只读一节：`get_page(page_id="123456", section="部署步骤")`
- 限制长度：`get_page(page_id="123456", max_chars=4000)`
```

补充一句限制：`section` 只支持 `markdown` / `storage` 输出；`html` 是整个 `body.view`，无法按章节切分。

- [ ] **Step 3: 跑全量测试**

```powershell
uv run pytest -v
```

Expected: 所有测试通过。

- [ ] **Step 4: 提交**

```powershell
git add README.md pyproject.toml uv.lock
git commit -m "docs: document phase 1 read tools and bump version" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```
