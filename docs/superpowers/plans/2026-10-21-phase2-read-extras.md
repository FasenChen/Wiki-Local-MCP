# Phase 2: 只读扩展工具 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 补齐 `list_spaces`、`get_comments`、`get_children`、`get_page_history` 四个只读工具，其中历史工具支持两个版本的 Markdown diff。

**Architecture:** 全部复用 `ConfluenceClient._get_json`。`get_children` 递归调用 `child/page` 并在本地组树，硬上限防止拉全站；`get_page_history` 先试 v1 版本端点，失败再退到 `/rest/experimental`，并给 `ConfluenceAPIError` 增加 `status_code` 以便按状态码回退。

**Tech Stack:** Python 3.10+、FastMCP（`mcp==1.30.0`）、httpx、markdownify、pytest。

**Spec:** `docs/tool-roadmap-v0.2.md`（本计划实现读工具 #3、#4、#5、#6）

## Global Constraints

- 本阶段只发起 `GET` 请求，不新增任何写方法。
- 先完成 Phase 1；本阶段复用其 `client.absolute_url` 与 `tests/conftest.py` 的 `FakeClient`。
- 目标环境 Confluence Data Center 8.5.15，REST API v1；版本端点是否可用必须实测确认。
- 工具签名固定：`list_spaces(limit: int = 50, start: int = 0)`、`get_comments(page_id: str, limit: int = 50)`、`get_children(page_id: str, depth: int = 1, limit: int = 50)`、`get_page_history(page_id: str, from_version: int | None = None, to_version: int | None = None, limit: int = 25, max_chars: int = 4000)`。
- `depth` 上限 3；`limit` 范围 1–50（`list_spaces` 1–100）；`max_chars >= 1`。
- 测试不访问真实 Confluence；端点路径只通过“路径常量 + fake client”间接覆盖，真实路径靠 Step 的手动冒烟确认。
- 不新增依赖。

## Review Focus

1. 版本端点不存在时（8.5 上可能 404/405）必须回退到 `/rest/experimental`，不能把 404 当成页面不存在。
2. `from_version` / `to_version` 只给一个时必须报错，不能猜另一半。
3. 子页面递归遇到总节点上限时必须停止并标记 `truncated: true`，不能无限翻页。
4. 评论回复的父评论 ID 取 `ancestors` 中最后一个 comment 类型的 id；顶层评论为 `None`。
5. 版本 diff 必须截断到 `max_chars` 并返回 `truncated`；上一版本号不存在时给出清楚的错误。
6. `page_id` 只允许数字，所有新方法复用同一校验。

## File Structure

- Modify `src/confluence_mcp/client.py` — `_validate_page_id`、`list_spaces`、`get_comments`、`get_child_pages`、`list_versions`、`get_page_version`，`ConfluenceAPIError.status_code`。
- Modify `src/confluence_mcp/server.py` — 四个新工具、`_storage`、`_unified_diff`、`_version_summary`。
- Modify `tests/conftest.py` — 扩展 `FakeClient`。
- Create `tests/test_spaces.py`、`tests/test_comments.py`、`tests/test_children.py`、`tests/test_history.py`。
- Modify `README.md`。

---

### Task 1: `ConfluenceAPIError.status_code`、页面 ID 校验与 `list_spaces`

**Files:**
- Modify: `src/confluence_mcp/client.py`
- Modify: `src/confluence_mcp/server.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_spaces.py`

**Interfaces:**
- Produces:
  - `ConfluenceAPIError(message: str, status_code: int | None = None)`，实例属性 `status_code`。
  - `ConfluenceClient._validate_page_id(page_id: str) -> None`（非数字抛 `ValueError`）。
  - `ConfluenceClient.list_spaces(self, *, limit: int, start: int) -> dict[str, Any]`。
  - 工具 `list_spaces(limit: int = 50, start: int = 0) -> dict[str, Any]`，返回 `{"spaces": [{"key", "name", "url"}], "count": int, "next_start": int | None}`。

