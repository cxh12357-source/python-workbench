"use strict";
const byId = (id) => document.getElementById(id);
let token = "";
let activeRun = null;
const terminal = new Set(["completed", "error", "timeout", "output_limit", "stopped"]);
const labels = {queued: "准备中", running: "运行中", completed: "已完成", error: "运行出错", timeout: "已超时", output_limit: "已达到输出上限", stopped: "已停止"};
async function request(path, options = {}) {
  const response = await fetch(path, {...options, credentials: "same-origin", headers: {"X-Runner-Token": token, ...options.headers}});
  const payload = await response.json();
  if (!response.ok) throw new Error(typeof payload.detail === "string" ? payload.detail : JSON.stringify(payload.detail));
  return payload;
}
function display(run) {
  byId("stdout").textContent = run.stdout;
  byId("stderr").textContent = run.stderr;
  byId("status").textContent = `${labels[run.status] || run.status} · ${run.duration_ms} ms${run.exit_code === null ? "" : ` · 退出码 ${run.exit_code}`}`;
}
function idle() { activeRun = null; byId("run").disabled = false; byId("stop").disabled = true; }
async function poll(id) {
  try {
    const run = await request(`/api/runs/${id}`);
    display(run);
    if (terminal.has(run.status)) idle();
    else setTimeout(() => poll(id), 100);
  } catch (error) { byId("status").textContent = error.message; idle(); }
}
byId("run").addEventListener("click", async () => {
  try {
    const argv = JSON.parse(byId("argv").value);
    if (!Array.isArray(argv) || argv.some((value) => typeof value !== "string")) throw new Error("参数必须是 JSON 字符串数组，如 [\"hello\"]。");
    byId("run").disabled = true;
    const run = await request("/api/runs", {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({code: byId("code").value, stdin: byId("stdin").value, argv})});
    activeRun = run.id;
    byId("stop").disabled = false;
    display(run);
    poll(run.id);
  } catch (error) { byId("status").textContent = error.message; idle(); }
});
byId("stop").addEventListener("click", async () => {
  if (!activeRun) return;
  try { await request(`/api/runs/${activeRun}`, {method: "DELETE"}); }
  catch (error) { byId("status").textContent = error.message; }
});
fetch("/api/session", {credentials: "same-origin", headers: {"X-Runner-Bootstrap": "1"}})
  .then(async (response) => { if (!response.ok) throw new Error("无法初始化会话，请从启动脚本提供的本机地址打开。"); return response.json(); })
  .then((session) => { token = session.token; byId("status").textContent = "可以运行"; byId("run").disabled = false; })
  .catch((error) => { byId("status").textContent = error.message; });
