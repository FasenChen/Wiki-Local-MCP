# 为当前 Agent 配置 Wiki MCP

请根据本文件，在当前会话所在的客户端中添加或更新本机 stdio MCP，注册名称使用 `wiki-local-mcp`。本文件由安装脚本生成，包含这台电脑实际使用的路径，可以直接作为附件提供给 Agent。

## 本机安装信息

操作系统为 $SYSTEM。项目目录如下，使用 JSON 字符串表示以保留路径中的特殊字符。

```json
$PROJECT_DIR
```

## stdio 启动配置

以下配置中的 `command` 是虚拟环境 Python 的绝对路径，`args` 是独立参数数组。

```json
$MCP_CONFIG
```

## 执行步骤

1. 根据当前会话识别正在使用的客户端。只配置当前客户端。如果无法判断，再请用户选择 WorkBuddy、DSH、Codex 或 Claude Code。
2. 检查上方 `command` 指向的文件是否存在。如果安装目录已移动，请用户在新目录重新运行 setup 并提供重新生成的 `MCP_SETUP.md`。
3. 读取当前客户端的 MCP 配置或使用其管理命令，合并 `wiki-local-mcp` 条目。保留其他服务器和用户设置。已有相同条目时复用，路径不同时更新该条目。
4. 使用下方当前客户端对应的方式完成配置。检查所用客户端版本的命令帮助或配置格式。
5. 重载连接并发现工具，确认 `search_pages`、`get_page`、`get_page_by_title` 是否可用。需要重启时，向用户说明具体步骤并将连接验证标为待完成。

本地文件访问和配置写入需要客户端授予相应权限。权限不足时，提供当前客户端可直接粘贴的配置及放置位置，并说明尚未完成自动配置。

## 客户端接入方式

- **Codex** 优先使用 `codex mcp add`，将上述 `command` 和 `args` 作为分开的参数传入，使用 `codex mcp list` 检查注册。Windows PowerShell 中可使用 `codex.cmd`。
- **Claude Code** 优先使用 `claude mcp add --scope user`，将上述 `command` 和 `args` 作为分开的参数传入，使用 `claude mcp list` 检查注册。
- **WorkBuddy** 在当前版本的“插件 → MCP 服务器 → 配置 MCP”入口或对应配置文件中合并上述 `mcpServers` 条目，然后重载连接。按当前安装版本确认配置文件位置。
- **DSH / DeepSeek Harness** 在当前 profile 的 `cordis.patch.yml` 中合并下方条目。已有 `mcp-confluence` 条目时更新它，保留其他 patch，再重载当前 profile。

DSH 配置如下。

```yaml
- insert:
    - id: mcp-confluence
      name: '@deepseek-ai/dsh-mcp-client'
      config:
        serverName: wiki-local-mcp
        transport: stdio
        command: $PYTHON_COMMAND
        args: ['-m', 'confluence_mcp.server']
```

需要核对客户端差异时，可参考官方文档。[WorkBuddy Connector](https://open.workbuddy.cn/en/docs/connector)、[DSH MCP 示例](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/user/guide/mcp-memory.md)

## 凭据与验证范围

- 配置客户端时使用本文件中的启动信息。禁止直接读取、输出或上传 `.env` 和 PAT，也不要让用户把 PAT 粘贴到对话中。
- MCP 进程会在本机读取项目 `.env`。客户端配置使用上方的本机启动命令，凭据留在本机。
- 本次任务只进行客户端注册和工具发现。禁止创建、修改、移动 Wiki 页面、添加评论或执行审批。
- 完成后简短报告修改的配置位置、服务器名称、工具发现结果，以及用户是否需要重启。将已注册和已连接分别说明。
