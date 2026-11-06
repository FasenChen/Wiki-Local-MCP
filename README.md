# Confluence MCP

面向本地部署的 Atlassian Confluence Data Center 8.5.15 的 MCP 工具。MCP 进程在本机运行，通过 Confluence REST API 访问当前账号有权查看的内容。默认只注册读工具；写工具需要在项目根目录的 `.env` 中显式开启，且默认 `dry_run`。

当前版本：**V1.0.0**（2026-11-06）

V1.0 首个稳定发布包含：

- Windows、macOS 和 Linux 的安装引导、虚拟环境创建、依赖安装及只读 Wiki 身份检查。
- 从项目根目录 `.env` 读取 Wiki 地址、PAT、CA 和写入开关，默认关闭写工具并保留人工审批流程。
- 为 Codex、Claude Code、WorkBuddy 和 DeepSeek Harness 生成 Agent 接入文档，并提供手动注册示例。
- 支持 Markdown 图片上传、Confluence 附件引用、页面/章节更新、评论、移动页面、历史版本和 Markdown diff。
- 提供本地审批队列、命令行审批、网页审批入口，以及基于已提交快照构建跨平台 ZIP 发布包。

## 安装和使用

整个流程是：准备 Python 和 PAT → 解压安装包 → 运行安装脚本并在控制台填写配置 → 接入 Agent → 进行只读查询。

### 1. 准备环境和 PAT

- Windows、macOS 或 Linux，以及 Python 3.10 或更高版本。首次安装依赖时需要能访问 Python 软件源。
- 可以访问 Confluence 的网络；内网 Wiki 通常需要连接公司网络或 VPN。
- Confluence Data Center 地址和个人访问令牌（PAT）。令牌沿用所属账号的 Wiki 权限。

