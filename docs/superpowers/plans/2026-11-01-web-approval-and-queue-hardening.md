# 网页审批页与写入队列加固 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 人在本地网页里点一次"批准"就把队列里的 Confluence 写入发出去,同时给队列加上 Agent 查看/撤回、崩溃恢复、执行记录和版本号。

**Architecture:** 把 `server.py` 里"认领、发送、记结果、写审计"的循环挪进新模块 `apply.py`,让网页和终端 `approve` 共用;网页由独立命令 `confluence-mcp-review web` 用标准库 `http.server` 提供,令牌加 cookie 加 Host/Origin 检查;MCP 侧删除 `apply_approved_operations`,新增 4 个查看/撤回/记录工具。

**Tech Stack:** Python 3.10+、标准库 `sqlite3` / `http.server`、`mcp` FastMCP、pytest。

**Spec:** `docs/superpowers/specs/2026-11-01-web-approval-and-queue-hardening-design.md`

## Global Constraints

- Python `>=3.10`;不新增第三方依赖;网页服务只用标准库 `http.server`。
- 审批页只监听 `127.0.0.1`,随机端口;没有有效令牌 cookie 的请求一律 `403`。
- 每条操作最多发送一次;没有状态码的错误一律 `indeterminate`,绝不重试。
- 遇到 `indeterminate` 只停当前这一批,其余未处理的操作保持 `pending`;页面上其他操作仍可点(用户未回答此问题,这是默认)。
- 写入仍受 `writes_enabled()` 和 `ensure_write_allowed(space_key)` 约束。
- `web` 命令和终端 `approve` 都必须通过 `review._interactive_stdin()`(Windows 上要真实控制台)。
- MCP 工具不能批准、执行,也不能撤回非 `pending` 的操作。
- 页面渲染操作内容只用 `textContent` / `createElement`,不用 `innerHTML`。
- 队列数据库版本号用 `PRAGMA user_version`,`SCHEMA_VERSION = 1`,不改表结构。
- 在现有分支 `feat/write-approval-queue` 上做,不在 `main` 上提交。
- 测试命令:`python -m pytest tests -q`。

## Review Focus

- 同一条操作被连点两次或两个请求同时批准:只发送一次(Task 2、Task 5)。
- 没有 cookie、Host 不是 `127.0.0.1:<port>`(DNS 重绑定)、Origin 不匹配的请求:拒绝,且队列状态不变(Task 5)。
- Agent 入队的内容里含 `<script>`:页面当文本显示,不执行(Task 5)。
- 刚开始执行、还不到 5 分钟的 `executing` 不会被启动清扫改成 `indeterminate`(Task 1)。
- Agent 对 `approved` / `executing` 的 ID 调用撤回:原样保留并在结果里说明(Task 3)。

## File Structure

- `src/confluence_mcp/queue.py`(改):版本号检查、`get_op`、`claim_approved`、`recover_stale_executing`。
- `src/confluence_mcp/apply.py`(新):`execute`、`approve_and_apply`,从 `server.py` 迁来。
- `src/confluence_mcp/server.py`(改):删 `apply_approved_operations`,加 4 个队列工具。
- `src/confluence_mcp/review.py`(改):`approve` 改为批准即写入;新增 `web` 子命令。
- `src/confluence_mcp/web.py`(新):HTTP 处理器、令牌与来源检查、`serve`。
- `src/confluence_mcp/web_page.py`(新):常量 `PAGE`(单页 HTML/JS)。
- `README.md`(改)。

---

### Task 1: 队列版本号、按 ID 认领、启动清扫

**Files:**
- Modify: `src/confluence_mcp/queue.py`
- Test: `tests/test_queue.py`

**Interfaces:**
- Produces:
  - `SCHEMA_VERSION: int = 1`
  - `class QueueSchemaError(RuntimeError)`
  - `get_op(op_id: str) -> dict[str, Any] | None`
  - `claim_approved(op_id: str) -> dict[str, Any] | None`(只认领状态为 `approved` 的那一条,原子地改为 `executing`)
  - `recover_stale_executing(*, now: datetime | None = None, max_age_seconds: int = 300) -> list[str]`(把 `updated_at` 早于 `now - max_age_seconds` 的 `executing` 改为 `indeterminate`,`error` 为 `"Interrupted before the result was known; check Confluence before retrying."`,返回被改的 ID)

