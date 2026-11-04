# `.env` 行尾注释修复与版本收尾 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `.env` 解析器支持行尾注释（防止写工具静默消失），统一版本号，清理文档，使项目可以安全发版。

**Architecture:** 
在行尾注释解析上，区分引号内外的 `#`（引号内只是值的一部分，引号外且前有空白才算注释）。改进 `.env` 默认路径为当前工作目录，统一版本号为 0.4.0，删除已过时的未跟踪计划文档，增加端到端测试确保 `.env` 启动加载真的影响工具注册。移除 PAT 敏感信息偷渡风险。

**Tech Stack:** 
Python 3.10+，pytest，标准库 `pathlib` 和正则表达式。

**Spec:** 全项目审查发现（2026-11-04），基于 ponytail 和代码审查结果。见上文"必须修"和"应该修"章节。

## Global Constraints

- 必须保留向后兼容：`.env` 不存在时静默通过，进程环境变量优先不被覆盖。
- 版本号必须与 pyproject.toml 一致（0.4.0）。
- 不修改 main 分支；所有改动在 feat/env-file-config 上。
- 测试覆盖率不下降（当前 219 个通过）。
- 令牌只从系统凭据库或进程环境来，不从 `.env` 读取。

## Review Focus

1. **行尾注释使写工具静默消失** — `CONFLUENCE_ENABLE_WRITES=true # enable` 让值变成 `true # enable`，`writes_enabled()` 判定为假，写工具不注册且没有任何警告。
   - 测试：`test_parses_env_with_inline_comment_outside_quotes` 断言值被正确截断。

2. **发版安装后找不到 `.env`** — 从源码文件向上两级的路径在 wheel 安装后指向错误位置。
   - 测试：`test_default_env_path_is_cwd_not_source` 或在 README 明确记录。

3. **启动加载 `.env` 不会真的影响工具注册** — 现有测试只看 `load_env_file` 函数，没看包导入时的全流程。
   - 测试：`test_writes_tools_enabled_from_env_file` 重新加载 server 模块，断言写工具根据 `.env` 值而注册/不注册。

4. **PAT 可能被写进 `.env`** — 代码接受 `ATLASSIAN_CONFLUENCE_PAT` 从 `.env` 读取，而 README 说不要。
   - 测试：确保 `.env` 中的 PAT 被忽略（或从 `load_env_file` 过滤）。

5. **版本号不一致** — pyproject.toml 是 0.4.0，src/__init__.py 是 0.1.0。
   - 测试或文档：pyproject.toml 来自 v0.4.0 tag（含 move_page、web 审批、queue 等），应该一致。

---

## File Structure

| 文件 | 职责 |
|---|---|
| `src/confluence_mcp/settings_file.py` | `.env` 解析与加载；支持行尾注释、排除 PAT 敏感键 |
| `src/confluence_mcp/__init__.py` | 包初始化时调用 `.env` 加载 |
| `src/confluence_mcp/client.py` | 凭据读取（不变） |
| `tests/test_settings_file.py` | 单元测试 `.env` 解析和加载 |
| `tests/test_registration.py` | 端到端测试：`.env` 影响工具注册 |
| `tests/conftest.py` | 测试隔离（不变） |
| `README.md` | 文档：`.env` 用法、版本号；删除过时说明 |
| `src/confluence_mcp/__init__.py` | 版本号统一到 0.4.0 |
| `docs/superpowers/plans/2026-11-03-env-file-config.md` | 删除（已过时，描述已删除的功能） |

---

## Task 1: 改进 `.env` 解析器支持行尾注释

**Files:**
- Modify: `src/confluence_mcp/settings_file.py:19-27`
- Modify: `tests/test_settings_file.py` (append)

**Interfaces:**
- Consumes: 无（现有 `parse_env`）
- Produces: 改进后的 `parse_env(text: str) -> dict[str, str]`，支持行尾注释和引号内的 `#`

- [ ] **Step 1: 写测试：行尾注释被剥离**

```python
def test_strips_trailing_comments_outside_quotes():
    text = 'A=hello # comment\nB="value # not comment"\n'
    assert parse_env(text) == {"A": "hello", "B": "value # not comment"}
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_settings_file.py::test_strips_trailing_comments_outside_quotes -v`
Expected: FAIL，`{"A": "hello # comment", ...}`

