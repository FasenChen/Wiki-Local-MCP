"""The single HTML page served by confluence-mcp-review web.

Operation text, titles and links come from agents or Confluence, so they are only ever
written with textContent (or as validated http(s) hrefs). The body preview is an isolated,
sandboxed frame that the server renders from /api/render, so no untrusted HTML enters this
document.
"""

PAGE = r"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Confluence 写入审批</title>
<style>
  :root {
    color-scheme: light;
    --bg: #f3f4f6; --surface: #ffffff; --text: #111827; --muted: #4b5563;
    --line: #d1d5db; --accent: #1d4ed8; --accent-soft: #eff6ff; --accent-line: #93c5fd;
    --bad: #b91c1c; --ok: #15803d; --warn: #92400e; --warn-soft: #fef3c7;
  }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.6 system-ui, "Microsoft YaHei", "PingFang SC", sans-serif; height: 100vh; display: flex; flex-direction: column; background: var(--bg); color: var(--text); }
  header { display: flex; flex-wrap: wrap; gap: 8px 10px; align-items: center; padding: 8px 16px; background: var(--surface); border-bottom: 1px solid var(--line); }
  header h1 { font-size: 16px; margin: 0; flex: 1; min-width: 0; }
  .split-tools { display: flex; gap: 6px; }
  #notice { padding: 6px 16px; background: var(--surface); border-bottom: 1px solid var(--line); }
  #notice:empty { display: none; }
  #notice.error { color: var(--bad); font-weight: 600; }
  #main { flex: 1; display: flex; min-height: 0; }
  #queue { flex: 0 0 auto; width: 30%; min-width: 260px; display: flex; flex-direction: column; min-height: 0; background: var(--surface); }
  #list { flex: 1; overflow-y: auto; padding: 10px; display: flex; flex-direction: column; gap: 8px; }
  #divider { flex: 0 0 8px; position: relative; cursor: col-resize; touch-action: none; }
  #divider::before { content: ""; position: absolute; top: 0; bottom: 0; left: 3px; width: 2px; background: var(--line); }
  #divider:hover::before { background: var(--accent); }
  #detail { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; padding: 12px 18px; background: var(--surface); }
  #detail-head { flex: 0 1 auto; max-height: 45vh; overflow-y: auto; padding-bottom: 6px; }
  #detail-head h2 { font-size: 18px; margin: 0 0 2px; overflow-wrap: anywhere; }
  .muted { color: var(--muted); font-size: 13px; overflow-wrap: anywhere; }
  .card { display: block; flex-shrink: 0; width: 100%; text-align: left; padding: 9px 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface); color: inherit; cursor: pointer; }
  .card:hover { border-color: var(--accent-line); background: var(--accent-soft); }
  .card.selected { border-color: var(--accent); background: var(--accent-soft); box-shadow: inset 4px 0 0 var(--accent); }
  .card-title { display: block; font-weight: 600; overflow-wrap: anywhere; }
  .card-meta { display: block; margin-top: 3px; font-size: 12px; color: var(--muted); overflow-wrap: anywhere; }
  .tags { display: flex; flex-wrap: wrap; gap: 4px; margin-top: 6px; }
  .tag { font-size: 12px; padding: 0 7px; border-radius: 4px; border: 1px solid var(--line); background: #f9fafb; color: var(--muted); }
  .tag.tag-collection { border-color: var(--accent-line); background: var(--accent-soft); color: var(--accent); }
  .tag.status-succeeded { color: var(--ok); }
  .tag.status-pending, .tag.status-approved { color: var(--warn); background: var(--warn-soft); border-color: transparent; }
  .tag.status-failed, .tag.status-indeterminate { color: var(--bad); }
  .location, .source { margin: 8px 0; padding: 8px 10px; border-radius: 8px; border: 1px solid var(--line); }
  .context { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 10px; }
  .context > :only-child { grid-column: 1 / -1; }
  .source { border-style: dashed; }
  .label { font-size: 12px; font-weight: 600; color: var(--muted); }
  .crumbs { overflow-wrap: anywhere; }
  .crumbs .sep { margin: 0 6px; color: var(--muted); }
  .newpage { margin-top: 4px; font-weight: 600; overflow-wrap: anywhere; }
  .url-text { font-size: 12px; color: var(--muted); overflow-wrap: anywhere; word-break: break-all; }
  .actions { display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0; }
  .result { font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; margin: 0; color: var(--muted); }
  #tabs { display: flex; gap: 4px; border-bottom: 1px solid var(--line); }
  .tab { border: 0; border-bottom: 2px solid transparent; border-radius: 0; padding: 6px 12px; background: transparent; }
  .tab.selected { border-bottom-color: var(--accent); color: var(--accent); font-weight: 600; }
  #panel { flex: 1; min-height: 0; display: flex; flex-direction: column; padding-top: 8px; }
  #panel pre { flex: 1; min-height: 0; overflow: auto; margin: 0; background: #f9fafb; color: var(--text); border: 1px solid var(--line); padding: 10px; border-radius: 6px; white-space: pre-wrap; word-break: break-word; }
  .limits { font-size: 13px; color: var(--muted); margin: 0 0 6px; }
  .limits summary { cursor: pointer; font-weight: 600; padding: 2px 0; }
  .limits p { margin: 4px 0 0; font-size: 12px; }
  .frame { flex: 1 1 0; min-height: 0; width: 100%; border: 1px solid var(--line); border-radius: 8px; background: #fff; }
  button { font: inherit; min-height: 44px; padding: 4px 12px; border: 1px solid var(--line); border-radius: 6px; background: var(--surface); color: var(--text); cursor: pointer; }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:focus-visible, a:focus-visible, #divider:focus-visible { outline: 3px solid var(--accent); outline-offset: 2px; }
  button.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
  button:disabled { opacity: .45; cursor: not-allowed; }
  a { color: var(--accent); }
  @media (max-width: 1000px) { .context { display: block; } }
  @media (max-width: 760px) {
    #main { flex-direction: column; }
    #queue { width: auto !important; min-width: 0; height: 24vh; min-height: 120px; }
    #list { padding: 6px; gap: 6px; }
    #divider, .split-tools { display: none; }
    #detail { min-width: 0; padding: 8px 12px; }
    #detail-head { max-height: 30vh; }
    header h1 { flex-basis: 100%; }
  }
</style>
</head>
<body>
<header>
  <h1>Confluence 写入审批</h1>
  <div class="split-tools" role="group" aria-label="队列宽度">
    <button type="button" id="split-narrow">收窄队列</button>
    <button type="button" id="split-wide">加宽队列</button>
    <button type="button" id="split-reset">恢复默认</button>
  </div>
  <button id="approve-all" class="primary">全部批准</button>
  <button id="reject-all">全部拒绝</button>
</header>
<div id="notice"></div>
<main id="main">
  <aside id="queue" aria-label="待审批队列"><div id="list"></div></aside>
  <div id="divider" role="separator" tabindex="0" aria-orientation="vertical" aria-label="调整队列与文档宽度：拖动，或聚焦后用左右方向键" aria-valuemin="20" aria-valuemax="80" aria-valuenow="30"></div>
  <section id="detail" aria-label="操作详情">
    <div id="detail-head"></div>
    <div id="tabs" role="tablist">
      <button class="tab selected" role="tab" data-tab="preview" aria-selected="true">预览</button>
      <button class="tab" role="tab" data-tab="source" aria-selected="false">源码</button>
      <button class="tab" role="tab" data-tab="diff" aria-selected="false">改动记录</button>
    </div>
    <div id="panel"></div>
  </section>
</main>
<script>
"use strict";
// The split ratio is kept in a host-only, non-HttpOnly preference cookie named cmr_split. It is
// not a secret and is validated on read. Cookies ignore the port, so it survives a restart of `web`
// even though the port changes. The session cookie is HttpOnly and is never read or written here.
var $ = function (id) { return document.getElementById(id); };
var STATE_PATH = "/api/state";
var APPROVE_PATH = "/api/approve";
var REJECT_PATH = "/api/reject";
var ACTIONS = { create_page: "新建页面", add_comment: "新增评论", update_page: "整页更新", update_page_section: "章节更新", move_page: "调整位置" };
var LOCATION_LABELS = { comment: "评论所在页面", move: "被移动页面的当前路径", update: "原 Wiki 页面路径（批准后修改此页）" };
var STATUSES = { pending: "待审批", approved: "已批准·未写入", rejected: "已拒绝", executing: "写入中", succeeded: "已成功", failed: "失败", indeterminate: "结果不明" };
var LIMITS = "只还原标题、段落、列表、表格、代码块、外部图片和本次入队的图片快照。其他宏、已有附件、样式与权限以 Confluence 页面为准，未还原的宏会在预览中标出。预览在隔离沙箱中显示，不执行脚本。";
var SECTION_NOTE = "章节更新：下面是整页更新后的完整正文，包含本次替换的章节。";
var NARROW = "(max-width: 760px)";
var MIN_LIST = 260, MIN_DETAIL = 380, DEFAULT_SPLIT = 0.3;
var ops = [], selected = null, tab = "preview", results = {}, locations = {}, locErrors = {}, locLoading = {};
var busy = false, expired = false, timer = null, panelKey = "", headKey = "", dragging = false;
var split = readSplit();

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

function locked() { return busy || expired; }

function stop() {
  expired = true;
  clearInterval(timer);
  notice("会话失效,请重新运行 confluence-mcp-review web", true);
  render();
}

function api(path, body) {
  var options = body === undefined
    ? { credentials: "same-origin" }
    : { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  return fetch(path, options).then(function (res) {
    if (res.status === 403) { stop(); throw new Error("forbidden"); }
    return res.json().catch(function () { return {}; }).then(function (data) {
      if (!res.ok) throw new Error(data.error || "HTTP " + res.status);
      return data;
    });
  });
}

function safeUrl(url) {
  return typeof url === "string" && /^https?:\/\//i.test(url) ? url : null;
}

function describe(op) {
  var executed = results[op.id];
  var status = executed ? executed.status : op.status;
  var error = executed ? executed.error : op.error;
  var result = executed ? executed.result : op.result;
  var text = "状态: " + status;
  if (error) text += "\n错误: " + error;
  if (result) {
    text += "\n结果: 页面 " + result.id;
    if (result.version != null) text += ", 版本 " + result.version;
    if (result.url) text += ", " + result.url;
    if (result.uploaded_attachments && result.uploaded_attachments.length) text += "\n已上传图片: " + result.uploaded_attachments.join(", ");
    if (result.reused_attachments && result.reused_attachments.length) text += "\n已复用图片: " + result.reused_attachments.join(", ");
    if (result.uploading_attachment) text += "\n上传待核对: " + result.uploading_attachment;
  }
  return text;
}

function heading(op) {
  if (op.title) return op.title;
  return op.action === "add_comment" ? "评论 · 页面 " + op.page_id : op.summary;
}

function crumbs(trail, partial) {
  var box = el("div", "crumbs");
  trail.forEach(function (item, i) {
    if (i) box.appendChild(el("span", "sep", "›"));
    var label = item.title || "(无标题)";
    var href = safeUrl(item.url);
    if (href) {
      var link = el("a", "", label);
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      box.appendChild(link);
    } else {
      box.appendChild(el("span", "", label));
    }
  });
  if (partial) box.appendChild(el("span", "muted", " （路径未完整返回）"));
  return box;
}

function locationBlock(op) {
  var box = el("div", "location");
  var loc = locations[op.id];
  if (!loc) {
    var note = locErrors[op.id]
      ? "位置信息暂不可用：" + locErrors[op.id] + "。重新选择此条可再次读取。"
      : "正在读取位置…";
    box.appendChild(el("div", "muted", note));
    return box;
  }
  if (loc.mode === "create") {
    box.appendChild(el("div", "label", "Wiki 目标位置（新页面将创建于此）"));
    if (loc.trail.length) box.appendChild(crumbs(loc.trail, loc.partial));
    else box.appendChild(el("div", "", "空间 " + loc.space_key + " 根目录"));
    box.appendChild(el("div", "newpage", "新页面：" + (loc.title || op.summary)));
  } else {
    box.appendChild(el("div", "label", LOCATION_LABELS[loc.mode] || LOCATION_LABELS.update));
    box.appendChild(crumbs(loc.trail, loc.partial));
  }
  return box;
}

// Original source named by the body's own provenance lines; it is not the Wiki destination.
function sourceBlock(op) {
  if (!op.source && !op.collection) return null;
  var box = el("div", "source");
  box.appendChild(el("div", "label", "原文来源（外部文档，不是 Wiki 目标）"));
  if (op.collection) box.appendChild(el("div", "", "归档：" + op.collection));
  if (op.source) {
    var href = safeUrl(op.source.url);
    var label = op.source.label || op.source.url;
    if (href) {
      var link = el("a", "", label);
      link.href = href;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      box.appendChild(link);
    } else {
      box.appendChild(el("span", "", label));
    }
    box.appendChild(el("div", "url-text", op.source.url));
    if (op.source.parent) box.appendChild(el("div", "url-text", "上级目录：" + op.source.parent));
  }
  return box;
}

function card(op) {
  var on = op.id === selected;
  var button = el("button", "card" + (on ? " selected" : ""));
  button.type = "button";
  button.dataset.id = op.id;
  button.setAttribute("aria-pressed", String(on));
  button.appendChild(el("span", "card-title", heading(op)));
  var tags = el("span", "tags");
  if (op.collection) tags.appendChild(el("span", "tag tag-collection", op.collection));
  tags.appendChild(el("span", "tag", ACTIONS[op.action] || op.action));
  tags.appendChild(el("span", "tag", "空间 " + (op.space_key || "未知")));
  tags.appendChild(el("span", "tag status-" + op.status, STATUSES[op.status] || op.status));
  button.appendChild(tags);
  var meta = [op.id, op.page_id ? "页面 " + op.page_id : "新页面"];
  if (op.version_before) meta.push("基于 v" + op.version_before);
  if (op.action === "update_page_section" && op.summary && op.summary !== op.title) meta.push("章节 " + op.summary);
  button.appendChild(el("span", "card-meta", meta.join(" · ")));
  button.addEventListener("click", function () { select(op.id); });
  return button;
}

function renderList() {
  var list = $("list");
  var active = document.activeElement;
  var focusId = active && active.dataset ? active.dataset.id : undefined;
  list.replaceChildren();
  if (!ops.length) list.appendChild(el("p", "muted", "队列是空的。"));
  ops.forEach(function (op) { list.appendChild(card(op)); });
  if (focusId !== undefined) {
    var again = Array.prototype.find.call(list.children, function (c) { return c.dataset.id === focusId; });
    if (again) again.focus({ preventScroll: true });
  }
}

function renderHead(op) {
  var head = $("detail-head");
  head.replaceChildren();
  head.appendChild(el("h2", "", heading(op)));
  var facts = [op.id, ACTIONS[op.action] || op.action, "空间 " + (op.space_key || "未知"), STATUSES[op.status] || op.status];
  if (op.version_before) facts.push("基于 v" + op.version_before);
  head.appendChild(el("div", "muted", facts.join(" · ")));
  var context = el("div", "context");
  context.appendChild(locationBlock(op));
  var source = sourceBlock(op);
  if (source) context.appendChild(source);
  head.appendChild(context);
  if (op.attachments && op.attachments.length) {
    var images = el("details", "limits");
    images.appendChild(el("summary", "", "随正文上传的图片（" + op.attachments.length + "）"));
    op.attachments.forEach(function (image) {
      images.appendChild(el("p", "url-text", image.source + " → " + image.filename + " · " + image.size_bytes + " 字节"));
    });
    head.appendChild(images);
  }
  if (op.status === "pending" || op.status === "approved") {
    var actions = el("div", "actions");
    var approve = el("button", "primary", op.status === "approved" ? "写入" : "批准");
    approve.id = "act-approve";
    approve.addEventListener("click", function () { act("approve", [op.id]); });
    var reject = el("button", "", "拒绝");
    reject.id = "act-reject";
    reject.addEventListener("click", function () { act("reject", [op.id]); });
    actions.appendChild(approve);
    actions.appendChild(reject);
    head.appendChild(actions);
  }
  head.appendChild(el("pre", "result", describe(op)));
}

function buildPanel(op) {
  var panel = $("panel");
  var key = panelKey;
  panel.replaceChildren();
  if (op.action === "move_page") {
    // A move sends no body, so every tab shows the planned order recorded at enqueue time.
    panel.appendChild(el("p", "limits", "调整页面位置，不修改正文。下面是入队时计算的移动后顺序；批准时按 Confluence 当时的实际顺序执行。"));
    panel.appendChild(el("pre", "", op.preview || "(没有记录)"));
  } else if (tab === "preview") {
    // Concise label always visible; the full limits open in place, and stay open across polls.
    var limits = el("details", "limits");
    limits.appendChild(el("summary", "", "本地近似预览，不等同于 Confluence 渲染"));
    limits.appendChild(el("p", "", LIMITS));
    panel.appendChild(limits);
    if (op.action === "update_page_section") panel.appendChild(el("p", "limits", SECTION_NOTE));
    var frame = document.createElement("iframe");
    frame.setAttribute("sandbox", "");
    frame.title = "正文预览";
    frame.className = "frame";
    frame.src = "/api/render?id=" + encodeURIComponent(op.id);
    panel.appendChild(frame);
  } else if (tab === "source") {
    var pre = el("pre", "", "正在加载源码…");
    panel.appendChild(el("p", "limits", "提交给 Confluence 的 storage XHTML，即批准后写入的正文。"));
    panel.appendChild(pre);
    api("/api/body?id=" + encodeURIComponent(op.id)).then(function (data) {
      if (panelKey === key) pre.textContent = data.storage || "(正文为空)";
    }, function (err) {
      if (panelKey === key) pre.textContent = "无法加载源码: " + err.message;
    });
  } else {
    var caption = op.kind === "update"
      ? "入队时保存的统一 diff（相对入队前的版本），用于审计。"
      : "入队时保存的 Markdown 原文（不是正文预览），用于审计。";
    panel.appendChild(el("p", "limits", caption));
    panel.appendChild(el("pre", "", op.preview || "(没有记录)"));
  }
}

function render() {
  renderList();
  var op = ops.find(function (o) { return o.id === selected; });
  document.querySelectorAll(".tab").forEach(function (button) {
    var on = button.dataset.tab === tab;
    button.classList.toggle("selected", on);
    button.setAttribute("aria-selected", String(on));
  });
  if (!op) {
    $("detail-head").replaceChildren(el("p", "muted", ops.length ? "选择左侧的一条操作查看正文。" : "队列是空的。"));
    $("panel").replaceChildren();
    headKey = "";
    panelKey = "";
  } else {
    // Rebuild the header only when something shown in it changes, so focus survives polling.
    var locState = locations[op.id] ? "ok" : (locErrors[op.id] || "loading");
    var key = [op.id, op.status, heading(op), describe(op), locState].join("\n");
    if (key !== headKey) {
      headKey = key;
      renderHead(op);
    }
    // The preview frame is rebuilt only when the operation or tab changes, so polling keeps scroll.
    if (op.id + "|" + tab !== panelKey) {
      panelKey = op.id + "|" + tab;
      buildPanel(op);
    }
    var approve = $("act-approve");
    var reject = $("act-reject");
    if (approve) approve.disabled = locked();
    if (reject) reject.disabled = locked() || op.status !== "pending";
  }
  $("approve-all").disabled = locked() || !ops.some(function (o) { return o.status === "pending"; });
  $("reject-all").disabled = $("approve-all").disabled;
}

function refresh() {
  return api(STATE_PATH).then(function (data) {
    ops = data.operations;
    if (!ops.some(function (o) { return o.id === selected; })) selected = null;
    render();
  });
}

function loadLocation(id) {
  if (locations[id] || locLoading[id]) return;
  locLoading[id] = true;
  delete locErrors[id];
  api("/api/location?id=" + encodeURIComponent(id)).then(function (data) {
    locations[id] = data;
  }, function (err) {
    locErrors[id] = err.message;
  }).then(function () {
    locLoading[id] = false;
    if (selected === id) render();
  });
}

function select(id) {
  selected = id;
  loadLocation(id);
  render();
}

function act(kind, ids) {
  if (locked()) return;
  busy = true;
  render();
  api(kind === "approve" ? APPROVE_PATH : REJECT_PATH, { ids: ids }).then(function (out) {
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
document.querySelectorAll(".tab").forEach(function (button) {
  button.addEventListener("click", function () { tab = button.dataset.tab; render(); });
});

// Split between queue and document. Pointer drag, arrow keys, Home/End on the separator, and the
// header buttons all go through setSplit, which clamps to the real pixel bounds.
function readSplit() {
  var match = /(?:^|;\s*)cmr_split=(0\.\d{1,3})(?:;|$)/.exec(document.cookie);
  var value = match ? parseFloat(match[1]) : NaN;
  return value >= 0.1 && value <= 0.9 ? value : DEFAULT_SPLIT;
}

function saveSplit() {
  document.cookie = "cmr_split=" + split.toFixed(3) + "; Path=/; Max-Age=31536000; SameSite=Strict";
}

function applySplit() {
  var queue = $("queue"), divider = $("divider"), main = $("main");
  if (window.matchMedia(NARROW).matches) {
    queue.style.width = "";
    divider.removeAttribute("aria-valuenow");
    return;
  }
  var width = main.clientWidth - divider.offsetWidth;
  var lo = MIN_LIST / width, hi = (width - MIN_DETAIL) / width;
  split = Math.min(hi, Math.max(lo, split));
  queue.style.width = Math.round(split * width) + "px";
  divider.setAttribute("aria-valuemin", String(Math.round(lo * 100)));
  divider.setAttribute("aria-valuemax", String(Math.round(hi * 100)));
  divider.setAttribute("aria-valuenow", String(Math.round(split * 100)));
}

function setSplit(value) {
  split = value;
  applySplit();
  saveSplit();
}

var divider = $("divider");
divider.addEventListener("pointerdown", function (e) {
  dragging = true;
  divider.setPointerCapture(e.pointerId);
  e.preventDefault();
});
divider.addEventListener("pointermove", function (e) {
  if (!dragging) return;
  var main = $("main");
  var rect = main.getBoundingClientRect();
  var width = main.clientWidth - divider.offsetWidth;
  split = (e.clientX - rect.left - divider.offsetWidth / 2) / width;
  applySplit();
});
function endDrag() {
  if (dragging) { dragging = false; saveSplit(); }
}
divider.addEventListener("pointerup", endDrag);
divider.addEventListener("pointercancel", endDrag);
divider.addEventListener("keydown", function (e) {
  var step = { ArrowLeft: -0.02, ArrowRight: 0.02 }[e.key];
  if (step) setSplit(split + step);
  else if (e.key === "Home") setSplit(0);
  else if (e.key === "End") setSplit(1);
  else return;
  e.preventDefault();
});
$("split-narrow").addEventListener("click", function () { setSplit(split - 0.05); });
$("split-wide").addEventListener("click", function () { setSplit(split + 0.05); });
$("split-reset").addEventListener("click", function () { setSplit(DEFAULT_SPLIT); });
window.addEventListener("resize", applySplit);
window.matchMedia(NARROW).addEventListener("change", applySplit);
applySplit();

refresh().catch(function () {});
timer = setInterval(function () { if (!busy) refresh().catch(function () {}); }, 5000);
</script>
</body>
</html>
"""
