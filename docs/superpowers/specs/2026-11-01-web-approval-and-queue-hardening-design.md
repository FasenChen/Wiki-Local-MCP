# 网页审批页与写入队列加固:设计

日期:2026-11-01
状态:待用户批准

## 背景与原因

本项目是只读为主的 Confluence MCP。写入工具(`create_page`、`add_comment`、`update_page`、`update_page_section`)只把操作写入本地 SQLite 队列(`~/.confluence-mcp/queue.sqlite3`),由人在 MCP 之外审批,审批后才真正写入 Confluence。

现状:审批只能在终端里用 `confluence-mcp-review list/approve/reject`,审批后还要 Agent 调用 `apply_approved_operations` 才会写入。

起因:参考了 Jira-local-MCP(https://github.com/LittleWhiteMouse-233/Jira-local-MCP)最近的更新,挑出适合本项目的部分。用户的原话要求:审批要在网页里做,"简单直观"。

## 目标

1. 一个本地网页审批页,人在页面上看 diff,点一次"批准"就把这条操作写入 Confluence。
2. Agent 能看到自己入队的操作,并能撤回还没审批的操作。
3. 进程在写入过程中崩溃后,不会留下永远停在 `executing` 的记录。
4. Agent 能查询已经执行过的操作的结果。
5. 队列数据库有版本号,结构变化时明确拒绝打开,不静默出错。
6. README 写明本地队列的安全边界。

## 非目标

- 不引入操作之间的依赖(例如用待创建页面的 operation ID 引用后续操作)。
- 不增加 Jira 那样的元数据查询工具。
- 不拆分 `server.py` 的目录结构。
- 不做手动排序、附件、批量取消的依赖范围确认。
- 不做会话滚动续期。

## 反目标(技术上做到了也算失败)

- Agent 通过任何 MCP 工具批准或执行操作,或者撤回已经批准的操作。
- 同一条操作被发送到 Confluence 两次。
- 结果不明的操作被自动重试。
- 审批页能被其他机器、或本机上没有令牌的网页访问到。

## 约束

- Python,沿用现有结构:`src/confluence_mcp/` 下的 `server.py`、`queue.py`、`review.py`、`writes.py`。
- 不新增第三方依赖。网页服务用标准库 `http.server`。
- Windows 为主要平台。现有 `review.py` 里对真实控制台的检查是提交 `23dba26` 的结果,不要退化。
- 写入仍受 `writes_enabled()` 和 `ensure_write_allowed(space_key)` 约束。
- 每条操作最多发送一次。

## 用户已决定的部分

- 审批在网页里完成。
- 布局:左边是待审批列表,右边是选中那条的完整 diff,右边有"批准"和"拒绝"按钮;顶部有"全部批准 / 全部拒绝"。
- 点一次"批准"就立刻写入 Confluence,不分成"批准"和"写入"两步。
- 采纳 Jira 的 5 项借鉴:Agent 查看和撤回、重启后 `executing` 转 `indeterminate`、Agent 执行记录查询、数据库版本号、README 已知边界。
- 不照搬 Jira 的依赖机制、元数据工具、15 分钟会话续期、按子包拆分工具。

## 我的决定(待用户确认)

以下是我替用户做的选择,请逐条核对。

1. **命令名与启动:** `confluence-mcp-review web`,在用户自己的终端运行,监听 `127.0.0.1` 的随机端口,启动时打开浏览器。审批页由这个独立进程提供,不放在 MCP 服务里,Agent 无法打开它。
2. **访问控制:** 启动时生成一次性令牌,放在链接里;首次访问后换成 HttpOnly、SameSite=Strict 的 cookie。所有修改状态的接口只接受 POST,并检查 Host 和 Origin。没有有效令牌的请求一律 403。
3. **页面技术:** 标准库 `http.server` 加一个静态 HTML/JS 页面,用安全的 DOM API 渲染(操作的内容来自 Agent,当作不可信数据,不用 `innerHTML`)。
4. **共用执行函数:** 把 `server.py` 里 `apply_approved_operations` 的认领、发送、记录结果、写审计那段逻辑挪成一个共用函数,页面和终端都调用它。
5. **终端 `approve` 也直接写入:** 这样两条路径行为一致。仍然需要真实的交互式控制台。
6. **删除 MCP 工具 `apply_approved_operations`:** 页面和终端批准即写入后,它没有存在的理由,而且保留它会让 Agent 有"执行"入口。
7. **"全部批准":** 点击后先弹确认框显示条数,确认后按入队顺序逐条写入;遇到 `indeterminate` 立即停止,后面的操作保持 `pending`。
8. **页面显示结果:** 每条操作写入后显示成功、失败或结果不明;成功时附 Confluence 页面链接。
9. **新增的 MCP 工具(名称是我定的):**
   - `list_queued_operations(page=1, page_size=50)`:概览,不含 payload。
   - `get_queued_operations(operation_ids)`:按 ID 取完整记录(含 preview)。
   - `cancel_queued_operations(operation_ids)`:只把 `pending` 改为 `rejected`;已批准、执行中、已完成的一律不动并在结果里说明。
   - `get_execution_log(page=1, page_size=50)`:已完成、失败、结果不明的操作和结果。
   这些工具在 `writes_enabled()` 为真时才注册。
10. **数据库版本号:** 用 `PRAGMA user_version`。已存在且表结构匹配的旧库(`user_version` 为 0)直接标记为版本 1;版本不认识时拒绝打开,并提示用户处理哪个文件。

11. **`approved` 状态保留:** 点批准后,操作先变 `approved`,再由共用执行函数认领为 `executing`,与 `queue.py` 现有流程一致,状态集合不变。旧流程遗留的、从未发送的 `approved` 行不做迁移;页面把它们列在列表里,标成"已批准未写入",并提供"写入"按钮。
12. **不改表结构:** 版本 1 就是当前的表结构,不增加 PID 或心跳列。执行写入的只有页面进程和终端 `approve`(MCP 不再执行)。页面启动时,把 `updated_at` 早于 5 分钟的 `executing` 行改为 `indeterminate`。5 分钟大于一次 Confluence 请求的超时,所以不会误伤正在发送的操作。
13. **干净的 HTTP 失败后继续:** "全部批准"遇到 Confluence 明确拒绝(有状态码,状态为 `failed`)时继续处理下一条;只有 `indeterminate` 才停止后面的操作。
14. **页面显示入队时的 diff:** 页面显示入队时保存的 `preview` 和"基于版本 vN"。写入时 payload 里带着 `version = N+1`,页面在期间被别人改过就会被 Confluence 以版本冲突拒绝,记为 `failed`,不会覆盖别人的修改。页面不额外做写前读取。
15. **凭据与开关:** 页面进程和 MCP 服务使用同一个 `get_client()`,读取同样的配置。`writes_enabled()` 为假时,`web` 命令拒绝启动并说明原因。
16. **启动要求真实控制台:** `confluence-mcp-review web` 沿用 `review.py` 里的真实控制台检查。否则有 shell 权限的 Agent 可以自己启动它并从输出里读到令牌,等于能批准自己的操作。令牌只打印到这个控制台。

## 需要用户回答(审阅后留下的唯一问题)

- 遇到 `indeterminate`(结果不明)的操作后:只停掉当前这一批,还是页面上所有写入都冻结,直到你手动标记处理?默认(批量停止、其他操作仍可点)是我的猜测,尚未确认。若选"全部冻结",需要加一个"标记已核对"的按钮和对应状态。

## 留给实现者决定

- 页面的具体样式、颜色、字体。
- 页面与后端之间接口的路径和 JSON 形状(只要满足上面的访问控制)。
- 重启恢复的实现细节。约束:不能把另一个仍在运行的进程正在执行的操作误改成 `indeterminate`。页面进程和 MCP 进程可能同时存在。
- 测试怎么写,沿用现有测试风格。

## 验收

- 在页面上点批准,操作写入 Confluence(用模拟的客户端验证),状态变为 `succeeded`。
- 同一条操作连续点两次批准,只发送一次。
- 发送时出现没有状态码的错误,状态变为 `indeterminate`,后续操作不再发送。
- Agent 调用 `cancel_queued_operations` 对 `approved` 或 `executing` 的操作无效。
- 没有令牌、或 Origin 不匹配的请求被拒绝。
- 进程在 `executing` 时被杀掉,重启后该操作显示为 `indeterminate`,且不会被重新发送。
- 版本号不匹配的数据库被拒绝打开。
