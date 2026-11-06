const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const page = fs.readFileSync(path.join(__dirname, "../src/confluence_mcp/web_page.py"), "utf8");
const script = page.split("<script>")[1].split("</script>")[0];

function functionSource(name) {
  const start = script.indexOf("function " + name + "(");
  assert.ok(start >= 0, "Missing frontend function " + name);
  const end = script.indexOf("\nfunction ", start + 1);
  return script.slice(start, end < 0 ? script.length : end);
}

function context() {
  const fields = { search: { value: "" }, "space-filter": { value: "" } };
  const statuses = ["pending", "approved", "executing", "succeeded", "failed", "indeterminate", "rejected"];
  const state = vm.createContext({
    ops: statuses.map((status, index) => ({
      id: "op-" + index,
      title: index === 0 ? "设备接入" : "Guide " + index,
      summary: "接入流程",
      status,
      space_key: [1, 2, 5].includes(index) ? "QA" : "OPS",
    })),
    filter: "active",
    checked: new Set(),
    $: id => fields[id],
  });
  vm.runInContext(["heading", "canApprove", "visibleOps", "checkedIds"].map(functionSource).join("\n"), state);
  return { state, fields };
}

test("the complete embedded script compiles", () => {
  new vm.Script(script);
});

test("active and attention filters retain legacy and indeterminate states", () => {
  const { state } = context();
  assert.deepEqual(Array.from(state.visibleOps(), op => op.id), ["op-0", "op-1", "op-2"]);
  state.filter = "attention";
  assert.deepEqual(Array.from(state.visibleOps(), op => op.id), ["op-4", "op-5"]);
});

test("space and case-insensitive search filters compose", () => {
  const { state, fields } = context();
  state.filter = "all";
  fields["space-filter"].value = "QA";
  fields.search.value = "OP-1";
  assert.deepEqual(Array.from(state.visibleOps(), op => op.id), ["op-1"]);
  fields.search.value = "设备";
  assert.equal(state.visibleOps().length, 0);
  fields["space-filter"].value = "";
  assert.deepEqual(Array.from(state.visibleOps(), op => op.id), ["op-0"]);
});

test("checked operations keep queue order and respect approval and rejection eligibility", () => {
  const { state, fields } = context();
  state.checked = new Set(["op-1", "op-0", "op-4", "op-5"]);
  fields["space-filter"].value = "QA";
  assert.deepEqual(Array.from(state.checkedIds("approve")), ["op-0", "op-1"]);
  assert.deepEqual(Array.from(state.checkedIds("reject")), ["op-0"]);
});

test("more than 200 operations are rejected before opening a confirmation", () => {
  const { state } = context();
  state.ops = Array.from({ length: 201 }, (_, index) => ({ id: "op-" + index, status: "pending" }));
  state.locked = () => false;
  state.confirmIds = [];
  const messages = [];
  state.notice = (message, error) => messages.push({ message, error });
  state.$ = () => assert.fail("Oversized batches must stop before rendering a dialog");
  vm.runInContext(functionSource("confirmAction"), state);
  state.confirmAction("approve", state.ops.map(op => op.id));
  assert.equal(messages.length, 1);
  assert.equal(messages[0].error, true);
  assert.match(messages[0].message, /200/);
});

test("session expiry closes confirmation, stops polling, and locks actions", () => {
  const { state } = context();
  const dialog = { open: true, close() { this.open = false; } };
  const nodes = { notice: {}, "sync-state": {}, "confirm-dialog": dialog };
  let clearedTimer;
  let renderCount = 0;
  state.$ = id => nodes[id];
  state.busy = false;
  state.expired = false;
  state.timer = 123;
  state.clearInterval = timer => { clearedTimer = timer; };
  state.render = () => { renderCount += 1; };
  vm.runInContext(["notice", "locked", "stop"].map(functionSource).join("\n"), state);
  state.stop();
  assert.equal(state.locked(), true);
  assert.equal(dialog.open, false);
  assert.equal(clearedTimer, 123);
  assert.equal(renderCount, 1);
  assert.match(nodes.notice.textContent, /会话失效/);
});