- [ ] **Step 1: 写失败的测试**(加到 `tests/test_queue.py`,文件顶部补 `sqlite3`、`from contextlib import closing`、`from datetime import datetime, timedelta, timezone`、`import pytest`)

```python
def test_claim_approved_claims_only_that_approved_op():
    a, b = _enqueue(), _enqueue()
    queue.approve([a, b])
    assert queue.claim_approved(b)["id"] == b
    assert queue.claim_approved(b) is None
    assert [r["status"] for r in queue.list_ops()] == ["approved", "executing"]

def test_claim_approved_ignores_pending():
    a = _enqueue()
    assert queue.claim_approved(a) is None
    assert queue.list_ops()[0]["status"] == "pending"

def test_get_op_returns_row_or_none():
    a = _enqueue()
    assert queue.get_op(a)["id"] == a
    assert queue.get_op("deadbeef") is None

def test_recover_flips_only_stale_executing_to_indeterminate():
    a, b = _enqueue(), _enqueue()
    queue.approve([a, b])
    queue.claim_approved(a)
    now = datetime.now(timezone.utc)
    assert queue.recover_stale_executing(now=now) == []
    assert queue.list_ops()[0]["status"] == "executing"
    assert queue.recover_stale_executing(now=now + timedelta(minutes=6)) == [a]
    rows = queue.list_ops()
    assert [r["status"] for r in rows] == ["indeterminate", "approved"]
    assert "Interrupted" in rows[0]["error"]

def _raw_db(user_version, schema=None):
    queue.QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(queue.QUEUE_PATH)) as conn:
        conn.execute(schema or queue._SCHEMA)
        conn.execute(f"PRAGMA user_version = {user_version}")

def test_new_database_is_stamped_with_schema_version():
    _enqueue()
    with closing(sqlite3.connect(queue.QUEUE_PATH)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == queue.SCHEMA_VERSION

def test_unversioned_database_with_matching_columns_is_stamped():
    _raw_db(0)
    assert queue.list_ops() == []
    with closing(sqlite3.connect(queue.QUEUE_PATH)) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == queue.SCHEMA_VERSION

def test_unknown_schema_version_is_refused():
    _raw_db(99)
    with pytest.raises(queue.QueueSchemaError, match="queue.sqlite3"):
        queue.list_ops()

def test_unversioned_database_with_other_columns_is_refused():
    _raw_db(0, "CREATE TABLE operations (id TEXT)")
    with pytest.raises(queue.QueueSchemaError):
        queue.list_ops()
```

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest tests/test_queue.py -v`
Expected: 新增的测试 FAIL(`AttributeError` 或 `QueueSchemaError` 未定义)。

- [ ] **Step 3: 实现版本检查**:在 `_connect()` 里 `conn.execute(_SCHEMA)` 之后读 `PRAGMA user_version`。为 0 时先比对 `PRAGMA table_info(operations)` 的列名集合与 `_SCHEMA` 的列(`id, created_at, updated_at, action, kind, page_id, space_key, version_before, summary, preview, payload, status, result, error`),一致则 `PRAGMA user_version = 1`,不一致抛 `QueueSchemaError`;非 0 且不等于 `SCHEMA_VERSION` 抛 `QueueSchemaError`。错误信息必须包含 `QUEUE_PATH` 的文件名,并说明"请检查或移走该文件"。出错时要关闭连接再抛。

- [ ] **Step 4: 实现 `get_op`、`claim_approved`、`recover_stale_executing`**:`claim_approved` 照 `claim_next_approved` 的 `BEGIN IMMEDIATE` 写法,只把 `WHERE id = ? AND status = 'approved'` 的那一行改为 `executing`。`recover_stale_executing` 的截止时间字符串用 `(now - timedelta(seconds=max_age_seconds)).isoformat()`,与 `_now()` 同格式,直接比较 `updated_at < cutoff`;在一个 `BEGIN IMMEDIATE` 事务里先查 ID 再更新。

- [ ] **Step 5: 运行,确认通过**

Run: `python -m pytest tests -q`
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add src/confluence_mcp/queue.py tests/test_queue.py
git commit -m "feat: version the queue schema and add per-op claim and stale recovery

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 共用执行模块,删除 MCP 的 apply 工具

**Files:**
- Create: `src/confluence_mcp/apply.py`
- Modify: `src/confluence_mcp/server.py`(删除 `apply_approved_operations`,从 `register_write_tools` 去掉它,删掉不再使用的导入)
- Test: `tests/test_apply_approved.py`(改写)、`tests/test_registration.py`

**Interfaces:**
- Consumes: Task 1 的 `queue.get_op`、`queue.claim_approved`。
- Produces:
  - `execute(client: Any, op: dict[str, Any]) -> dict[str, Any]`:`op` 是已被认领(`executing`)的行。执行 `ensure_write_allowed`、`update_page` 或 `create_content`,调用 `queue.finish`,成功时 `audit_write`。返回 `{"operation_id", "action", "status", "result", "error"}`,`status` 为 `succeeded` / `failed` / `indeterminate`(沿用原循环里的判定:有 `status_code` 的 `ConfluenceAPIError` 与 `ConfluenceConfigurationError` 为 `failed`,其余为 `indeterminate`)。
  - `approve_and_apply(client: Any, op_ids: list[str]) -> dict[str, Any]`:按给定顺序逐个处理。`pending` 先 `queue.approve`;已是 `approved` 的直接认领;其他状态记入 `not_pending`。认领后调 `execute`。遇到 `indeterminate` 立即停止,其后未处理的 ID 记入 `skipped`。返回 `{"executed": [...], "not_pending": [...], "skipped": [...]}`。

- [ ] **Step 1: 改写 `tests/test_apply_approved.py`**:保留 `audit_log` fixture 和 `_enqueue`,把 `server.apply_approved_operations()` 的调用换成 `apply.approve_and_apply(fake_client, ids)`。测试(`from confluence_mcp import apply, queue, writes`):

```python
def test_approve_and_apply_sends_stored_payload_and_audits(fake_client, audit_log):
    op = _enqueue(payload={"version": {"number": 4}})
    fake_client.update_response = {"id": "42", "version": {"number": 4}}
    out = apply.approve_and_apply(fake_client, [op])
    assert fake_client.updated == [{"version": {"number": 4}}]
    assert out["executed"][0]["status"] == "succeeded"
    assert out["executed"][0]["result"]["version"] == 4
    assert "update_page" in audit_log.read_text(encoding="utf-8")