- [ ] **Step 3: 实现行尾注释处理**

在 `parse_env` 的值处理上（现在是 `value = value.strip()`），先去掉成对引号，再对无引号的值：找最后一个空白字符，之后如果是 `#` 就截断。算法：
```
if value 引号配对: 去掉引号
else: value = value.rstrip() 然后从后向前找第一个 `# ` 模式，如果找到就截断前面部分
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_settings_file.py::test_strips_trailing_comments_outside_quotes -v`
Expected: PASS

- [ ] **Step 5: 补充测试覆盖边界情况**

```python
def test_preserves_hash_inside_quotes():
    text = "URL='https://wiki.example.com#section'\n"
    assert parse_env(text) == {"URL": "https://wiki.example.com#section"}

def test_trailing_comment_with_multiple_hashes():
    text = 'KEY=value ## comment with multiple #\n'
    assert parse_env(text) == {"KEY": "value"}
```

- [ ] **Step 6: 运行全部 settings_file 测试**

Run: `pytest tests/test_settings_file.py -v`
Expected: 全部通过（现有 + 新增）

- [ ] **Step 7: 提交**

```bash
git add src/confluence_mcp/settings_file.py tests/test_settings_file.py
git commit -m "fix(config): parse_env strips trailing comments outside quotes

- Distinguish between # inside and outside quoted values
- Trailing # preceded by whitespace marks a comment
- Fixes issue where CONFLUENCE_ENABLE_WRITES=true # enable made value 'true # enable'
- Tests cover hash in URLs, multiple hashes, and quote preservation

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: 调整 `.env` 默认路径为当前工作目录

**Files:**
- Modify: `src/confluence_mcp/settings_file.py:8-9`
- Modify: `README.md` (文档)
- Test: 已有 `test_missing_file_is_a_no_op` 应继续通过

**Interfaces:**
- Consumes: 无（改内部常量）
- Produces: `DEFAULT_ENV_FILE = Path.cwd() / ".env"`

- [ ] **Step 1: 阅读现状**

现状：`DEFAULT_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"` 指向源码上两级。MCP 配置的 `cwd` 已指向仓库，所以用 `Path.cwd()` 更简洁且发版后也正确。

- [ ] **Step 2: 改为当前工作目录**

编辑 `src/confluence_mcp/settings_file.py:9`，改为：
```python
DEFAULT_ENV_FILE = Path.cwd() / ".env"
```

- [ ] **Step 3: 运行现有测试验证不破坏**

Run: `pytest tests/test_settings_file.py -v`
Expected: 全部通过（`test_missing_file_is_a_no_op` 等）

- [ ] **Step 4: 更新 README 文档**

在"本地配置文件 `.env`"小节，改为：
```
MCP 启动时会读取当前工作目录下的 `.env`（参考 `.env.example`）。
MCP 的 MCP_HOST 配置应设置 `cwd` 指向仓库目录。
```

- [ ] **Step 5: 提交**

