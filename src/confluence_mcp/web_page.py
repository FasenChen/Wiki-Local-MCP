"""The single HTML page served by confluence-mcp-review web.

Operation text comes from an agent, so it is only ever written with textContent.
"""

PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Confluence 写入审批</title>
<style>
  :root { color-scheme: light dark; --line: #8884; --accent: #2563eb; --bad: #b91c1c; --ok: #15803d; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.5 system-ui, "Microsoft YaHei", sans-serif; height: 100vh; display: flex; flex-direction: column; }
  header { display: flex; gap: 12px; align-items: center; padding: 10px 16px; border-bottom: 1px solid var(--line); }
  header h1 { font-size: 16px; margin: 0; flex: 1; }
  #notice { padding: 6px 16px; min-height: 30px; border-bottom: 1px solid var(--line); }
  #notice.error { color: var(--bad); }
  main { flex: 1; display: flex; min-height: 0; }
  #list { width: 38%; min-width: 260px; overflow-y: auto; border-right: 1px solid var(--line); }
  .item { padding: 8px 14px; border-bottom: 1px solid var(--line); cursor: pointer; }
  .item.selected { background: #2563eb22; }
  .item .meta { opacity: .7; font-size: 12px; }
  .badge { font-size: 12px; padding: 0 6px; border: 1px solid var(--line); border-radius: 8px; margin-left: 6px; }
  .badge.succeeded { color: var(--ok); }
  .badge.failed, .badge.indeterminate { color: var(--bad); }
  #detail { flex: 1; padding: 14px 18px; overflow-y: auto; }
  pre { background: #8881; padding: 10px; border-radius: 6px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; }
  button { font: inherit; padding: 5px 14px; border: 1px solid var(--line); border-radius: 6px; background: transparent; color: inherit; cursor: pointer; }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button:disabled { opacity: .4; cursor: not-allowed; }
  #result { margin-top: 10px; }
</style>
</head>
<body>
<header>
  <h1>Confluence 写入审批</h1>
  <button id="approve-all" class="primary">全部批准</button>
  <button id="reject-all">全部拒绝</button>
</header>
<div id="notice"></div>
<main>
  <div id="list"></div>
  <div id="detail"></div>
</main>
<script>
"use strict";
var $ = function (id) { return document.getElementById(id); };
var ops = [], selected = null, results = {}, busy = false, timer = null;

function el(tag, className, text) {
  var node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function notice(text, isError) {
  $("notice").textContent = text;
  $("notice").className = isError ? "error" : "";
}

function stop() {
  clearInterval(timer);
  notice("会话失效,请重新运行 confluence-mcp-review web", true);
  $("approve-all").disabled = true;
  $("reject-all").disabled = true;
  document.querySelectorAll("#detail button").forEach(function (b) { b.disabled = true; });
}

function api(path, body) {
  var options = body === undefined
    ? { credentials: "same-origin" }
    : { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  return fetch(path, options).then(function (res) {
    if (res.status === 403) { stop(); throw new Error("forbidden"); }
    if (!res.ok) throw new Error("HTTP " + res.status);
    return res.json();
  });
}

function describe(op) {
  var executed = results[op.id];
  var status = executed ? executed.status : op.status;
  var error = executed ? executed.error : op.error;
  var result = executed ? executed.result : op.result;
  var text = "状态: " + status;
  if (error) text += "\n错误: " + error;
  if (result) text += "\n结果: 页面 " + result.id + ", 版本 " + result.version + ", " + (result.url || "");
  return text;
}

function render() {
  var list = $("list");
  list.replaceChildren();
  ops.forEach(function (op) {
    var item = el("div", "item" + (op.id === selected ? " selected" : ""));
    var title = el("div", "", op.id);
    title.appendChild(el("span", "badge " + op.status, op.status));
    item.appendChild(title);
    var where = op.action + "  " + (op.space_key || "") + "/" + (op.page_id || "新页面");
    if (op.version_before) where += "  v" + op.version_before;
    item.appendChild(el("div", "meta", where));
    item.appendChild(el("div", "", op.summary));
    item.addEventListener("click", function () { selected = op.id; render(); });
    list.appendChild(item);
  });

  var detail = $("detail");
  detail.replaceChildren();
  var op = ops.find(function (o) { return o.id === selected; });
  if (!op) { detail.appendChild(el("p", "", ops.length ? "选择左侧的一条操作查看改动。" : "队列是空的。")); }
  else {
    detail.appendChild(el("h2", "", op.summary));
    detail.appendChild(el("pre", "", op.preview));
    var actionable = op.status === "pending" || op.status === "approved";
    if (actionable) {
      var approve = el("button", "primary", op.status === "approved" ? "写入" : "批准");
      approve.addEventListener("click", function () { act("approve", [op.id]); });
      detail.appendChild(approve);
      detail.appendChild(document.createTextNode(" "));
      var reject = el("button", "", "拒绝");
      reject.disabled = op.status !== "pending";
      reject.addEventListener("click", function () { act("reject", [op.id]); });
      detail.appendChild(reject);
    }
    detail.appendChild(el("pre", "", describe(op))).id = "result";
  }
  $("approve-all").disabled = busy || !ops.some(function (o) { return o.status === "pending"; });
  $("reject-all").disabled = $("approve-all").disabled;
}

function refresh() {
  return api("/api/state").then(function (data) {
    ops = data.operations;
    if (!ops.some(function (o) { return o.id === selected; })) selected = null;
    render();
  });
}

function act(kind, ids) {
  if (busy) return;
  busy = true;
  render();
  api("/api/" + kind, { ids: ids }).then(function (out) {
    if (kind === "approve") {
      (out.executed || []).forEach(function (e) { results[e.operation_id] = e; });
      var parts = ["已处理 " + (out.executed || []).length + " 条"];
      if ((out.not_pending || []).length) parts.push(out.not_pending.length + " 条已不是待审批");
      if ((out.skipped || []).length) parts.push(out.skipped.length + " 条因结果不明被跳过,仍待审批");
      notice(parts.join(","), (out.skipped || []).length > 0);
    } else {
      notice("已拒绝 " + (out.rejected || []).length + " 条", false);
    }
  }).catch(function (err) {
    if (err.message !== "forbidden") notice("请求失败: " + err.message, true);
  }).then(function () {
    busy = false;
    return refresh().catch(function () {});
  });
}

function pendingIds() {
  return ops.filter(function (o) { return o.status === "pending"; }).map(function (o) { return o.id; });
}

$("approve-all").addEventListener("click", function () {
  var ids = pendingIds();
  if (ids.length && confirm("写入 " + ids.length + " 条?")) act("approve", ids);
});
$("reject-all").addEventListener("click", function () {
  var ids = pendingIds();
  if (ids.length) act("reject", ids);
});

refresh().catch(function () {});
timer = setInterval(function () { if (!busy) refresh().catch(function () {}); }, 5000);
</script>
</body>
</html>
"""