def test_second_approval_of_same_op_sends_nothing(fake_client):
    op = _enqueue()
    fake_client.update_response = {"id": "42", "version": {"number": 4}}
    apply.approve_and_apply(fake_client, [op])
    out = apply.approve_and_apply(fake_client, [op])
    assert out["executed"] == [] and out["not_pending"] == [op]
    assert len(fake_client.updated) == 1

def test_leftover_approved_op_is_applied(fake_client):
    op = _enqueue()
    queue.approve([op])
    fake_client.update_response = {"id": "42", "version": {"number": 4}}
    assert apply.approve_and_apply(fake_client, [op])["executed"][0]["status"] == "succeeded"

def test_version_conflict_is_failed_and_batch_continues(fake_client):
    a, b = _enqueue(), _enqueue()
    calls = []
    def update(page_id, payload):
        calls.append(page_id)
        if len(calls) == 1:
            raise ConfluenceAPIError("conflict", status_code=409)
        return {"id": "42", "version": {"number": 4}}
    fake_client.update_page = update
    out = apply.approve_and_apply(fake_client, [a, b])
    assert [e["status"] for e in out["executed"]] == ["failed", "succeeded"]

def test_timeout_is_indeterminate_and_rest_stay_pending(fake_client):
    a, b, c = _enqueue(), _enqueue(), _enqueue()
    def timeout(page_id, payload):
        raise ConfluenceAPIError("timed out")
    fake_client.update_page = timeout
    out = apply.approve_and_apply(fake_client, [a, b, c])
    assert [e["status"] for e in out["executed"]] == ["indeterminate"]
    assert out["skipped"] == [b, c]
    assert [r["status"] for r in queue.list_ops()] == ["indeterminate", "pending", "pending"]