可在终端检查 Python 版本：Windows 运行 `py -3 --version`，若没有 `py` 则尝试 `python --version`；macOS / Linux 运行 `python3 --version`。没有符合版本的 Python 时，请先从 [Python 官网](https://www.python.org/downloads/)或组织提供的软件源安装。

获取 PAT：登录 Confluence，选择右上角头像 → **设置（Settings）** → **个人访问令牌（Personal access tokens）**，创建令牌并在关闭窗口前复制。界面入口可能因组织配置而不同；详见 [Atlassian 官方说明](https://confluence.atlassian.com/enterprise/using-personal-access-tokens-1026032365.html)。

### 2. 获取并解压安装包

获取项目提供的跨平台 ZIP；项目发布后也可从 [GitHub Releases](https://github.com/FasenChen/Wiki-Local-MCP/releases) 下载。将 ZIP 解压到计划长期使用的新目录，例如 Windows 的 `D:\Apps\Wiki-Local-MCP` 或 macOS 的 `/Users/yourname/Apps/Wiki-Local-MCP`。如果发布页没有安装包，请向提供方获取。

解压后的目录应能直接看到 `setup.bat`、`setup.command`、`.env.example` 等文件；下文的“项目目录”均指这些文件所在的目录。不要在压缩包内部直接运行安装脚本。

### 3. 运行安装脚本并填写配置

**Windows：**双击项目目录中的 `setup.bat`。

**macOS：**双击项目目录中的 `setup.command`。若提示没有执行权限，在终端运行 `chmod +x "/完整路径/setup.command"` 后重试；如果 macOS 对下载文件显示安全提示，请按组织策略及 [Apple 说明](https://support.apple.com/en-us/102445)处理。

按控制台提示填写 Wiki 地址和 PAT：

```text
====== Wiki 连接配置 ======
Wiki 地址（必填）：https://wiki.example.com/confluence
PAT（必填，输入不显示）：
```

把示例地址替换为自己的地址，并在 PAT 提示后粘贴自己的令牌、按 Enter；**输入时不会显示任何字符**。地址应包含实际的上下文路径（如 `/confluence`），不要附加 `/rest/api`。

如果显示“已配置”，直接按 Enter 保留已有值；输入新值可更新。脚本只更新地址和 PAT，保留 `.env` 中已有的 CA、写入开关、空间配置和其他内容。若终端无法隐藏 PAT 输入，脚本会停止并提示使用系统终端。

配置保存在项目目录的 `.env` 中，也可以自行编辑。macOS 的 Finder 默认隐藏它，可按 `Command + Shift + .` 显示隐藏文件。PAT 是明文保存的，不要分享填写后的目录、提交 `.env` 或把 PAT 发给 Agent。

### 4. 检查安装结果

1. 配置完成后，控制台立即显示 `====== 环境配置 ======`。脚本创建或复用项目内的 `.venv`，安装固定版本依赖，再分别检查 MCP 只读工具加载和 Wiki 身份认证。
2. 看到 `检查 MCP 工具完成。`、`Confluence authentication succeeded.` 和 `检查 Wiki 认证完成。`，表示这些安装检查已通过。检查只发送读取请求；认证成功不代表账号对所有空间都有权限。
3. 安装结束时按 Enter 退出。以后需要更新配置时，可重新运行安装脚本，在结束时输入 `E` 重新填写；修改配置后重启 MCP 和正在运行的审批服务，并可重新运行安装检查。
4. 所有检查通过后，脚本在项目目录生成 `MCP_SETUP.md`，并显示它的完整路径。下一步将这个文件发给 Agent。

环境配置期间显示阶段进度和结果，pip 版本及依赖下载、构建明细会隐藏。首次安装依赖可能需要几分钟，失败时显示对应阶段的简短提示。

### 升级或移动已有安装

之前保存在系统凭据库中的 PAT 不会删除，但新版不再读取；如旧配置文件没有 PAT，需要自行填写。移动项目目录后，请重新运行安装并更新客户端中的绝对路径；若已有 `.venv` 不可用，脚本会提示处理，不会自动删除。不要在不同电脑或操作系统之间复制 `.venv`。

Windows 路径过深时可能无法创建完整的 `.venv`；请尝试将项目放到较短路径，并自行处理未完成的虚拟环境后重新安装。

升级已有安装时，先备份旧目录的 `.env`，然后将新版 ZIP 解压到新目录，不要覆盖旧目录：ZIP 内自带空白 `.env`，覆盖解压会替换旧配置。将旧 `.env` 复制到新目录，替换空白模板；如旧版本使用系统凭据库，还需自行填写 PAT。macOS 可在 Finder 中按 `Command + Shift + .` 显示隐藏文件。不要复制旧 `.venv`，在新目录运行安装并更新客户端路径；确认新版可用后再处理旧目录。同一用户的队列和审计记录保存在用户主目录的 `.confluence-mcp` 中。

### Linux 手动安装

在项目目录中执行，保留已存在的 `.env`：

```bash
cp -n .env.example .env
python3 -m venv .venv
.venv/bin/python -m pip install -c constraints.txt -e .
```

编辑 `.env` 并保存地址和 PAT，再执行 `.venv/bin/python -m confluence_mcp.healthcheck`。需要内部 CA 时，在 `.env` 设置 `ATLASSIAN_CONFLUENCE_CA_BUNDLE`，不要关闭 TLS 验证。上述命令也适用于 macOS；Windows 手动安装时可先运行 `python -m venv .venv`，再使用下方开发命令和 `.env.example`。

Linux 也可在项目目录运行 `python3 scripts/install.py`，使用相同的控制台安装引导并生成 `MCP_SETUP.md`。

### 5. 让 Agent 配置 MCP

把安装成功后生成的 **`MCP_SETUP.md` 作为附件发给当前 Agent**，即可请求它配置 Wiki MCP。

文档已经填写本机操作系统、项目目录、Python 启动路径及参数，并包含 WorkBuddy、DSH、Codex 和 Claude Code 的接入步骤。Agent 会识别当前客户端，保留其他配置，再检查工具是否加载。

该文件只包含本机接入信息。PAT 保存在项目 `.env` 中。移动安装目录后，重新运行 setup 并使用新生成的文档。

自动配置需要 Agent 有本机文件访问和配置写入权限。权限不足时，文档会引导 Agent 提供可粘贴配置和具体放置位置。客户端需要重启或重载时，由 Agent 说明对应操作。

### 手动注册示例

以下路径只是示例，请替换为自己的解压目录。Windows 的 Python 为 `<目录>\.venv\Scripts\python.exe`，macOS/Linux 为 `<目录>/.venv/bin/python`；参数均为 `-m confluence_mcp.server`。无需配置工作目录，也不要在客户端配置里填写 PAT。

#### Codex / Claude Code

Windows PowerShell：

```powershell
codex mcp add wiki-local-mcp -- "D:\Code\Wiki-Local-MCP\.venv\Scripts\python.exe" -m confluence_mcp.server
claude mcp add --scope user wiki-local-mcp -- "D:\Code\Wiki-Local-MCP\.venv\Scripts\python.exe" -m confluence_mcp.server
```

macOS 示例（Linux 请替换为自己的项目目录）：

```bash
codex mcp add wiki-local-mcp -- "/Users/yourname/Wiki-Local-MCP/.venv/bin/python" -m confluence_mcp.server
claude mcp add --scope user wiki-local-mcp -- "/Users/yourname/Wiki-Local-MCP/.venv/bin/python" -m confluence_mcp.server
```

使用 `codex mcp list` 或 `claude mcp list` 查看注册状态。Claude Code 的 `--scope user` 为用户级；若只需当前项目，请按客户端文档选择相应作用域。

#### WorkBuddy 和其他 JSON 客户端

WorkBuddy 可通过 **插件 → MCP 服务器 → 配置 MCP** 添加。以下是 Windows 示例；macOS 将 `command` 替换为 `/Users/yourname/Wiki-Local-MCP/.venv/bin/python`：

```json
{
  "mcpServers": {
    "wiki-local-mcp": {
      "type": "stdio",
      "command": "D:\\Code\\Wiki-Local-MCP\\.venv\\Scripts\\python.exe",
      "args": ["-m", "confluence_mcp.server"]
    }
  }
}
```

WorkBuddy 用户级配置通常位于 `~/.workbuddy/mcp.json`；其他 JSON 客户端的配置位置请参照其文档。合并新条目，保留原有配置。

#### DeepSeek Harness

按当前 profile 的 `cordis.patch.yml` 合并以下 `insert`；示例使用 Windows 路径，macOS 替换为对应 `.venv/bin/python`：

```yaml
- insert:
    - id: mcp-confluence
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: wiki-local-mcp
        transport: stdio
        command: 'D:\Code\Wiki-Local-MCP\.venv\Scripts\python.exe'
        args: ['-m', 'confluence_mcp.server']
```

用户级 patch 的位置和插件可用性以所用 DSH 版本为准，参考 [DSH 官方示例](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/mcp-memory.md)。保留其他 patch，重载或重启后检查 `mcp__wiki-local-mcp__` 开头的工具。

### 6. 验证并开始使用

在客户端确认 `search_pages`、`get_page`、`get_page_by_title` 已加载。可以在 Agent 中发送下面的请求，把示例词替换为自己有权限查看的内容：

```text
请使用 wiki-local-mcp 搜索包含“发布流程”的 Wiki 页面，列出标题和链接；只读，不要修改页面。
```

Agent 找到页面后，可以继续要求“读取其中的页面并总结主要步骤”。也可以提供页面链接或 Page ID，让 Agent 直接读取。搜索结果只包含 PAT 所属账号有权限查看的内容。

安装脚本的认证检查、客户端加载工具和实际读取目标页面是不同步骤；工具未出现时先重启客户端并检查本机启动路径。默认只启用读取；需要创建或修改页面时，先看下方的[启用写操作与人工审批](#启用写操作与人工审批可选)。

## 本地配置文件 `.env`

MCP 和审批工具只从源码项目根目录的 `.env`（参考 `.env.example`）读取地址、PAT、CA、写开关和空间白名单。启动目录、`CONFLUENCE_MCP_ENV_FILE` 及同名进程环境变量不会改变这些设置。

| 配置项 | 是否必填 | 用途 |
| --- | --- | --- |
| `ATLASSIAN_CONFLUENCE_URL` | 是 | Wiki 根地址，包含实际上下文路径。 |
| `ATLASSIAN_CONFLUENCE_PAT` | 是 | 当前账号的 Confluence Data Center PAT。 |
| `ATLASSIAN_CONFLUENCE_CA_BUNDLE` | 否 | 内部 CA 证书文件路径；TLS 验证保持开启。 |
| `CONFLUENCE_ENABLE_WRITES` | 否 | 设置为 `true` 后注册写工具；默认关闭。 |
| `CONFLUENCE_WRITE_SPACES` | 否 | 可写 Space Key，多个用逗号分隔；留空不限制空间。 |

- 文件不存在时按空配置处理，写操作默认关闭；使用连接功能前仍需配置 URL 和 PAT。行尾注释需要 `#` 前有空格，例如 `CONFLUENCE_WRITE_SPACES=OPS # 已批准`。
- 每个进程首次使用配置时读取一次；修改 `.env` 后需重启 MCP 和正在运行的审批服务。
- 此定位方式适用于上述源码／可编辑安装。脱离源码的普通 wheel 安装没有本方案定义的项目根目录，需另行约定配置位置。

## 启用写操作与人工审批（可选）

默认情况下服务器不注册任何写工具。启用方式是在项目根目录的 `.env` 中加入以下配置，然后重启 MCP：

```text
CONFLUENCE_ENABLE_WRITES=true
CONFLUENCE_WRITE_SPACES=OPS,QA   # 可选；不设置表示不限制空间
```

所有写工具默认 `dry_run=true`：只返回将要发生的变更（目标、storage 预览）。
传 `dry_run=false` 不会写入 Confluence，而是把最终请求 payload 存入本地队列
`%USERPROFILE%\.confluence-mcp\queue.sqlite3`，状态为 `pending`。
macOS / Linux 路径为 `~/.confluence-mcp/queue.sqlite3`。

流程：

1. 写工具 `dry_run=false` → 入队，返回 `operation_id` 和 `pending` 状态。
2. 在你自己的终端里审批（需要真实的交互式控制台，Agent 无法替你启动），二选一：
   - 网页：在仓库根目录运行 `.\.venv\Scripts\confluence-mcp-review.exe web`。在本机 `127.0.0.1` 打开审批页。
     - 左侧队列：卡片标题是页面标题（章节更新显示章节名），标签显示动作、空间和状态，并列出操作 ID。用 Tab 聚焦后按 Enter/空格选中。
     - 左右分栏默认约 3:7。拖动中间的分隔条；也可以用头部的“收窄队列 / 加宽队列 / 恢复默认”按钮（每次 5%）；聚焦分隔条后用左右方向键（每次 2%），Home/End 为最小/最大。可调范围受最小宽度限制（队列 260px，详情 380px），分隔条的 ARIA 数值与之一致。窄窗口（≤760px）改为上下排列，队列较矮，详情区独立滚动。偏好保存在 `cmr_split` 这个普通偏好 Cookie 中（仅本机 host，非 HttpOnly，值经过校验），因此重启 `web`（端口变化）后仍保留。审批会话 Cookie 不被读取或修改。
     - 来源：如果正文开头的引用块（`> 原文归档：…`、`> 来源：[名称](URL)`）里有这两个明确标签，队列卡片显示归档标签，右侧标出原文 URL 和上级目录，并与 Wiki 目标位置分开。只识别这种开头的标签行，正文中的其他链接一律不当作来源；无效或带凭据的 URL 不显示。队列中没有单独的来源字段。
     - 位置：新建页面显示目标父页面的完整路径和新页面名称；整页或章节更新显示原页面的完整路径（可点击打开）；评论显示所在页面。选中某条时才读取一次位置，列表自动刷新不会重复读取；读取失败会标明“暂不可用”，不影响批准。
     - 正文三个标签：“预览”（默认）是即将写入的正文，“源码”是提交给 Confluence 的 storage XHTML，“改动记录”是入队时保存的 diff（更新）或 Markdown 原文（新建/评论）。
     - 图片清单显示本次入队图片的来源、附件名称和字节数；预览使用入队时保存的图片快照。
     - 预览的限制：它是本地近似渲染，只还原标题、段落、列表、表格、`code` 宏、外部图片和本次入队的图片快照（`ac:image` 的 `ac:alt` 会保留）。其他宏、已有附件、样式、布局和权限以 Confluence 页面为准，未还原的宏会在预览中标出。预览旁边常驻一行“本地近似预览”提示，展开可看完整说明。预览在隔离的沙箱中显示，不执行脚本、不能访问审批接口。正文里的链接显示为文字和地址，不可点击。
     - 右侧的“批准”会立即写入 Confluence，“全部批准”会先确认条数。会话失效或写入进行中时，所有写入按钮都会禁用。
   - 终端：`.\.venv\Scripts\confluence-mcp-review.exe approve <id>`。不带 id 表示审批全部 `pending`，
     需输入 `yes`，确认后立即写入。

   `.\.venv\Scripts\confluence-mcp-review.exe`（等同 `list`）查看队列；`reject <id>` 可随时拒绝，无需交互式终端。
   macOS / Linux 将上述命令的 `.\.venv\Scripts\confluence-mcp-review.exe` 替换为 `./.venv/bin/confluence-mcp-review`，参数相同。
   `web` 和 `approve` 都要求设置 `CONFLUENCE_ENABLE_WRITES=true`。
3. 批准即写入：每条操作仅领取执行一次，页面与图片可能需要多次请求，失败不自动重试。原来的 `apply_approved_operations` 工具已移除。
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
（macOS / Linux 为 `~/.confluence-mcp/audit.log`；JSON Lines，不含页面正文和 PAT）。

已知边界：

- 该队列阻止的是通过 MCP 的提示注入或误写。它不能阻止一个拥有 shell、
  能以同一 OS 用户运行、能附加 PTY 或读取 PAT 的 agent；Jira-local-MCP 也有同样的限制。
- 审批页的令牌只在该 `web` 进程运行期间有效，只能挡住别的网页和别的机器，挡不住本机上权限相同的恶意进程。
- SQLite 队列和审计日志不防同一系统用户的篡改，不是不可抵赖的审计，不要把它当作生产级审计记录。
- 队列数据库有版本号（`PRAGMA user_version`）。本版本会将版本 0/1 的既有队列升级到版本 2，新增图片快照表并保留原有操作与结果。旧版程序会拒绝版本 2 队列，升级时应一并重启 MCP 和审批进程。遇到不认识的版本或表结构会拒绝打开并报出文件路径，请先检查该文件。

## 能力

- `search_pages`：按页面正文/标题中的文本查找页面，可限定 Space Key。
- `get_page`：按 Page ID 读取页面；支持 `section` 按标题只读一节，或用 `max_chars` 截断超长内容。
- `get_page_by_title`：按精确标题读取页面；重名时要求提供 Space Key。
- `cql_search`：直接执行 CQL，支持标签、时间、作者、空间组合查询；返回 excerpt 与分页 `next_start`。
- `get_page_outline`：只返回 h1–h6 标题树，适合先看结构再决定读哪一节。
- `list_spaces`：列出可见的全局 Space，便于找到 `space_key`。
- `get_comments`：读取页面评论并转 Markdown，保留回复的父评论 ID。
- `get_children`：读取子页面树，最多 3 层，单次调用总节点上限 200。
- `get_page_history`：列出版本历史，或对两个版本做 Markdown diff（默认 4000 字符上限）。8.5.15 实测 `/rest/api/content/{id}/version` 可用；不可用时自动回退到 `/rest/experimental`。
- `create_page` / `add_comment`（需开启写操作）：从 Markdown 创建页面或评论；默认 `dry_run=true` 只返回预览，`dry_run=false` 入队等待人工审批。
- `update_page` / `update_page_section`（需开启写操作）：整页或单节更新；必须传 `expected_version`，整页 Markdown 更新默认拒绝含宏页面，单节更新只替换目标章节；`dry_run=false` 入队等待人工审批。
- `create_page` / `update_page` / `update_page_section` 的 Markdown 图片会自动读取或下载，并在审批后上传为页面附件；相对路径需要 `image_base_dir`。详见下方“Markdown 图片”。
- `move_page`（需开启写操作）：调整页面在页面树中的位置，不修改正文。`position="before"` / `"after"` 把页面放到同级页面 `target_page_id` 的前/后（会随之改到该页面的父页面下）；`position="append"` 把页面移到 `target_page_id` 下作为最后一个子页面。只支持同一空间内移动，不支持移到空间根目录。`dry_run=true` 返回移动前后的同级顺序；`dry_run=false` 入队等待人工审批，批准后向站点的 `/pages/movepage.action` 发送 POST 请求。要排好多个页面，按顺序入队多条移动，批准时按队列顺序执行。
- `list_queued_operations` / `get_queued_operations` / `cancel_queued_operations` / `get_execution_log`（需开启写操作）：查看自己入队的操作和 diff 预览、撤回尚未审批（`pending`）的操作、读取已结束操作的结果。MCP 无法批准或执行任何操作，也无法撤回已批准的操作。
- 页面内容可返回 Markdown、Confluence 渲染 HTML 或原始 storage XHTML。

页面 ID 可从页面链接中的 `pageId` 参数，或从 `.../pages/<数字>/...` 路径中取得。也可以先用 `search_pages` 或 `get_page_by_title` 查找页面。

Confluence 8.5.15 使用 Server/Data Center REST API v1。页面读取通过 `GET /rest/api/content/{id}?expand=body.storage,body.view,version,space,ancestors` 完成；搜索通过 `GET /rest/api/content/search` 完成。默认只发起 `GET` 请求；开启写操作后才会发起 `POST` / `PUT`。

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
- 查看待审批队列：终端运行 `.\.venv\Scripts\confluence-mcp-review.exe`
- 网页审批并写入：终端运行 `.\.venv\Scripts\confluence-mcp-review.exe web`
- 看自己入队的操作：`list_queued_operations()`；撤回未审批的：`cancel_queued_operations(operation_ids=["..."])`

`section` 只支持 `markdown` / `storage` 输出；`html` 是整个 `body.view`，无法按章节切分。

`html` 返回 Confluence 的 `body.view` 渲染片段；如果服务器未提供该扩展，则回退到 `body.storage`。`markdown` 从 storage XHTML 转换；Confluence 专有宏、图表和应用宏可能无法完全映射为 Markdown，需以 HTML 或原页面查看其渲染结果。

## Markdown 图片

创建、整页 Markdown 更新和章节更新会自动处理 Markdown 图片（含引用式图片）以及 HTML `<img>`。工具仍接收 Markdown 正文文本；调用方读取 MD 文件后，将其所在目录作为 `image_base_dir` 传入。

```python
create_page(
    space_key="OPS",
    title="部署说明",
    content_markdown="## 部署流程\n\n![流程图](images/flow.png)",
    image_base_dir=r"D:\文档",  # 原始 MD 文件位于 D:\文档，图片位于 D:\文档\images
    dry_run=False,
)

update_page(
    page_id="123456",
    expected_version=3,
    content="## 新流程\n\n![流程图](images/flow.png)",
    image_base_dir=r"D:\文档",
    dry_run=False,
)
```

- 本地图片支持相对路径、绝对路径和本机 `file:` URL。相对路径按 `image_base_dir` 解析，支持 URL 编码的空格及中文路径。
- `http(s)` 图片会下载后上传，`//host/path` 按 HTTPS 下载。下载跟随重定向，使用独立请求且不携带 Wiki PAT；需要登录、Cookie 或其他认证的图片应先保存到本地。
- `dry_run=true` 会读取或下载图片并返回附件清单和正文预览。`dry_run=false` 将图片二进制快照与正文原子存入本地 SQLite 队列，审批后使用该快照，源文件随后变化或被移动也不会影响本次执行。任一图片读取或下载失败，整条操作会报错并停止入队。
- 升级前已经入队的操作保留原请求；如需为这些操作补齐图片上传，请撤回后使用新工具重新入队。
- 正文图片转换为 `<ac:image><ri:attachment ... /></ac:image>`。附件名称为 `mcp-<内容 SHA-256><图片扩展名>`，相同内容去重并复用目标页已有的同名附件，内容变化会生成新名称。既有附件保留在页面中。
- 新页面先创建占位页取得 ID，再上传图片并发布最终正文，通常完成于版本 2。已有页面在上传前核对版本与空间，上传后仍以入队时绑定的下一版本提交正文，保留 Confluence 的版本冲突保护。
- 页面与附件通过多次请求写入。中途失败可能保留已创建的占位页或已上传的附件；执行日志记录已知页面 ID、已上传/复用的附件及正在上传的名称。结果不明的请求需到 Wiki 核对，再决定后续操作。
- 读取同页附件图片为 Markdown 时使用 `![说明](attachment:filename)`；更新时会保留此引用。它表示目标页面的已有附件。`content_format="storage"` 的整页更新和 `add_comment` 沿用原来的正文处理方式。
- 图片需要非空内容及 `image/*` 类型（本地文件按扩展名识别）。`data:` 内嵌图片不在本次支持范围。上传权限、大小限制和最终图片渲染由 Confluence 决定；本地审批预览仅展示本次排队的图片快照，已有附件仍显示占位说明。

上传使用 Data Center 的附件接口和 multipart 表单，正文使用 Confluence 附件图片引用格式，参见 [Atlassian 附件上传说明](https://support.atlassian.com/confluence/kb/using-the-confluence-rest-api-to-upload-an-attachment-to-one-or-more-pages/) 和 [Confluence Storage Format](https://confluence.atlassian.com/doc/confluence-storage-format-790796544.html)。

## 权限与故障定位

MCP 不会绕过 Confluence 权限；结果只包含 PAT 所属用户能读取的内容。对内网 Confluence 的请求由启动 MCP 的机器发出，因此 Codex 必须运行在能访问公司网络/VPN 的本地环境。把服务器改为远端运行时，远端也必须能访问该内网地址。

- 提示需要 Python：安装 Python 3.10 或更高版本，重新打开终端，再检查命令是否可用。
- 提示缺少地址或 PAT：重新运行脚本并填写缺少的值；只有对应的值已配置时才能按 Enter 保留。
- 提示无法隐藏 PAT 输入：在 Windows 终端或 macOS 终端中运行安装脚本，再重新输入；也可以自行编辑项目目录中的 `.env`。
- 安装依赖失败：检查本机能否访问 Python 软件源、网络代理和组织网络策略，再重新运行安装脚本。
- Agent 中看不到工具：确认安装检查已完成、客户端配置使用本机 `.venv` 中 Python 的绝对路径，然后重启或重载客户端。
- `401`：检查 PAT 是否有效/过期。
- `403`：检查账号对 Space 和页面限制是否有读取权限；写操作还需检查 `CONFLUENCE_WRITE_SPACES` 与 Space 的编辑限制。
- `404`：检查 Page ID 与根地址上下文路径；无权查看的页面也可能表现为不可用。
- TLS/连接错误：检查 VPN、DNS、代理与 `ATLASSIAN_CONFLUENCE_CA_BUNDLE`。
- 重定向错误：确认 `ATLASSIAN_CONFLUENCE_URL` 指向实际 Confluence 根地址，而非登录页、反向代理跳转地址或 `/rest/api`。

如果配置没生效，检查源码项目根目录的 `.env` 及其中的配置值，然后重启 MCP 和审批服务。不要把 PAT、密码或公司页面内容提交到 GitHub 或输出到日志；`.env` 包含明文 PAT，不要分享。

## 开发

```powershell
.\.venv\Scripts\python.exe -m pip install -c constraints.txt -e ".[dev]"
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m confluence_mcp.server
```

第三条命令会启动 stdio MCP 进程并等待 MCP Host 请求，需由 MCP 客户端管理进程生命周期。

## 官方接口依据

写工具沿用 PAT 的权限，不会绕过 Confluence 的编辑限制。

- [Atlassian：Confluence Data Center REST API](https://developer.atlassian.com/server/confluence/rest/v923/)
- [Atlassian：REST API expansions](https://developer.atlassian.com/server/confluence/expansions-in-the-rest-api/)
- [Atlassian：使用 REST API 读取页面内容](https://support.atlassian.com/confluence/kb/how-to-get-page-content-or-child-list-via-rest-api/)
- [Model Context Protocol Python SDK](https://github.com/modelcontextprotocol/python-sdk)