```bash
git add src/confluence_mcp/settings_file.py README.md
git commit -m "fix(config): use current working directory for default .env path

- Changed from source-relative path to Path.cwd() / '.env'
- More reliable for wheel installations and deployed environments
- MCP_HOST cwd config already points to repo, so this is semantically correct
- Updated README to clarify cwd requirement

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: 从 `.env` 解析过程排除敏感键（PAT）

**Files:**
- Modify: `src/confluence_mcp/settings_file.py:31-38` (`load_env_file` 函数)
- Modify: `tests/test_settings_file.py` (append)

**Interfaces:**
- Consumes: `parse_env` 返回的字典（已改进）
- Produces: 改进后的 `load_env_file`，跳过 `ATLASSIAN_CONFLUENCE_PAT`

- [ ] **Step 1: 写测试：PAT 键被过滤**

```python
def test_load_env_skips_pat_key(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text(
        "ATLASSIAN_CONFLUENCE_URL=https://wiki.example.com\n"
        "ATLASSIAN_CONFLUENCE_PAT=secret-token-123\n"
        "CONFLUENCE_ENABLE_WRITES=true\n",
        encoding="utf-8"
    )
    monkeypatch.delenv("ATLASSIAN_CONFLUENCE_URL", raising=False)
    monkeypatch.delenv("ATLASSIAN_CONFLUENCE_PAT", raising=False)
    monkeypatch.delenv("CONFLUENCE_ENABLE_WRITES", raising=False)
    
    loaded = settings_file.load_env_file(path)
    
    assert "ATLASSIAN_CONFLUENCE_URL" in loaded
    assert "CONFLUENCE_ENABLE_WRITES" in loaded
    assert "ATLASSIAN_CONFLUENCE_PAT" not in loaded  # PAT 被过滤
    assert "ATLASSIAN_CONFLUENCE_PAT" not in os.environ  # 环境变量里也没有
```

- [ ] **Step 2: 运行测试验证失败**

Run: `pytest tests/test_settings_file.py::test_load_env_skips_pat_key -v`
Expected: FAIL，PAT 被加载到 os.environ

- [ ] **Step 3: 在 `load_env_file` 里过滤敏感键**

编辑 `src/confluence_mcp/settings_file.py:31-38`，在 for 循环里检查 key：
```python
_SENSITIVE_KEYS = {"ATLASSIAN_CONFLUENCE_PAT", "ATLASSIAN_CONFLUENCE_PASSWORD"}

def load_env_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    loaded = []
    for key, value in parse_env(path.read_text(encoding="utf-8-sig")).items():
        if key in _SENSITIVE_KEYS:
            continue  # 跳过敏感键
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
```

- [ ] **Step 4: 运行测试验证通过**

Run: `pytest tests/test_settings_file.py::test_load_env_skips_pat_key -v`
Expected: PASS

- [ ] **Step 5: 运行全部 settings_file 测试**

Run: `pytest tests/test_settings_file.py -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add src/confluence_mcp/settings_file.py tests/test_settings_file.py
git commit -m "fix(config): skip sensitive keys when loading .env

- ATLASSIAN_CONFLUENCE_PAT and ATLASSIAN_CONFLUENCE_PASSWORD are excluded
- These must come from system credential store or process env only
- Prevents accidental credential leakage via .env file
- Tokens/passwords remain secure per README guidance

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: 添加端到端测试验证 `.env` 影响工具注册

**Files:**
- Modify: `tests/test_registration.py` (append)

**Interfaces:**
- Consumes: `server.mcp`，`settings_file.ENV_FILE_VAR`
- Produces: 测试 `test_env_file_enables_writes_at_startup`

- [ ] **Step 1: 写测试：从 `.env` 文件加载后写工具出现**

```python
def test_env_file_enables_writes_at_startup(tmp_path, monkeypatch):
    """Verify that .env with CONFLUENCE_ENABLE_WRITES=true actually enables writes."""
    # 创建 .env 文件
    env_file = tmp_path / ".env"
    env_file.write_text("CONFLUENCE_ENABLE_WRITES=true\n", encoding="utf-8")
    
    # 指向这个 .env 文件并重新加载 server 模块
    monkeypatch.setenv(settings_file.ENV_FILE_VAR, str(env_file))
    monkeypatch.delenv("CONFLUENCE_ENABLE_WRITES", raising=False)  # 清除进程环境
    
    # 重新加载 settings_file 和 server 模块，重新注册工具
    import importlib
    importlib.reload(settings_file)
    importlib.reload(server)
    
    names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert "create_page" in names, "write tools should be registered from .env"
```

- [ ] **Step 2: 运行测试验证失败（如果当前工作目录的 `.env` 不存在）**

Run: `pytest tests/test_registration.py::test_env_file_enables_writes_at_startup -v`
Expected: 可能 FAIL 或 PASS（取决于工作环境）

- [ ] **Step 3: 补充测试：`.env` 中的行尾注释也要工作**

```python
def test_env_file_with_inline_comment_enables_writes(tmp_path, monkeypatch):
    """Verify inline comments in .env don't break settings."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "CONFLUENCE_ENABLE_WRITES=true # enable writes\n"
        "CONFLUENCE_WRITE_SPACES=OPS # approved space\n",
        encoding="utf-8"
    )
    
    monkeypatch.setenv(settings_file.ENV_FILE_VAR, str(env_file))
    monkeypatch.delenv("CONFLUENCE_ENABLE_WRITES", raising=False)
    monkeypatch.delenv("CONFLUENCE_WRITE_SPACES", raising=False)
    
    import importlib
    importlib.reload(settings_file)
    importlib.reload(server)
    
    names = {tool.name for tool in asyncio.run(server.mcp.list_tools())}
    assert "create_page" in names
    
    # 验证空间白名单也正确解析
    from confluence_mcp import writes
    assert "OPS" in {item.strip() for item in os.environ.get("CONFLUENCE_WRITE_SPACES", "").split(",") if item.strip()}
```

- [ ] **Step 4: 运行两个新测试**

Run: `pytest tests/test_registration.py -k "env_file" -v`
Expected: 全部 PASS

- [ ] **Step 5: 运行全部注册测试**

Run: `pytest tests/test_registration.py -v`
Expected: 全部通过

- [ ] **Step 6: 提交**

```bash
git add tests/test_registration.py
git commit -m "test: add end-to-end tests for .env file loading at startup

- Verify CONFLUENCE_ENABLE_WRITES from .env enables write tools
- Verify inline comments in .env don't break settings parsing
- Ensure full startup path (import→load_env→register) works correctly
- Catches regressions in .env integration

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: 统一版本号至 0.4.0

**Files:**
- Modify: `src/confluence_mcp/__init__.py:8`
- Verify: `pyproject.toml:7` 已是 0.4.0

**Interfaces:**
- Consumes: pyproject.toml 中的版本号
- Produces: 一致的 `__version__ = "0.4.0"`

- [ ] **Step 1: 验证 pyproject.toml**

Run: `grep "^version" pyproject.toml`
Expected: `version = "0.4.0"`

- [ ] **Step 2: 改 `__init__.py` 中的版本**

编辑 `src/confluence_mcp/__init__.py:8`，改为：
```python
__version__ = "0.4.0"
```

- [ ] **Step 3: 验证版本一致**

Run: `grep -r "__version__\|^version" src/confluence_mcp/__init__.py pyproject.toml`
Expected: 两个都是 `0.4.0`

- [ ] **Step 4: 运行测试验证无破坏**

Run: `pytest -q`
Expected: 219 passed

- [ ] **Step 5: 提交**

```bash
git add src/confluence_mcp/__init__.py
git commit -m "chore: align version number with pyproject.toml

- Set __version__ to 0.4.0 to match pyproject.toml
- Version 0.4.0 includes move_page, web approval, queue, and .env loading
- Ensures version consistency across build artifacts

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: 更新文档并删除过时计划

**Files:**
- Modify: `README.md` （多处）
- Delete: `docs/superpowers/plans/2026-11-03-env-file-config.md`

**Interfaces:**
- Consumes: 现有 README 和过时计划
- Produces: 更新的 README，清晰的 `.env` 说明和版本说明

- [ ] **Step 1: 清理 README 中的过时令牌说明**

编辑 `README.md:147`，现在写：
```
- 审批页的令牌在 MCP 进程运行期间有效；进程停止时令牌消失，下次启动生成新令牌。
```

- [ ] **Step 2: 清理 README 中关于 `.env` 的说明**

检查 `README.md:90-94`，确保写法一致：
```
MCP 启动时会读取当前工作目录的 `.env`（参考 `.env.example`）。
进程环境变量优先，`.env` 不会覆盖已设置的值。
文件不存在时静默跳过。
```

并删除关于 `CONFLUENCE_MCP_ENV_FILE` 的说明（测试用，用户无需知道）。

- [ ] **Step 3: 在错误排查章节补充 `.env` 错误**

在 `README.md` 错误排查部分，补充：
```
- .env 行尾注释：`KEY=value # comment` 格式正确；注释必须在 # 前有空白。
- .env 不生效：检查 MCP 的 cwd 是否指向仓库根目录。
```

- [ ] **Step 4: 删除过时计划文档**

Run: `rm docs/superpowers/plans/2026-11-03-env-file-config.md`
Expected: 文件被删除

- [ ] **Step 5: 运行全部测试**

Run: `pytest -q`
Expected: 219 passed

- [ ] **Step 6: 提交**

```bash
git add README.md
git rm docs/superpowers/plans/2026-11-03-env-file-config.md
git commit -m "docs: update .env documentation and clean up outdated plan

- Clarify .env path must be in cwd (set by MCP_HOST config)
- Correct token lifecycle (valid during process life, not one-time)
- Remove reference to CONFLUENCE_MCP_ENV_FILE (internal test hook only)
- Remove outdated plan document describing deleted get_review_link feature
- Add troubleshooting for common .env mistakes

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: 最终验证与合并

**Files:**
- Verify: 全部文件无误
- Test: 全部测试通过

**Interfaces:**
- Consumes: Task 1-6 的改动
- Produces: 可发版的 feat/env-file-config 分支

- [ ] **Step 1: 运行全部测试**

Run: `pytest -q`
Expected: 219 passed

- [ ] **Step 2: 验证 `.env` 行尾注释工作**

创建临时 `.env` 文件测试：
```bash
cd /tmp
printf 'CONFLUENCE_ENABLE_WRITES=true # enable writes\n' > test.env
CONFLUENCE_MCP_ENV_FILE=/tmp/test.env uv run python -c "
import asyncio
from confluence_mcp import server
names = {t.name for t in asyncio.run(server.mcp.list_tools())}
print('create_page in tools:', 'create_page' in names)
"
```
Expected: `create_page in tools: True`

- [ ] **Step 3: 验证 PAT 被过滤**

```bash
cd /tmp
printf 'ATLASSIAN_CONFLUENCE_PAT=secret123\nATLASSIAN_CONFLUENCE_URL=https://wiki.example.com\n' > test.env
CONFLUENCE_MCP_ENV_FILE=/tmp/test.env uv run python -c "
import os
from confluence_mcp import settings_file
os.environ.pop('ATLASSIAN_CONFLUENCE_PAT', None)
settings_file.load_env_file(__import__('pathlib').Path('/tmp/test.env'))
print('PAT in environ:', 'ATLASSIAN_CONFLUENCE_PAT' in os.environ)
print('URL in environ:', 'ATLASSIAN_CONFLUENCE_URL' in os.environ)
"
```
Expected: `PAT in environ: False`, `URL in environ: True`

- [ ] **Step 4: 检查版本一致**

Run: `grep -E "__version__|^version" src/confluence_mcp/__init__.py pyproject.toml`
Expected: 两个都是 `0.4.0`

- [ ] **Step 5: 查看提交历史**

Run: `git log --oneline -7`
Expected: 7 个新提交，每个任务一个

- [ ] **Step 6: 整理分支**

如果需要压缩或重新组织，可选：
```bash
git log -10 --oneline
# 检查是否需要 rebase -i 整理
```

- [ ] **Step 7: 最终提交确认**

Run: `git status`
Expected: 工作区干净，没有未跟踪的改动

---

## Self-Review Checklist

✅ **Spec Coverage:** 
- 行尾注释支持 ✓ (Task 1)
- `.env` 路径修复 ✓ (Task 2)
- PAT 敏感键过滤 ✓ (Task 3)
- 端到端启动测试 ✓ (Task 4)
- 版本号统一 ✓ (Task 5)
- 文档更新与过时文件删除 ✓ (Task 6)
- 最终验证 ✓ (Task 7)

✅ **Step Scanning:** 
每个 Step 都是一个原子操作，实现者能明确地执行。没有"处理边界情况"或"TBD"这样的模糊语句。

✅ **Type Consistency:** 
- `parse_env(text: str) -> dict[str, str]` 一致
- `load_env_file(path: Path) -> list[str]` 一致
- 敏感键集合 `_SENSITIVE_KEYS` 定义清晰

✅ **Review Focus Pinned:** 
1. 行尾注释 → Task 1 (test_strips_trailing_comments_outside_quotes)
2. 发版路径 → Task 2 (DEFAULT_ENV_FILE 改为 Path.cwd())
3. 启动加载 → Task 4 (test_env_file_enables_writes_at_startup)
4. PAT 过滤 → Task 3 (test_load_env_skips_pat_key)
5. 版本号 → Task 5 (统一为 0.4.0)

✅ **Proportion:** 
计划长度与改动量相当（7 个小任务，约 150 行改动代码 + 测试）。没有过度的代码清单，步骤足以指导实现。