def test_whitelist_is_rechecked(fake_client, monkeypatch):
    op = _enqueue(space_key="OPS")
    monkeypatch.setenv("CONFLUENCE_WRITE_SPACES", "QA")
    assert apply.approve_and_apply(fake_client, [op])["executed"][0]["status"] == "failed"
    assert fake_client.updated == []

def test_create_records_new_page_id(fake_client):
    op = _enqueue(kind="create", page_id=None, version_before=None)
    fake_client.create_response = {"id": "77", "version": {"number": 1}}
    assert apply.approve_and_apply(fake_client, [op])["executed"][0]["result"]["id"] == "77"
```

在 `tests/test_registration.py` 里,两处断言里删掉 `apply_approved_operations`(默认隐藏的那条改为不再检查它;启用时的集合里删除它),并在启用时的测试末尾加 `assert "apply_approved_operations" not in names`。

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest tests/test_apply_approved.py tests/test_registration.py -v`
Expected: FAIL(`confluence_mcp.apply` 不存在;注册测试里 `apply_approved_operations` 仍被注册)。

- [ ] **Step 3: 创建 `apply.py`**:把 `server.apply_approved_operations` 循环体里 `try/except` 到 `queue.finish` / `audit_write` 的部分原样搬进 `execute`(保留所有判定与注释,尤其是"有状态码才是 failed"那条);`approve_and_apply` 按上面的契约写。

- [ ] **Step 4: 修改 `server.py`**:删除 `apply_approved_operations` 函数,把它从 `register_write_tools` 的元组里去掉,删除因此不再使用的导入(`audit_write`、`ConfluenceConfigurationError`)。

- [ ] **Step 5: 运行,确认通过**

Run: `python -m pytest tests -q`
Expected: 全部 PASS。

- [ ] **Step 6: 提交**

```bash
git add src/confluence_mcp/apply.py src/confluence_mcp/server.py tests/test_apply_approved.py tests/test_registration.py
git commit -m "refactor: move write execution to apply.py and drop the MCP apply tool

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: Agent 查看、撤回与执行记录工具

**Files:**
- Modify: `src/confluence_mcp/server.py`(加四个函数,放进 `register_write_tools`)
- Test: `tests/test_queue_tools.py`(新)、`tests/test_registration.py`

**Interfaces:**
- Consumes: `queue.list_ops`、`queue.get_op`、`queue.reject`。
- Produces(都返回 `dict[str, Any]`,均不含 `payload`):
  - `list_queued_operations(page: int = 1, page_size: int = 50)` → `{"items": [...], "total": int, "page": int, "page_size": int}`;`items` 是状态为 `pending` / `approved` / `executing` 的操作,字段 `id, status, action, space_key, page_id, version_before, summary, created_at`。`page >= 1`,`1 <= page_size <= 200`,否则 `ValueError`。
  - `get_queued_operations(operation_ids: list[str])` → `{"operations": [...], "missing": [...]}`,1 到 200 个 ID,按请求顺序;每条在上面字段基础上加 `preview, result, error, updated_at`。
  - `cancel_queued_operations(operation_ids: list[str])` → `{"cancelled": [...], "not_cancelled": [{"id", "status"}]}`,`status` 为当前状态或 `"unknown"`;只改 `pending`。
  - `get_execution_log(page: int = 1, page_size: int = 50)` → 同 `list_queued_operations` 的分页形状,`items` 是 `succeeded` / `failed` / `indeterminate` 的操作,最新在前,字段含 `result, error, updated_at`。

- [ ] **Step 1: 写失败的测试**(`tests/test_queue_tools.py`,`from confluence_mcp import queue, server`)

```python
def _op(**o):
    args = dict(kind="update", page_id="42", space_key="OPS", version_before=3,
                summary="Guide", preview="-old\n+new", payload={"secret": "storage"})
    args.update(o)
    return queue.enqueue("update_page", **args)