- [ ] **Step 1: 扩展 `tests/conftest.py`**

给 `FakeClient.__init__` 增加：

```python
        self.spaces_response = {"results": [], "size": 0}
```

增加方法：

```python
    def list_spaces(self, *, limit, start):
        self.search_calls.append(("spaces", limit, start))
        return self.spaces_response
```

- [ ] **Step 2: 写失败测试 `tests/test_spaces.py`**

```python
import pytest

from confluence_mcp import server


def test_list_spaces_returns_key_name_and_url(fake_client):
    fake_client.spaces_response = {
        "results": [{"key": "OPS", "name": "Operations", "_links": {"webui": "/display/OPS"}}],
        "size": 1,
    }

    result = server.list_spaces(limit=10)

    assert result == {
        "spaces": [
            {
                "key": "OPS",
                "name": "Operations",
                "url": "https://wiki.example.com/display/OPS",
            }
        ],
        "count": 1,
        "next_start": None,
    }


@pytest.mark.parametrize("kwargs", [{"limit": 0}, {"limit": 101}, {"start": -1}])
def test_list_spaces_rejects_invalid_paging(fake_client, kwargs):
    with pytest.raises(ValueError):
        server.list_spaces(**kwargs)


def test_api_error_defaults_to_no_status_code():
    from confluence_mcp.client import ConfluenceAPIError

    assert ConfluenceAPIError("boom").status_code is None
```

- [ ] **Step 3: 运行测试，确认失败**

```powershell
uv run pytest tests/test_spaces.py -v
```

Expected: FAIL，`AttributeError: ... has no attribute 'list_spaces'`。

- [ ] **Step 4: 修改 `client.py`**

异常类改为：

```python
class ConfluenceAPIError(RuntimeError):
    """Raised when Confluence returns an unsuccessful response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
```

把 `get_page` 里的数字校验抽成方法，所有按 ID 取内容的客户端方法都先调用它：

```python
    def _validate_page_id(self, page_id: str) -> None:
        if not re.fullmatch(r"[0-9]+", page_id):
            raise ValueError("page_id must contain only digits.")
```

`_get_json` 抛错时带上状态码，例如：

```python
raise ConfluenceAPIError("Confluence returned 404: ...", status_code=404)
raise ConfluenceAPIError(f"Confluence returned HTTP {response.status_code}.", status_code=response.status_code)
```

新方法：

```python
    def list_spaces(self, *, limit: int, start: int) -> dict[str, Any]:
        return self._get_json("space", params={"type": "global", "limit": limit, "start": start})
```

- [ ] **Step 5: 在 `server.py` 实现 `list_spaces`**

```python
@mcp.tool()
def list_spaces(limit: int = 50, start: int = 0) -> dict[str, Any]:
    """List global Confluence spaces visible to the current account."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")
    if start < 0:
        raise ValueError("start must be zero or greater.")

    client = get_client()
    payload = client.list_spaces(limit=limit, start=start)
    results = payload.get("results", [])
    total = payload.get("size")
    if isinstance(total, int):
        has_more = start + len(results) < total
    else:
        has_more = len(results) == limit
    return {
        "spaces": [
            {
                "key": space.get("key", ""),
                "name": space.get("name", ""),
                "url": client.absolute_url((space.get("_links") or {}).get("webui")),
            }
            for space in results
        ],
        "count": len(results),
        "next_start": start + len(results) if has_more else None,
    }
```

注意：`/rest/api/space` 的响应没有 `totalSize`，只有 `size`/`limit`，因此读取 `size`。

- [ ] **Step 6: 运行测试，确认通过**

```powershell
uv run pytest tests/test_spaces.py -v
```

Expected: 5 passed。

- [ ] **Step 7: 提交**

