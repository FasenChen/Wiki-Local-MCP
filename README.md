# Confluence Read-only MCP

面向本地部署的 Atlassian Confluence Data Center 8.5.15，提供只读 MCP 工具。MCP 进程在本机运行，通过 Confluence REST API 读取当前账号有权查看的页面；不提供创建、编辑、删除等写入操作。

## 能力

- `search_pages`：按页面正文/标题中的文本查找页面，可限定 Space Key。
- `get_page`：按 Page ID 读取页面。
- `get_page_by_title`：按精确标题读取页面；重名时要求提供 Space Key。
- 页面内容可返回 Markdown、Confluence 渲染 HTML 或原始 storage XHTML。

页面 ID 可从页面链接中的 `pageId` 参数，或从 `.../pages/<数字>/...` 路径中取得。也可以先用 `search_pages` 或 `get_page_by_title` 查找页面。

## 运行环境

- Windows、macOS 或 Linux
- Python 3.10 或更高版本
- [`uv`](https://docs.astral.sh/uv/)
- MCP Host 与 Confluence 之间可达的网络/VPN 路由
- Confluence Data Center PAT，且该账号有目标 Space/Page 的读取权限

Confluence 8.5.15 使用 Server/Data Center REST API v1。页面读取通过 `GET /rest/api/content/{id}?expand=body.storage,body.view,version,space,ancestors` 完成；搜索通过 `GET /rest/api/content/search` 完成。MCP 对上游 REST API 只发起 `GET` 请求。

## 安装和认证

在仓库根目录执行：

```powershell
uv sync
```

将 Confluence 根地址设置为 `ATLASSIAN_CONFLUENCE_URL`。地址需要包含部署时使用的上下文路径，例如 `https://wiki.example.com/confluence`；不要把 `/rest/api` 加到地址末尾。

```powershell
$env:ATLASSIAN_CONFLUENCE_URL = "https://wiki.example.com/confluence"
```

推荐使用 Confluence Personal Access Token（PAT）。在当前 Windows 用户的凭据库中安全保存 PAT；输入内容不会显示：

```powershell
uv run confluence-mcp-store-pat
```

该命令把 PAT 存到当前用户操作系统凭据库（Windows Credential Manager）。MCP 进程在相同 Windows 用户下运行时会读取它。也可用环境变量 `ATLASSIAN_CONFLUENCE_PAT` 提供 PAT；环境变量优先于凭据库。Basic Auth 可通过 `ATLASSIAN_CONFLUENCE_USERNAME` 与 `ATLASSIAN_CONFLUENCE_PASSWORD` 同时设置。

如果公司使用内部 CA，将证书包路径放在 `ATLASSIAN_CONFLUENCE_CA_BUNDLE`。TLS 证书验证默认开启，不要通过关闭验证来绕过企业证书配置。

## 注册到 Codex Desktop

Codex Desktop、Codex CLI 与 IDE 扩展共用 MCP 配置。打开 Codex 设置中的 `config.toml`，合并以下配置，并替换 Confluence 地址：

```toml
[mcp_servers.confluence_readonly]
command = "uv"
args = ["run", "confluence-mcp"]
cwd = "D:\\Code\\Wiki-MCP-Local"
startup_timeout_sec = 20
tool_timeout_sec = 60

[mcp_servers.confluence_readonly.env]
ATLASSIAN_CONFLUENCE_URL = "https://wiki.example.com/confluence"
```

PAT 不写入 `config.toml`。在 Codex Desktop 的 MCP 设置中重启/刷新服务器；随后可从工具列表调用 `search_pages`、`get_page` 和 `get_page_by_title`。项目级配置也可放在仓库的 `.codex/config.toml`，但只会在 Codex 信任该项目时加载。

## 常用调用

- 查找页面：`search_pages(query="发布流程", space_key="OPS", limit=10)`
- 读取页面并转 Markdown：`get_page(page_id="123456", output_format="markdown")`
- 按标题读取并转 HTML：`get_page_by_title(title="发布流程", space_key="OPS", output_format="html")`
- 返回 Confluence 原始存储格式：`get_page(page_id="123456", output_format="storage")`

`html` 返回 Confluence 的 `body.view` 渲染片段；如果服务器未提供该扩展，则回退到 `body.storage`。`markdown` 从 storage XHTML 转换；Confluence 专有宏、图表和应用宏可能无法完全映射为 Markdown，需以 HTML 或原页面查看其渲染结果。

## 权限与故障定位

MCP 不会绕过 Confluence 权限；结果只包含 PAT 所属用户能读取的内容。对内网 Confluence 的请求由启动 MCP 的机器发出，因此 Codex 必须运行在能访问公司网络/VPN 的本地环境。把服务器改为远端运行时，远端也必须能访问该内网地址。

- `401`：检查 PAT 是否有效/过期，或 Basic Auth 是否完整。
- `403`：检查账号对 Space 和页面限制是否有读取权限。
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

- [Atlassian：Confluence Data Center REST API](https://developer.atlassian.com/server/confluence/rest/v923/)
- [Atlassian：REST API expansions](https://developer.atlassian.com/server/confluence/expansions-in-the-rest-api/)
- [Atlassian：使用 REST API 读取页面内容](https://support.atlassian.com/confluence/kb/how-to-get-page-content-or-child-list-via-rest-api/)
- [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk)