def test_list_shows_active_ops_without_payload():
    a = _op(); b = _op(); queue.reject([b])
    out = server.list_queued_operations()
    assert [i["id"] for i in out["items"]] == [a] and out["total"] == 1
    assert "payload" not in out["items"][0]

def test_list_paginates():
    ids = [_op() for _ in range(3)]
    out = server.list_queued_operations(page=2, page_size=2)
    assert [i["id"] for i in out["items"]] == ids[2:] and out["total"] == 3

def test_get_returns_preview_in_request_order_and_reports_missing():
    a, b = _op(), _op()
    out = server.get_queued_operations([b, "deadbeef", a])
    assert [o["id"] for o in out["operations"]] == [b, a]
    assert out["operations"][0]["preview"] == "-old\n+new"
    assert out["missing"] == ["deadbeef"]

def test_cancel_only_touches_pending():
    p, ap, ex = _op(), _op(), _op()
    queue.approve([ap, ex]); queue.claim_approved(ex)
    out = server.cancel_queued_operations([p, ap, ex, "deadbeef"])
    assert out["cancelled"] == [p]
    assert out["not_cancelled"] == [
        {"id": ap, "status": "approved"}, {"id": ex, "status": "executing"},
        {"id": "deadbeef", "status": "unknown"}]
    assert [r["status"] for r in queue.list_ops()] == ["rejected", "approved", "executing"]

def test_execution_log_lists_finished_newest_first():
    a, b = _op(), _op()
    queue.approve([a, b]); queue.claim_approved(a); queue.claim_approved(b)
    queue.finish(a, "succeeded", result={"id": "42", "version": 4})
    queue.finish(b, "failed", error="conflict")
    out = server.get_execution_log()
    assert [i["id"] for i in out["items"]] == [b, a]
    assert out["items"][0]["error"] == "conflict"
```

在 `tests/test_registration.py` 里,启用写入时的集合加上这四个名字,默认隐藏的测试里断言 `list_queued_operations` 不在 `names`。

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest tests/test_queue_tools.py tests/test_registration.py -v`
Expected: FAIL(函数未定义)。

- [ ] **Step 3: 实现四个函数**:校验失败抛 `ValueError`(沿用本文件其他工具的写法);分页用 `queue.list_ops(statuses)` 取回后切片,日志按 `updated_at` 倒序。加入 `register_write_tools` 的元组。这些函数本身不读取 Confluence,不需要 `get_client()`。

- [ ] **Step 4: 运行,确认通过**

Run: `python -m pytest tests -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add src/confluence_mcp/server.py tests/test_queue_tools.py tests/test_registration.py
git commit -m "feat: let the agent list, inspect and cancel queued writes and read the log

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 终端 `approve` 批准即写入

**Files:**
- Modify: `src/confluence_mcp/review.py`
- Test: `tests/test_review.py`

**Interfaces:**
- Consumes: `apply.approve_and_apply(client, op_ids)`、`writes.writes_enabled()`、`client.get_client()`。
- Produces: `review._approve(ids)` 行为变化:键入 `yes` 后对目标操作调用 `approve_and_apply(get_client(), [...])`,打印每条的 `operation_id`、`status`、`error`;写入未开启(`writes_enabled()` 为假)时在询问前打印错误到 stderr 并返回 `2`。`review.get_client` 作为模块属性存在,便于测试替换。

- [ ] **Step 1: 改测试**:`tests/test_review.py` 里 `_pending()` 不变。新增 autouse fixture,设置 `CONFLUENCE_ENABLE_WRITES=true`、用 `fake_client` 的 `monkeypatch.setattr(review, "get_client", lambda: fake_client)`(因为 `fake_client` 只替换 `server.get_client`,所以测试要自己替换 `review.get_client`)。把依赖"approve 之后状态是 `approved`"的两个测试改掉,并加入新测试:

```python
def test_approve_without_ids_approves_and_writes_all_pending(monkeypatch, capsys, fake_client):
    a, b = _pending(), _pending()
    fake_client.update_response = {"id": "42", "version": {"number": 4}}
    monkeypatch.setattr("sys.stdin", TTYInput("yes\n"))
    assert review.main(["approve"]) == 0
    assert {r["status"] for r in queue.list_ops()} == {"succeeded"}
    assert len(fake_client.updated) == 2
    assert "-old" in capsys.readouterr().out