```powershell
git add src/confluence_mcp/client.py src/confluence_mcp/server.py tests/conftest.py tests/test_spaces.py
git commit -m "feat: add list_spaces tool and API status codes" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 2: `get_comments`

**Files:**
- Modify: `src/confluence_mcp/client.py`
- Modify: `src/confluence_mcp/server.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_comments.py`

**Interfaces:**
- Produces:
  - `ConfluenceClient.get_comments(self, page_id: str, *, limit: int) -> list[dict[str, Any]]`。
  - 工具 `get_comments(page_id: str, limit: int = 50) -> dict[str, Any]`，返回 `{"comments": [{"comment_id", "author", "created", "parent_comment_id", "content"}], "count": int}`。

- [ ] **Step 1: 扩展 `tests/conftest.py`**

```python
        self.comments = {}
```

```python
    def get_comments(self, page_id, *, limit):
        self.search_calls.append(("comments", page_id, limit))
        return self.comments.get(page_id, [])
```

- [ ] **Step 2: 写失败测试 `tests/test_comments.py`**

```python
from confluence_mcp import server


def test_get_comments_returns_author_body_and_parent(fake_client):
    fake_client.comments["42"] = [
        {
            "id": "99",
            "ancestors": [],
            "history": {
                "createdBy": {"displayName": "Alice"},
                "createdDate": "2026-10-01T10:00:00.000Z",
            },
            "body": {"storage": {"value": "<p>first</p>"}},
        },
        {
            "id": "100",
            "ancestors": [{"id": "42", "type": "page"}, {"id": "99", "type": "comment"}],
            "history": {
                "createdBy": {"displayName": "Bob"},
                "createdDate": "2026-10-02T10:00:00.000Z",
            },
            "body": {"storage": {"value": "<p>reply</p>"}},
        },
    ]

    result = server.get_comments("42", limit=50)

    assert result["comments"] == [
        {
            "comment_id": "99",
            "author": "Alice",
            "created": "2026-10-01T10:00:00.000Z",
            "parent_comment_id": None,
            "content": "first",
        },
        {
            "comment_id": "100",
            "author": "Bob",
            "created": "2026-10-02T10:00:00.000Z",
            "parent_comment_id": "99",
            "content": "reply",
        },
    ]
    assert result["count"] == 2
```

- [ ] **Step 3: 运行测试，确认失败**

```powershell
uv run pytest tests/test_comments.py -v
```

Expected: FAIL，`AttributeError: ... has no attribute 'get_comments'`。

- [ ] **Step 4: 实现 client 与工具**

client：

```python
    def get_comments(self, page_id: str, *, limit: int) -> list[dict[str, Any]]:
        self._validate_page_id(page_id)
        payload = self._get_json(
            f"content/{page_id}/child/comment",
            params={
                "expand": "body.storage,version,history",
                "depth": "all",
                "limit": limit,
            },
        )
        return payload.get("results", [])
```

server：

```python
@mcp.tool()
def get_comments(page_id: str, limit: int = 50) -> dict[str, Any]:
    """Read page comments as Markdown, preserving reply parents."""
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50.")

    client = get_client()
    comments = client.get_comments(page_id, limit=limit)
    return {
        "comments": [
            {
                "comment_id": str(comment.get("id", "")),
                "author": ((comment.get("history") or {}).get("createdBy") or {}).get("displayName"),
                "created": (comment.get("history") or {}).get("createdDate"),
                "parent_comment_id": _comment_parent(comment),
                "content": _convert_storage(
                    ((comment.get("body") or {}).get("storage") or {}).get("value") or "",
                    "markdown",
                ),
            }
            for comment in comments
        ],
        "count": len(comments),
    }


def _comment_parent(comment: dict[str, Any]) -> str | None:
    comment_ancestors = [
        ancestor for ancestor in comment.get("ancestors") or [] if ancestor.get("type") == "comment"
    ]
    if not comment_ancestors:
        return None
    return str(comment_ancestors[-1].get("id", ""))
