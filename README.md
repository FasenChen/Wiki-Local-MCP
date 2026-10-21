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
- `create_page` / `add_comment`（需开启写操作）：从 Markdown 创建页面或评论；默认 `dry_run=true`，只返回预览。
- `update_page` / `update_page_section`（需开启写操作）：整页或单节更新；必须传 `expected_version`，整页 Markdown 更新默认拒绝含宏页面，单节更新只替换目标章节。
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
Set-Location D:\Code\Wiki-Local-MCP
uv sync
```

### 2. 保存 Confluence PAT

推荐使用 Confluence Personal Access Token（PAT）。运行下面的命令后，在隐藏输入提示中粘贴 PAT；它会保存到当前 Windows 用户的 Credential Manager，不会写入仓库或 Codex 配置：

```powershell
uv run confluence-mcp-store-pat
```

同一 Windows 用户启动的 MCP 进程会从系统凭据库读取 PAT。也可使用环境变量 `ATLASSIAN_CONFLUENCE_PAT`；它优先于凭据库。Basic Auth 可同时设置 `ATLASSIAN_CONFLUENCE_USERNAME` 和 `ATLASSIAN_CONFLUENCE_PASSWORD`。不要将 PAT 或密码写入 `config.toml`。

### 3. 注册到 Codex Desktop

Codex Desktop、Codex CLI 与 IDE 扩展共用个人配置文件：

```text
%USERPROFILE%\.codex\config.toml
```

先保留文件中的现有内容，再把下面配置追加到文件末尾；不要用此示例覆盖整个配置文件：

```toml
[mcp_servers.confluence]
command = "uv"
args = ["run", "confluence-mcp"]
cwd = "D:\\Code\\Wiki-Local-MCP"
startup_timeout_sec = 20
tool_timeout_sec = 60

[mcp_servers.confluence.env]
ATLASSIAN_CONFLUENCE_URL = "https://wiki.example.com/confluence"
```

将示例地址替换成你们 Confluence 的站点根地址，并包含部署使用的上下文路径（如有）；不要在地址后加 `/rest/api`。如果 Codex 找不到 `uv`，将 `command` 替换为 `uv.exe` 的绝对路径。

服务名已从 `confluence_readonly` 改为 `confluence`。Claude Code 用户需要把 `~/.claude.json` 中对应条目的 key 同步改成 `confluence`（只改 key，命令、参数、cwd、env 保持不变）。

也可以在 Codex Desktop 打开 **Settings → MCP Servers → Add Server**，选择 **STDIO**，配置命令、参数、工作目录和环境变量。保存后重启/刷新 MCP 服务器。CLI 可用 `codex mcp list` 查看登记状态。

### 4. 确认连接

在 Codex 的 MCP 工具列表中确认出现 `search_pages`、`get_page` 和 `get_page_by_title`。调用 `search_pages` 搜索一个有权限查看的词，或调用 `get_page` 读取 Page ID。MCP 运行机器必须能通过公司网络/VPN 访问 Confluence。

若公司使用内部 CA，将证书包路径设置到 `ATLASSIAN_CONFLUENCE_CA_BUNDLE`；TLS 验证默认开启，不要关闭验证。服务不会自动读取 `.env` 文件。
## 启用写操作（可选）

默认情况下服务器不注册任何写工具。启用方式是在 MCP 配置的 `env` 中加入：

```toml
CONFLUENCE_ENABLE_WRITES = "true"
CONFLUENCE_WRITE_SPACES = "OPS,QA"   # 可选；不设置表示不限制空间
```

所有写工具默认 `dry_run=true`：只返回将要发生的变更（目标、storage 预览），
调用方确认后再传 `dry_run=false`。真实写入会追加到
`%USERPROFILE%\.confluence-mcp\audit.log`（JSON Lines，不含页面正文和 PAT）。
修改页面时必须提供 `expected_version`，版本不一致会直接报冲突。日常修改优先用 `update_page_section`：它只替换目标章节，页面其余宏和章节原样保留。

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
- 预览评论（不写入）：`add_comment(page_id="123456", content_markdown="评审意见", dry_run=True)`

`section` 只支持 `markdown` / `storage` 输出；`html` 是整个 `body.view`，无法按章节切分。

`html` 返回 Confluence 的 `body.view` 渲染片段；如果服务器未提供该扩展，则回退到 `body.storage`。`markdown` 从 storage XHTML 转换；Confluence 专有宏、图表和应用宏可能无法完全映射为 Markdown，需以 HTML 或原页面查看其渲染结果。

## 权限与故障定位

MCP 不会绕过 Confluence 权限；结果只包含 PAT 所属用户能读取的内容。对内网 Confluence 的请求由启动 MCP 的机器发出，因此 Codex 必须运行在能访问公司网络/VPN 的本地环境。把服务器改为远端运行时，远端也必须能访问该内网地址。

- `401`：检查 PAT 是否有效/过期，或 Basic Auth 是否完整。
- `403`：检查账号对 Space 和页面限制是否有读取权限；写操作还需检查 `CONFLUENCE_WRITE_SPACES` 与 Space 的编辑限制。
- `404`：检查 Page ID 与根地址上下文路径；无权查看的页面也可能表现为不可用。
- TLS/连接错误：检查 VPN、DNS、代理与 `ATLASSIAN_CONFLUENCE_CA_BUNDLE`。
- 重定向错误：确认 `ATLASSIAN_CONFLUENCE_URL` 指向实际 Confluence 根地址，而非登录页、反向代理跳转地址或 `/rest/api`。

服务不会自动读取 `.env` 文件。不要把 PAT、密码或公司页面内容写入仓库文件、提交到 GitHub 或输出到日志；优先使用系统凭据库。

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