def test_approve_refuses_when_writes_disabled(monkeypatch, capsys, fake_client):
    op = _pending()
    monkeypatch.delenv("CONFLUENCE_ENABLE_WRITES")
    monkeypatch.setattr("sys.stdin", TTYInput("yes\n"))
    assert review.main(["approve", op]) == 2
    assert queue.list_ops()[0]["status"] == "pending"
    assert "CONFLUENCE_ENABLE_WRITES" in capsys.readouterr().err
```

`test_approve_reports_non_pending_ids` 保留,需同样依赖该 fixture。

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest tests/test_review.py -v`
Expected: FAIL。

- [ ] **Step 3: 实现**:在 `review.py` 里 `from .client import get_client`、`from .apply import approve_and_apply`、`from .writes import WRITE_FLAG, writes_enabled`。`_approve` 里在控制台检查之后、读取队列之前检查 `writes_enabled()`。确认后改为 `approve_and_apply(get_client(), [op["id"] for op in targets])`;`not_pending` 和 `skipped` 沿用 `not pending: <id>` / `skipped: <id>` 的输出格式。

- [ ] **Step 4: 运行,确认通过**

Run: `python -m pytest tests -q`
Expected: 全部 PASS。

- [ ] **Step 5: 提交**

```bash
git add src/confluence_mcp/review.py tests/test_review.py
git commit -m "feat: terminal approve now writes the approved operations

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: 网页审批页

**Files:**
- Create: `src/confluence_mcp/web.py`、`src/confluence_mcp/web_page.py`
- Modify: `src/confluence_mcp/review.py`(新增 `web` 子命令)
- Test: `tests/test_web.py`、`tests/test_review.py`

**Interfaces:**
- Consumes: `apply.approve_and_apply`、`queue.list_ops`、`queue.reject`、`queue.recover_stale_executing`。
- Produces:
  - `web_page.PAGE: str`
  - `web.make_server(client: Any, token: str, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer`
  - `web.serve(client: Any) -> None`:生成 `secrets.token_urlsafe(32)`,创建服务,打印 `http://127.0.0.1:<port>/?token=<token>`,`webbrowser.open` 同一地址,`serve_forever()`,`KeyboardInterrupt` 时关闭。
  - 路由:`GET /?token=<t>`(令牌正确则设置 `cmr_session=<t>; HttpOnly; SameSite=Strict; Path=/` 并 `302` 到 `/`,否则 `403`);`GET /`(返回 `PAGE`);`GET /api/state`;`POST /api/approve`;`POST /api/reject`;其他路径 `404`。
  - 所有请求(令牌落地除外)要求 cookie 与令牌相等(`secrets.compare_digest`),且 `Host` 为 `127.0.0.1:<port>` 或 `localhost:<port>`;`POST` 还要求 `Origin` 为 `http://<上述 Host 之一>`。不满足一律 `403`,不读取请求体,不改队列。
  - `/api/state` 返回 `{"operations": [...]}`:状态为 `pending` / `approved` / `executing` 的全部,加最近 20 条已结束的;每条字段 `id, status, action, kind, space_key, page_id, version_before, summary, preview, result, error, created_at, updated_at`,不含 `payload`。
  - `POST` 请求体是 `{"ids": [str, ...]}`,1 到 200 个字符串,否则 `400`。`/api/approve` 返回 `approve_and_apply` 的字典;`/api/reject` 返回 `{"rejected": [...]}`。
  - 一个模块级 `threading.Lock` 包住 `approve_and_apply`,让并发批准串行执行。
  - 响应头:`Cache-Control: no-store`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`,页面响应加 `Content-Security-Policy: default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'`。
  - `review.py` 的 `web` 子命令:非交互终端返回 `2`(信息含 `interactive terminal`);`writes_enabled()` 为假返回 `2`(信息含 `CONFLUENCE_ENABLE_WRITES`);否则 `queue.recover_stale_executing()`,再 `web.serve(get_client())`,返回 `0`。

- [ ] **Step 1: 写失败的测试**(`tests/test_web.py`)。用线程里的 `make_server(fake_client, "tok")`,`http.client.HTTPConnection("127.0.0.1", port)` 发请求。辅助函数 `call(method, path, body=None, cookie=True, host=None, origin=...)`。

```python
def test_token_landing_sets_cookie_and_redirects(server): ...  # 302, Set-Cookie 含 HttpOnly 和 SameSite=Strict
def test_wrong_token_is_403(server): ...
def test_requests_without_cookie_are_403_and_do_not_touch_queue(server, fake_client):
    op = _pending()
    assert call("POST", "/api/approve", {"ids": [op]}, cookie=False).status == 403
    assert call("GET", "/api/state", cookie=False).status == 403
    assert queue.list_ops()[0]["status"] == "pending" and fake_client.updated == []
def test_foreign_host_is_403(server):          # Host: evil.example:<port>,带有效 cookie
def test_post_with_wrong_or_missing_origin_is_403(server): ...
def test_state_lists_pending_without_payload(server): ...
def test_approve_writes_once_even_when_posted_twice(server, fake_client):
    op = _pending(); fake_client.update_response = {"id": "42", "version": {"number": 4}}
    first = call("POST", "/api/approve", {"ids": [op]})
    second = call("POST", "/api/approve", {"ids": [op]})
    assert len(fake_client.updated) == 1
    assert json.loads(second.read())["not_pending"] == [op]
def test_reject_marks_pending_rejected(server): ...
def test_approve_rejects_bad_body(server):     # {"ids": []}、{"ids": [1]}、非 JSON 都是 400
def test_page_never_uses_innerhtml():
    assert "innerHTML" not in web_page.PAGE and "outerHTML" not in web_page.PAGE
    assert "textContent" in web_page.PAGE
```

在 `tests/test_review.py` 里加:

```python
def test_web_refuses_without_tty(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    assert review.main(["web"]) == 2
    assert "interactive terminal" in capsys.readouterr().err

def test_web_refuses_when_writes_disabled(monkeypatch, capsys):
    monkeypatch.delenv("CONFLUENCE_ENABLE_WRITES", raising=False)
    monkeypatch.setattr("sys.stdin", TTYInput(""))
    assert review.main(["web"]) == 2
    assert "CONFLUENCE_ENABLE_WRITES" in capsys.readouterr().err

def test_web_sweeps_stale_ops_then_serves(monkeypatch, fake_client):
    served = []
    monkeypatch.setenv("CONFLUENCE_ENABLE_WRITES", "true")
    monkeypatch.setattr("sys.stdin", TTYInput(""))
    monkeypatch.setattr(review, "get_client", lambda: fake_client)
    monkeypatch.setattr(review.web, "serve", served.append)
    monkeypatch.setattr(review.queue, "recover_stale_executing", lambda: served.append("swept"))
    assert review.main(["web"]) == 0
    assert served == ["swept", fake_client]
```

- [ ] **Step 2: 运行,确认失败**

Run: `python -m pytest tests/test_web.py tests/test_review.py -v`
Expected: FAIL(模块不存在)。

- [ ] **Step 3: 实现 `web.py`**:`BaseHTTPRequestHandler` 子类,`make_server` 里通过 `functools.partial` 或把 `client`、`token`、`port` 挂在 `server` 对象上传给处理器。每个请求先过一个 `_authorized(require_origin)` 检查,失败直接 `403`,不读请求体。`log_message` 重写为不输出请求行(请求行里有令牌)。

- [ ] **Step 4: 实现 `web_page.py` 的 `PAGE`**:布局 A。顶部栏有 `#approve-all` 和 `#reject-all`;左侧 `#list` 是操作列表(每项显示 `id`、状态、`action`、`space_key/page_id`、`v<version_before>`、`summary`),右侧 `#detail` 含标题、`<pre id="diff">`(显示 `preview`)、`#approve`、`#reject`、`#result`(显示该条的状态、错误或成功链接文本)。批准 `approved`(遗留未写入)的操作时,按钮文字为"写入"。"全部批准"先 `confirm("写入 N 条?")`,N 是 `pending` 条数。所有数据只用 `textContent` 和 `createElement` 写入 DOM;请求用 `fetch(..., {method: "POST", credentials: "same-origin"})`;动作后和每 5 秒刷新一次 `/api/state`;`403` 时停止轮询并在页面上提示"会话失效,请重新运行 confluence-mcp-review web"。

- [ ] **Step 5: 在 `review.py` 加 `web` 子命令**:`from . import queue, web`,`subparsers.add_parser("web", ...)`,按上面的契约实现 `_web()`。

- [ ] **Step 6: 运行,确认通过**

Run: `python -m pytest tests -q`
Expected: 全部 PASS。

- [ ] **Step 7: 手动验证**:在真实终端运行 `CONFLUENCE_ENABLE_WRITES=true confluence-mcp-review web`(PowerShell 里先设 `$env:CONFLUENCE_ENABLE_WRITES="true"`),确认浏览器自动打开、页面能列出一条用 `update_page` 工具 `dry_run=False` 入队的操作、点"拒绝"后状态变化。不要在没有测试空间的情况下点"批准"。

- [ ] **Step 8: 提交**

```bash
git add src/confluence_mcp/web.py src/confluence_mcp/web_page.py src/confluence_mcp/review.py tests/test_web.py tests/test_review.py
git commit -m "feat: add local web approval page that writes on approve

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: 更新 `README.md`**:读一遍现有写入/审批相关章节,改成如下内容(保持原有语气):
  - 审批流程:Agent 入队 → 人运行 `confluence-mcp-review web`(或终端 `approve`)→ 批准即写入;`apply_approved_operations` 已移除。
  - 新增四个工具的名字与用途。
  - 新增"已知边界"一节:SQLite 队列、审计日志不防同一系统用户的篡改;审批页令牌只防别的网页和别的机器,不防本机上有同样权限的恶意进程;结果不明(`indeterminate`)的操作不会自动重试,需要人去 Confluence 核对;队列数据库有版本号,版本不认识时拒绝打开。
  - 启动 `web` 需要真实控制台和 `CONFLUENCE_ENABLE_WRITES=true`。

- [ ] **Step 2: 提交**

```bash
git add README.md
git commit -m "docs: describe web approval and the queue's known limits

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Self-Review

- **覆盖:** 目标 1(Task 5)、2(Task 3)、3(Task 1 与 Task 5 的启动清扫)、4(Task 3)、5(Task 1)、6(Task 6);决定 4、5、6(Task 2、4)、7(Task 2 的 `approve_and_apply` 与 Task 5 的 `confirm`)、8(Task 5)、9(Task 3)、10(Task 1)、11 到 16(Task 1、2、5)。
- **类型一致:** `claim_approved`、`get_op`、`recover_stale_executing`、`approve_and_apply`、`execute` 的名字和参数在各任务里一致;`review.get_client` 与 `review.web` 都是模块属性,测试用 `monkeypatch.setattr` 替换。
- **Review Focus** 五条分别落在 Task 2/5(重复批准)、Task 5(来源检查、`innerHTML`)、Task 1(清扫新鲜 `executing`)、Task 3(撤回非 `pending`)。
- 未做:没有升版本号(删除了一个 MCP 工具,按语义属于不兼容变更,发布前再定);没有改 `.gitignore`(`.superpowers/` 等你确认)。