```

把 `_page_summary` 之后定义的 `_convert_storage` 放在工具之前（Phase 1 已创建）。

- [ ] **Step 5: 运行测试，确认通过**

```powershell
uv run pytest tests/test_comments.py -v
```

Expected: 1 passed。

- [ ] **Step 6: 手动冒烟（必须做，8.5 的 `depth=all` 行为需确认）**

调用 `get_comments(page_id=<有回复的页面>)`，确认回复的 `parent_comment_id` 指向父评论而不是页面 ID。若 8.5 不返回嵌套评论，改为对每条评论再请求 `content/{comment_id}/child/comment`，并把结论写进 README。

- [ ] **Step 7: 提交**

```powershell
git add src/confluence_mcp/client.py src/confluence_mcp/server.py tests/conftest.py tests/test_comments.py
git commit -m "feat: add get_comments tool" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 3: `get_children`（限深、限总量）

**Files:**
- Modify: `src/confluence_mcp/client.py`
- Modify: `src/confluence_mcp/server.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_children.py`

**Interfaces:**
- Produces:
  - `ConfluenceClient.get_child_pages(self, page_id: str, *, limit: int) -> list[dict[str, Any]]`。
  - `MAX_CHILD_NODES = 200`（模块级常量，便于测试改小）。
  - 工具 `get_children(page_id: str, depth: int = 1, limit: int = 50) -> dict[str, Any]`，节点字段同 `_page_summary`，`depth > 1` 时每个节点带 `"children": [...]`；顶层带 `"truncated": bool`。

- [ ] **Step 1: 扩展 `tests/conftest.py`**

```python
        self.children = {}
```

```python
    def get_child_pages(self, page_id, *, limit):
        self.search_calls.append(("children", page_id, limit))
        return self.children.get(page_id, [])[:limit]
```

- [ ] **Step 2: 写失败测试 `tests/test_children.py`**

```python
import pytest

from confluence_mcp import server


def _page(page_id, title):
    return {"id": page_id, "title": title, "space": {"key": "OPS"}, "version": {"number": 1}}


def test_get_children_returns_tree(fake_client):
    fake_client.children = {"1": [_page("2", "Child")], "2": [_page("3", "Grandchild")]}

    result = server.get_children("1", depth=2)

    assert result["children"][0]["page_id"] == "2"
    assert result["children"][0]["children"][0]["page_id"] == "3"
    assert result["truncated"] is False


def test_get_children_depth_one_has_no_children_key(fake_client):
    fake_client.children = {"1": [_page("2", "Child")]}

    result = server.get_children("1", depth=1)

    assert "children" not in result["children"][0]


@pytest.mark.parametrize("depth", [0, 4])
def test_get_children_rejects_depth_out_of_range(fake_client, depth):
    with pytest.raises(ValueError):
        server.get_children("1", depth=depth)


def test_get_children_stops_at_node_cap(fake_client, monkeypatch):
    monkeypatch.setattr(server, "MAX_CHILD_NODES", 2)
    fake_client.children = {"1": [_page("2", "A"), _page("3", "B")], "2": [_page("4", "C")]}

    result = server.get_children("1", depth=3)

    assert result["truncated"] is True
```

- [ ] **Step 3: 运行测试，确认失败**

```powershell
uv run pytest tests/test_children.py -v
```

Expected: FAIL，`AttributeError: ... has no attribute 'get_children'`。

- [ ] **Step 4: 实现 client 与工具**

client：

```python
    def get_child_pages(self, page_id: str, *, limit: int) -> list[dict[str, Any]]:
        self._validate_page_id(page_id)
        payload = self._get_json(
            f"content/{page_id}/child/page",
            params={"expand": "space,version", "limit": limit},
        )
        return payload.get("results", [])
```

server：

