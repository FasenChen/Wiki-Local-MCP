# Confluence MCP

面向本地部署的 Atlassian Confluence Data Center 8.5.15 的 MCP 工具。MCP 进程在本机运行，通过 Confluence REST API 访问当前账号有权查看的内容。默认只注册读工具；写工具需要通过环境变量显式开启，且默认 `dry_run`。

## 能力

- `search_pages`：按页面正文/标题中的文本查找页面，可限定 Space Key。
- `get_page`：按 Page ID 读取页面。
- `get_page_by_title`：按精确标题读取页面；重名时要求提供 Space Key。
- `cql_search`：直接执行 CQL，支持标签、时间、作者、空间组合查询；返回 excerpt 与分页 `next_start`。
- `get_page_outline`：只返回 h1–h6 标题树，适合先看结构再决定读哪一节。
- `get_page` 新增 `section` 与 `max_chars`：按标题只读一节；超长内容截断并返回 `truncated`。
- `list_spaces`：列出可见的全局 Space，便于找到 `space_key`。
- `get_comments`：读取页面评论并转 Markdown，保留回复的父评论 ID。
- `get_children`：读取子页面树，最多 3 层，单次调用总节点上限 200。
- `get_page_history`：列出版本历史，或对两个版本做 Markdown diff（默认 4000 字符上限）。8.5.15 实测 `/rest/api/content/{id}/version` 可用；不可用时自动回退到 `/rest/experimental`。
- `create_page` / `add_comment`（需开启写操作）：从 Markdown 创建页面或评论；默认 `dry_run=true` 只返回预览，`dry_run=false` 入队等待人工审批。
- `update_page` / `update_page_section`（需开启写操作）：整页或单节更新；必须传 `expected_version`，整页 Markdown 更新默认拒绝含宏页面，单节更新只替换目标章节；`dry_run=false` 入队等待人工审批。
- `move_page`（需开启写操作）：调整页面在页面树中的位置，不修改正文。`position="before"` / `"after"` 把页面放到同级页面 `target_page_id` 的前/后（会随之改到该页面的父页面下）；`position="append"` 把页面移到 `target_page_id` 下作为最后一个子页面。只支持同一空间内移动，不支持移到空间根目录。`dry_run=true` 返回移动前后的同级顺序；`dry_run=false` 入队等待人工审批，批准后调用 `PUT /rest/api/content/{id}/move/{position}/{targetId}`。要排好多个页面，按顺序入队多条移动，批准时按队列顺序执行。
- `list_queued_operations` / `get_queued_operations` / `cancel_queued_operations` / `get_execution_log`（需开启写操作）：查看自己入队的操作和 diff 预览、撤回尚未审批（`pending`）的操作、读取已结束操作的结果。MCP 无法批准或执行任何操作，也无法撤回已批准的操作。
- 页面内容可返回 Markdown、Confluence 渲染 HTML 或原始 storage XHTML。

页面 ID 可从页面链接中的 `pageId` 参数，或从 `.../pages/<数字>/...` 路径中取得。也可以先用 `search_pages` 或 `get_page_by_title` 查找页面。

## 运行环境