```python
MAX_CHILD_NODES = 200


@mcp.tool()
def get_children(page_id: str, depth: int = 1, limit: int = 50) -> dict[str, Any]:
    """List child pages, optionally recursing up to three levels."""
    if not 1 <= depth <= 3:
        raise ValueError("depth must be between 1 and 3.")
    if not 1 <= limit <= 50:
        raise ValueError("limit must be between 1 and 50.")

    client = get_client()
    budget = [MAX_CHILD_NODES]
    truncated = False

    def build(current_id: str, levels_left: int) -> list[dict[str, Any]]:
        nonlocal truncated
        nodes = []
        for child in client.get_child_pages(current_id, limit=limit):
            if budget[0] <= 0:
                truncated = True
                break
            budget[0] -= 1
            node = _page_summary(child, client)
            if levels_left > 1:
                node["children"] = build(str(child.get("id", "")), levels_left - 1)
            nodes.append(node)
        return nodes

    return {"page_id": page_id, "children": build(page_id, depth), "truncated": truncated}
```

- [ ] **Step 5: 运行测试，确认通过**

```powershell
uv run pytest tests/test_children.py -v
```

Expected: 5 passed。

- [ ] **Step 6: 提交**

```powershell
git add src/confluence_mcp/client.py src/confluence_mcp/server.py tests/conftest.py tests/test_children.py
git commit -m "feat: add get_children tool with depth and node caps" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 4: 版本列表与历史版本读取

**Files:**
- Modify: `src/confluence_mcp/client.py`
- Modify: `tests/conftest.py`
- Create: `tests/test_history.py`

**Interfaces:**
- Produces:
  - `ConfluenceClient.list_versions(self, page_id: str) -> list[dict[str, Any]]`；先试 `content/{id}/version`，`404`/`405` 时回退 `../experimental/content/{id}/version`，两者都失败才抛错。
  - `ConfluenceClient.get_page_version(self, page_id: str, version: int) -> dict[str, Any]`，返回 `status=historical` 的页面。
  - `_version_summary(version: dict[str, Any]) -> dict[str, Any]`（server 内），字段 `number`、`when`、`by`、`message`。

- [ ] **Step 1: 扩展 `tests/conftest.py`**

```python
        self.versions = {}
        self.historical_pages = {}
```

```python
    def list_versions(self, page_id):
        self.search_calls.append(("versions", page_id, 0))
        return self.versions.get(page_id, [])

    def get_page_version(self, page_id, version):
        self.search_calls.append(("version", page_id, version))
        return self.historical_pages[(page_id, version)]
```

- [ ] **Step 2: 写失败测试（客户端回退逻辑，用子类覆盖 `_get_json`）**

`tests/test_history.py` 前半：

```python
import pytest

from confluence_mcp import server
from confluence_mcp.client import ConfluenceAPIError, ConfluenceClient


class FallingBackClient(ConfluenceClient):
    def __init__(self):
        self.paths = []

    def _get_json(self, path, *, params):
        self.paths.append(path)
        if path.startswith("content/"):
            raise ConfluenceAPIError("not found", status_code=404)
        return {"results": [{"number": 2, "when": "2026-10-01", "by": {"displayName": "A"}, "message": "m"}]}


def test_list_versions_falls_back_to_experimental_endpoint():
    client = FallingBackClient()

    versions = client.list_versions("42")

    assert client.paths == [
        "content/42/version",
        "../experimental/content/42/version",
    ]
    assert versions[0]["number"] == 2


class OnlyExperimentalForbiddenClient(ConfluenceClient):
    def __init__(self):
        pass

    def _get_json(self, path, *, params):
        raise ConfluenceAPIError("forbidden", status_code=403)


def test_list_versions_does_not_swallow_permission_errors():
    with pytest.raises(ConfluenceAPIError, match="forbidden"):
        OnlyExperimentalForbiddenClient().list_versions("42")
```

- [ ] **Step 3: 运行测试，确认失败**

```powershell
uv run pytest tests/test_history.py -v
```

Expected: FAIL，`AttributeError: 'FallingBackClient' object has no attribute 'list_versions'`。

- [ ] **Step 4: 实现 client 方法**

```python
    def list_versions(self, page_id: str) -> list[dict[str, Any]]:
        self._validate_page_id(page_id)
        last_error: ConfluenceAPIError | None = None
        for path in (
            f"content/{page_id}/version",
            f"../experimental/content/{page_id}/version",
        ):
            try:
                return self._get_json(path, params={"limit": 100}).get("results", [])
            except ConfluenceAPIError as exc:
                if exc.status_code not in (404, 405):
                    raise
                last_error = exc
        raise ConfluenceAPIError(
            "Confluence exposes no version-history endpoint at /rest/api/content/{id}/version "
            "or /rest/experimental/content/{id}/version.",
            status_code=last_error.status_code if last_error else None,
        )

    def get_page_version(self, page_id: str, version: int) -> dict[str, Any]:
        self._validate_page_id(page_id)
        return self._get_json(
            f"content/{page_id}",
            params={
                "status": "historical",
                "version": version,
                "expand": "body.storage,version,space",
            },
        )
```

`../experimental/...` 相对 `base_url=".../rest/api/"` 解析为 `.../rest/experimental/...`，这是 httpx 的相对 URL 行为；不要改成绝对地址，否则会丢掉上下文路径。

- [ ] **Step 5: 运行测试，确认通过**

```powershell
uv run pytest tests/test_history.py -v
```

Expected: 2 passed。

- [ ] **Step 6: 手动冒烟**

对真实 8.5.15 实例执行（PowerShell，PAT 已在环境变量中）：

```powershell
curl.exe -s -H "Authorization: Bearer $env:ATLASSIAN_CONFLUENCE_PAT" "$env:ATLASSIAN_CONFLUENCE_URL/rest/api/content/<page_id>/version?limit=5"
curl.exe -s -H "Authorization: Bearer $env:ATLASSIAN_CONFLUENCE_PAT" "$env:ATLASSIAN_CONFLUENCE_URL/rest/api/content/<page_id>?status=historical&version=2&expand=body.storage"
```

Expected: 第一条返回 `results` 数组时无需回退；若返回 404/405 而第二条可用，说明回退路径生效。把结论写进 README 的“官方接口依据”附近。

- [ ] **Step 7: 提交**

```powershell
git add src/confluence_mcp/client.py tests/conftest.py tests/test_history.py
git commit -m "feat: add version listing with experimental fallback" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```

---

### Task 5: `get_page_history` 工具与 diff

**Files:**
- Modify: `src/confluence_mcp/server.py`
- Modify: `tests/test_history.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `list_versions`、`get_page_version`（Task 4）、`_convert_storage`（Phase 1）。
- Produces:
  - `_storage(page: dict[str, Any]) -> str`。
  - `_unified_diff(old: str, new: str, from_label: str, to_label: str) -> str`。
  - 工具 `get_page_history(page_id, from_version=None, to_version=None, limit=25, max_chars=4000) -> dict[str, Any]`；返回 `{"page_id", "versions": [...], "diff"?, "truncated"?}`。

- [ ] **Step 1: 追加失败测试到 `tests/test_history.py`**