- Windows、macOS 或 Linux
- Python 3.10 或更高版本
- [`uv`](https://docs.astral.sh/uv/)
- MCP Host 与 Confluence 之间可达的网络/VPN 路由
- Confluence Data Center PAT，且该账号有目标 Space/Page 的读取权限；使用写工具时还需要目标 Space 的编辑权限

Confluence 8.5.15 使用 Server/Data Center REST API v1。页面读取通过 `GET /rest/api/content/{id}?expand=body.storage,body.view,version,space,ancestors` 完成；搜索通过 `GET /rest/api/content/search` 完成。默认只发起 `GET` 请求；开启写操作后才会发起 `POST` / `PUT`。

## 安装和认证

### 1. 安装依赖

在 PowerShell 中进入仓库目录并同步依赖：

```powershell
Set-Location D:\AI\MCP\Wiki-Local-MCP
uv sync
```

### 2. 保存 Confluence PAT

推荐使用 Confluence Personal Access Token（PAT）。运行下面的命令后，在隐藏输入提示中粘贴 PAT；它会保存到当前 Windows 用户的 Credential Manager，不会写入仓库或 Codex 配置：

```powershell
uv run confluence-mcp-store-pat
```

同一 Windows 用户启动的 MCP 进程会从系统凭据库读取 PAT，服务名为 `confluence-mcp`，用户名为 `pat`。升级已有安装后，如原凭据保存在其他服务名下，需迁移凭据或重新运行上述命令保存 PAT。也可使用环境变量 `ATLASSIAN_CONFLUENCE_PAT`；它优先于凭据库。不要将 PAT 或密码写入 `config.toml`。

### 3. 注册到 Codex Desktop

Codex Desktop、Codex CLI 与 IDE 扩展共用个人配置文件：

```text
%USERPROFILE%\.codex\config.toml
```

先保留文件中的现有内容，再把下面配置追加到文件末尾；不要用此示例覆盖整个配置文件：

```toml
[mcp_servers.wiki-local-mcp]
command = "uv"
args = ["run", "confluence-mcp"]
cwd = "D:\\AI\\MCP\\Wiki-Local-MCP"
startup_timeout_sec = 20
tool_timeout_sec = 60

[mcp_servers.wiki-local-mcp.env]
ATLASSIAN_CONFLUENCE_URL = "https://wiki.example.com/confluence"
```

将示例地址替换成你们 Confluence 的站点根地址，并包含部署使用的上下文路径（如有）；不要在地址后加 `/rest/api`。如果 Codex 找不到 `uv`，将 `command` 替换为 `uv.exe` 的绝对路径。

MCP Host 的注册别名统一使用 `wiki-local-mcp`。Claude Code 用户在 `~/.claude.json` 中使用同名 key；已有配置更名时只改 key，保留命令、参数、cwd、env。

也可以在 Codex Desktop 打开 **Settings → MCP Servers → Add Server**，选择 **STDIO**，配置命令、参数、工作目录和环境变量。保存后重启/刷新 MCP 服务器。CLI 可用 `codex mcp list` 查看登记状态。

### 4. 确认连接

在 Codex 的 MCP 工具列表中确认出现 `search_pages`、`get_page` 和 `get_page_by_title`。调用 `search_pages` 搜索一个有权限查看的词，或调用 `get_page` 读取 Page ID。MCP 运行机器必须能通过公司网络/VPN 访问 Confluence。

若公司使用内部 CA，将证书包路径设置到 `ATLASSIAN_CONFLUENCE_CA_BUNDLE`；TLS 验证默认开启，不要关闭验证。

## 本地配置文件 `.env`（可选）

MCP 启动时会读取工作目录（MCP 配置里的 `cwd`，应指向仓库根目录）下的 `.env`（参考 `.env.example`）。进程环境变量优先，`.env` 不会覆盖已设置的值。`.env` 不读取 PAT，PAT 只能来自系统凭据库或进程环境变量。

- 文件不存在时静默跳过。行尾注释需要 `#` 前有空格，例如 `CONFLUENCE_WRITE_SPACES=OPS # 已批准`。

## 启用写操作与人工审批（可选）

默认情况下服务器不注册任何写工具。启用方式是在 MCP 配置的 `env` 中加入：

```toml
CONFLUENCE_ENABLE_WRITES = "true"
CONFLUENCE_WRITE_SPACES = "OPS,QA"   # 可选；不设置表示不限制空间
```

所有写工具默认 `dry_run=true`：只返回将要发生的变更（目标、storage 预览）。
传 `dry_run=false` 不会写入 Confluence，而是把最终请求 payload 存入本地队列
`%USERPROFILE%\.confluence-mcp\queue.sqlite3`，状态为 `pending`。

流程：

1. 写工具 `dry_run=false` → 入队，返回 `operation_id` 和 `pending` 状态。
2. 在你自己的终端里审批（需要真实的交互式控制台，Agent 无法替你启动），二选一：
   - 网页：`uv run confluence-mcp-review web`。在本机 `127.0.0.1` 打开审批页。
     - 左侧队列：卡片标题是页面标题（章节更新显示章节名），标签显示动作、空间和状态，并列出操作 ID。用 Tab 聚焦后按 Enter/空格选中。
     - 左右分栏默认约 3:7。拖动中间的分隔条；也可以用头部的“收窄队列 / 加宽队列 / 恢复默认”按钮（每次 5%）；聚焦分隔条后用左右方向键（每次 2%），Home/End 为最小/最大。可调范围受最小宽度限制（队列 260px，详情 380px），分隔条的 ARIA 数值与之一致。窄窗口（≤760px）改为上下排列，队列较矮，详情区独立滚动。偏好保存在 `cmr_split` 这个普通偏好 Cookie 中（仅本机 host，非 HttpOnly，值经过校验），因此重启 `web`（端口变化）后仍保留。审批会话 Cookie 不被读取或修改。
     - 来源：如果正文开头的引用块（`> 原文归档：…`、`> 来源：[名称](URL)`）里有这两个明确标签，队列卡片显示归档标签，右侧标出原文 URL 和上级目录，并与 Wiki 目标位置分开。只识别这种开头的标签行，正文中的其他链接一律不当作来源；无效或带凭据的 URL 不显示。队列中没有单独的来源字段。
     - 位置：新建页面显示目标父页面的完整路径和新页面名称；整页或章节更新显示原页面的完整路径（可点击打开）；评论显示所在页面。选中某条时才读取一次位置，列表自动刷新不会重复读取；读取失败会标明“暂不可用”，不影响批准。
     - 正文三个标签：“预览”（默认）是即将写入的正文，“源码”是提交给 Confluence 的 storage XHTML，“改动记录”是入队时保存的 diff（更新）或 Markdown 原文（新建/评论）。
     - 预览的限制：它是本地近似渲染，只还原标题、段落、列表、表格、`code` 宏和外部图片（`ac:image` 的 `ac:alt` 会保留）。其他宏、附件、样式、布局和权限以 Confluence 页面为准，未还原的宏会在预览中标出。预览旁边常驻一行“本地近似预览”提示，展开可看完整说明。预览在隔离的沙箱中显示，不执行脚本、不能访问审批接口。正文里的链接显示为文字和地址，不可点击。
     - 右侧的“批准”会立即写入 Confluence，“全部批准”会先确认条数。会话失效或写入进行中时，所有写入按钮都会禁用。
   - 终端：`uv run confluence-mcp-review approve <id>`。不带 id 表示审批全部 `pending`，
     需输入 `yes`，确认后立即写入。

   `uv run confluence-mcp-review`（等同 `list`）查看队列；`reject <id>` 可随时拒绝，无需交互式终端。
   `web` 和 `approve` 都要求设置 `CONFLUENCE_ENABLE_WRITES=true`。
3. 批准即写入：每条操作最多发送一次，失败不自动重试。原来的 `apply_approved_operations` 工具已移除。
   Agent 可以用 `list_queued_operations` 看队列，用 `cancel_queued_operations` 撤回尚未审批的操作。

状态：`pending`（待审批）、`approved`（已批准）、`rejected`（已拒绝）、
`executing`（正在发送）、`succeeded`（已成功）、`failed`（Confluence 明确拒绝，
例如版本冲突 409）、`indeterminate`（结果未知，例如超时）。

`indeterminate` 和卡在 `executing` 的操作永远不会自动重试：先到 Confluence
确认页面是否已被修改，再决定手动处理。批量写入遇到 `indeterminate` 会立即停止，
其余未处理的操作保持 `pending`。启动 `web` 时，超过 5 分钟仍是 `executing` 的操作会被改成
`indeterminate`（说明写入过程中进程中断过）。更新请求携带入队时绑定的
`version.number = 当前版本 + 1`；如果页面在审批期间被他人修改，Confluence 返回
409，该操作变为 `failed`，不会覆盖新版本。

成功执行的写入会追加到 `%USERPROFILE%\.confluence-mcp\audit.log`
（JSON Lines，不含页面正文和 PAT）。

已知边界：

- 该队列阻止的是通过 MCP 的提示注入或误写。它不能阻止一个拥有 shell、
  能以同一 OS 用户运行、能附加 PTY 或读取 PAT 的 agent；Jira-local-MCP 也有同样的限制。
- 审批页的令牌只在该 `web` 进程运行期间有效，只能挡住别的网页和别的机器，挡不住本机上权限相同的恶意进程。
- SQLite 队列和审计日志不防同一系统用户的篡改，不是不可抵赖的审计，不要把它当作生产级审计记录。
- 队列数据库有版本号（`PRAGMA user_version`）。遇到不认识的版本或表结构会拒绝打开并报出文件路径，
  不做自动迁移；请先检查或移走该文件。

## 常用调用

- 查找页面：`search_pages(query="发布流程", space_key="OPS", limit=10)`
- 读取页面并转 Markdown：`get_page(page_id="123456", output_format="markdown")`
- 按标题读取并转 HTML：`get_page_by_title(title="发布流程", space_key="OPS", output_format="html")`
- 返回 Confluence 原始存储格式：`get_page(page_id="123456", output_format="storage")`
- 按标签检索：`cql_search(cql='label = "release" and lastmodified > now("-7d")')`
- 看页面结构：`get_page_outline(page_id="123456")`
- 只读一节：`get_page(page_id="123456", section="部署步骤")`
- 限制长度：`get_page(page_id="123456", max_chars=4000)`
- 预览创建页面（不写入）：`create_page(space_key="OPS", title="标题", content_markdown="## 内容", dry_run=True)`
- 排队创建页面（待人工审批）：`create_page(space_key="OPS", title="标题", content_markdown="## 内容", dry_run=False)`
- 预览评论（不写入）：`add_comment(page_id="123456", content_markdown="评审意见", dry_run=True)`
- 排队评论（待人工审批）：`add_comment(page_id="123456", content_markdown="评审意见", dry_run=False)`
- 查看待审批队列：终端运行 `uv run confluence-mcp-review`
- 网页审批并写入：终端运行 `uv run confluence-mcp-review web`
- 看自己入队的操作：`list_queued_operations()`；撤回未审批的：`cancel_queued_operations(operation_ids=["..."])`

`section` 只支持 `markdown` / `storage` 输出；`html` 是整个 `body.view`，无法按章节切分。

`html` 返回 Confluence 的 `body.view` 渲染片段；如果服务器未提供该扩展，则回退到 `body.storage`。`markdown` 从 storage XHTML 转换；Confluence 专有宏、图表和应用宏可能无法完全映射为 Markdown，需以 HTML 或原页面查看其渲染结果。

## 权限与故障定位

MCP 不会绕过 Confluence 权限；结果只包含 PAT 所属用户能读取的内容。对内网 Confluence 的请求由启动 MCP 的机器发出，因此 Codex 必须运行在能访问公司网络/VPN 的本地环境。把服务器改为远端运行时，远端也必须能访问该内网地址。

- `401`：检查 PAT 是否有效/过期。
- `403`：检查账号对 Space 和页面限制是否有读取权限；写操作还需检查 `CONFLUENCE_WRITE_SPACES` 与 Space 的编辑限制。
- `404`：检查 Page ID 与根地址上下文路径；无权查看的页面也可能表现为不可用。
- TLS/连接错误：检查 VPN、DNS、代理与 `ATLASSIAN_CONFLUENCE_CA_BUNDLE`。
- 重定向错误：确认 `ATLASSIAN_CONFLUENCE_URL` 指向实际 Confluence 根地址，而非登录页、反向代理跳转地址或 `/rest/api`。

服务启动时会读取工作目录下的 `.env`（见上文“本地配置文件”）。如果 `.env` 没生效，检查 `cwd` 是否指向仓库根目录。不要把 PAT、密码或公司页面内容写入仓库文件、提交到 GitHub 或输出到日志；优先使用系统凭据库。

## 开发

```powershell
uv sync
uv run confluence-mcp
```

第二条命令会启动 stdio MCP 进程并等待 MCP Host 请求，需由 MCP 客户端管理进程生命周期。

## 官方接口依据

写工具沿用 PAT 的权限，不会绕过 Confluence 的编辑限制。

- [Atlassian：Confluence Data Center REST API](https://developer.atlassian.com/server/confluence/rest/v923/)
- [Atlassian：REST API expansions](https://developer.atlassian.com/server/confluence/expansions-in-the-rest-api/)
- [Atlassian：使用 REST API 读取页面内容](https://support.atlassian.com/confluence/kb/how-to-get-page-content-or-child-list-via-rest-api/)
- [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk)