```python
def _page(version, storage):
    return {
        "id": "42",
        "title": "Guide",
        "space": {"key": "OPS"},
        "version": {"number": version},
        "body": {"storage": {"value": storage}},
    }


def test_get_page_history_lists_recent_versions(fake_client):
    fake_client.versions["42"] = [
        {"number": 2, "when": "2026-10-02", "by": {"displayName": "Bob"}, "message": "fix"},
        {"number": 1, "when": "2026-10-01", "by": {"displayName": "Alice"}, "message": ""},
    ]

    result = server.get_page_history("42", limit=1)

    assert result["versions"] == [
        {"number": 2, "when": "2026-10-02", "by": "Bob", "message": "fix"}
    ]
    assert "diff" not in result


def test_get_page_history_diffs_two_versions(fake_client):
    fake_client.historical_pages[("42", 1)] = _page(1, "<p>old</p>")
    fake_client.historical_pages[("42", 2)] = _page(2, "<p>new</p>")

    result = server.get_page_history("42", from_version=1, to_version=2)

    assert result["diff"].startswith("--- v1")
    assert "-old" in result["diff"]
    assert "+new" in result["diff"]
    assert result["truncated"] is False


def test_get_page_history_truncates_long_diff(fake_client):
    fake_client.historical_pages[("42", 1)] = _page(1, "<p>old</p>")
    fake_client.historical_pages[("42", 2)] = _page(2, "<p>new</p>")

    result = server.get_page_history("42", from_version=1, to_version=2, max_chars=10)

    assert len(result["diff"]) == 10
    assert result["truncated"] is True


def test_get_page_history_requires_both_versions(fake_client):
    with pytest.raises(ValueError, match="both"):
        server.get_page_history("42", from_version=1)


@pytest.mark.parametrize("kwargs", [{"from_version": 0, "to_version": 1}, {"from_version": 1, "to_version": 1}])
def test_get_page_history_rejects_invalid_versions(fake_client, kwargs):
    with pytest.raises(ValueError):
        server.get_page_history("42", **kwargs)
```

- [ ] **Step 2: 运行测试，确认失败**

```powershell
uv run pytest tests/test_history.py -v
```

Expected: FAIL，`AttributeError: ... has no attribute 'get_page_history'`。

- [ ] **Step 3: 实现工具**

```python
def _storage(page: dict[str, Any]) -> str:
    return ((page.get("body") or {}).get("storage") or {}).get("value") or ""


def _unified_diff(old: str, new: str, from_label: str, to_label: str) -> str:
    return "\n".join(
        difflib.unified_diff(
            old.splitlines(), new.splitlines(), fromfile=from_label, tofile=to_label, lineterm=""
        )
    )


@mcp.tool()
def get_page_history(
    page_id: str,
    from_version: int | None = None,
    to_version: int | None = None,
    limit: int = 25,
    max_chars: int = 4000,
) -> dict[str, Any]:
    """List page versions, or diff two versions as Markdown."""
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1.")
    if (from_version is None) != (to_version is None):
        raise ValueError("Provide both from_version and to_version, or neither.")
    for version in (from_version, to_version):
        if version is not None and version < 1:
            raise ValueError("version numbers must be at least 1.")
    if from_version is not None and from_version == to_version:
        raise ValueError("from_version and to_version must differ.")

    client = get_client()
    versions = [
        {
            "number": item.get("number"),
            "when": item.get("when"),
            "by": (item.get("by") or {}).get("displayName"),
            "message": item.get("message", ""),
        }
        for item in client.list_versions(page_id)[:limit]
    ]
    result: dict[str, Any] = {"page_id": page_id, "versions": versions}
    if from_version is None:
        return result

    old_storage = _storage(client.get_page_version(page_id, from_version))
    new_storage = _storage(client.get_page_version(page_id, to_version or from_version))
    diff = _unified_diff(
        storage_to_markdown(old_storage),
        storage_to_markdown(new_storage),
        f"v{from_version}",
        f"v{to_version}",
    )
    result["diff"] = diff[:max_chars]
    result["truncated"] = len(diff) > max_chars
    return result
```

导入 `difflib` 和 `storage_to_markdown`（后者已导入）。

- [ ] **Step 4: 运行测试，确认通过**

```powershell
uv run pytest tests/test_history.py -v
```

Expected: 8 passed。

- [ ] **Step 5: 更新 README**

在“能力”追加四个工具，注明：`get_children` 最多 3 层、总节点上限 200；`get_page_history` 的版本端点先在 `/rest/api` 尝试，8.5 不支持时回退 `/rest/experimental`。

- [ ] **Step 6: 提交**

```powershell
git add src/confluence_mcp/server.py tests/test_history.py README.md
git commit -m "feat: add page history and version diff tools" -m "Co-Authored-By: Claude Code <noreply@anthropic.com>"
```
