"use strict";
/* Knowledge API web client.
 *
 * Contract: the library selection is only *intent*. The server computes the
 * legal set; a refusal is shown verbatim and never softened. Switching library
 * issues no model request and stale responses from a previous selection are
 * discarded by the request generation counter.
 */

const state = {
  csrf: null,
  user: null,
  workspaces: [],
  selection: null,
  generation: 0,
  recordId: null,
  lastResult: null,
};

const $ = (id) => document.getElementById(id);

async function api(path, options) {
  const opts = Object.assign({ headers: {} }, options || {});
  if (opts.body !== undefined && typeof opts.body !== "string") {
    opts.body = JSON.stringify(opts.body);
    opts.headers["Content-Type"] = "application/json";
  }
  if (opts.method && opts.method !== "GET" && state.csrf) {
    opts.headers["X-RAG-Token"] = state.csrf;
  }
  const res = await fetch(path, opts);
  let payload = null;
  try {
    payload = await res.json();
  } catch (err) {
    payload = null;
  }
  if (!res.ok) {
    const code = (payload && payload.error) || "http_" + res.status;
    const error = new Error(code);
    error.status = res.status;
    error.payload = payload;
    throw error;
  }
  return payload;
}

function describeError(err) {
  const map = {
    unauthenticated: "未认证或凭据无效。",
    forbidden: "该请求不在当前主体的授权范围内，已整体拒绝。",
    unauthorized_workspace: "请求包含未授权知识库，已整体拒绝。",
    unknown_workspace: "请求包含未知知识库，已整体拒绝。",
    no_workspace: "该主体没有任何知识库授权。",
    bad_csrf: "会话校验失败，请重新登录。",
    not_available: "对象不存在或当前主体不可访问。",
    host_not_allowed: "仅允许本机访问。",
  };
  return map[err.message] || "请求失败（" + err.message + "）。";
}

function renderLibraries() {
  const box = $("libs");
  box.innerHTML = "";
  if (!state.workspaces.length) {
    $("libs-empty").hidden = false;
    return;
  }
  $("libs-empty").hidden = true;
  state.workspaces.forEach((ws, i) => {
    const id = "lib-" + ws.id;
    const wrap = document.createElement("label");
    wrap.className = "lib";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "lib";
    input.id = id;
    input.value = ws.id;
    input.checked = state.selection === ws.id || (state.selection === null && i === 0);
    input.addEventListener("change", () => selectWorkspace(ws.id));
    const span = document.createElement("span");
    span.textContent = ws.name + "（" + ws.id + "）";
    if (ws.status !== "active") {
      const badge = document.createElement("em");
      badge.className = "warn";
      badge.textContent = " 未就绪";
      span.appendChild(badge);
    }
    wrap.appendChild(input);
    wrap.appendChild(span);
    box.appendChild(wrap);
  });
  if (state.workspaces.length > 1) {
    const wrap = document.createElement("label");
    wrap.className = "lib";
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "lib";
    input.id = "lib-all";
    input.value = "all";
    input.addEventListener("change", () => selectWorkspace("all"));
    wrap.appendChild(input);
    const span = document.createElement("span");
    span.textContent = "全部已授权知识库";
    wrap.appendChild(span);
    box.appendChild(wrap);
  }
  if (state.selection === null) state.selection = state.workspaces[0].id;
}

function selectWorkspace(value) {
  state.selection = value;
  // Switching is a client-side act: no model request, and any response from a
  // previous selection is invalidated.
  state.generation += 1;
  state.recordId = null;
  state.lastResult = null;
  $("result-panel").hidden = true;
  $("generation").hidden = true;
  $("ask-status").textContent = "已切换知识库：" + value + "（未发起模型请求）";
}

async function doLogin(ev) {
  ev.preventDefault();
  $("login-error").hidden = true;
  try {
    const payload = await api("/api/login", {
      method: "POST",
      body: { user_id: $("user_id").value, password: $("password").value },
    });
    state.csrf = payload.csrf;
    state.user = payload;
    state.workspaces = payload.workspaces || [];
    state.selection = null;
    $("who").textContent = payload.display + " · " + payload.user_id;
    $("logout").hidden = false;
    $("login-panel").hidden = true;
    $("app-panel").hidden = false;
    renderLibraries();
    await loadRecords();
  } catch (err) {
    $("login-error").textContent = describeError(err);
    $("login-error").hidden = false;
  }
}

async function doLogout() {
  try {
    await api("/api/logout", { method: "POST", body: {} });
  } catch (err) {
    /* ignore */
  }
  state.csrf = null;
  state.user = null;
  state.workspaces = [];
  state.selection = null;
  state.generation += 1;
  state.recordId = null;
  $("who").textContent = "未登录";
  $("logout").hidden = true;
  $("login-panel").hidden = false;
  $("app-panel").hidden = true;
  $("result-panel").hidden = true;
  $("evidence").innerHTML = "";
  $("records").innerHTML = "";
}

async function doQuery(ev) {
  ev.preventDefault();
  const gen = ++state.generation;
  $("ask-status").textContent = "查询中…";
  $("result-panel").hidden = true;
  const route = $("route").value;
  const body = {
    workspace: state.selection,
    question: $("question").value,
    route: route,
    mode: $("mode").value,
  };
  try {
    const payload = await api("/api/query", { method: "POST", body: body });
    if (gen !== state.generation) return; // a stale response for an old selection
    state.lastResult = payload.result;
    state.recordId = payload.record_id;
    renderResult(payload.result, payload.workspaces);
    $("ask-status").textContent =
      "查询完成：" + (payload.result.evidence || []).length + " 条证据，知识库 " + (payload.workspaces || []).join("、");
    await loadRecords();
  } catch (err) {
    if (gen !== state.generation) return;
    $("ask-status").textContent = describeError(err);
  }
}

function renderResult(result, workspaces) {
  $("result-panel").hidden = false;
  const statusLabels = {
    complete: "完整",
    partial: "部分覆盖",
    ambiguous: "存在歧义",
    missing: "缺证据",
    stale: "来源已过期",
    service_failure: "服务失败",
  };
  $("result-meta").textContent =
    "请求知识库：" +
    (workspaces || []).join("、") +
    " · 路径 " +
    result.route +
    (result.mode ? " · 模式 " + result.mode : "") +
    " · 状态：" +
    (statusLabels[result.status] || result.status) +
    (result.failures && result.failures.length
      ? " · 失败库：" + result.failures.map((f) => f.workspace).join("、")
      : "");
  const list = $("evidence");
  list.innerHTML = "";
  (result.evidence || []).forEach((item, index) => {
    const li = document.createElement("li");
    li.className = "evidence-item";
    const head = document.createElement("div");
    head.className = "evidence-head";
    head.textContent =
      "[" + index + "] " + item.workspace + " · " + (item.chunk_id || "?");
    li.appendChild(head);
    const body = document.createElement("pre");
    body.textContent = (item.content || "").slice(0, 1200);
    li.appendChild(body);
    const links = document.createElement("div");
    links.className = "evidence-links";
    const textLink = document.createElement("a");
    textLink.textContent = "解析正文";
    textLink.href = "/api/source/" + state.recordId + "/" + index + "/text";
    links.appendChild(textLink);
    li.appendChild(links);
    list.appendChild(li);
  });
  if (!result.evidence || !result.evidence.length) {
    const li = document.createElement("li");
    li.textContent = "没有可用证据。";
    list.appendChild(li);
  }
}

async function doGenerate() {
  if (!state.lastResult || !state.recordId) return;
  $("generation").hidden = false;
  $("generation").textContent = "生成中…";
  try {
    const payload = await api("/api/generate", {
      method: "POST",
      body: { record_id: state.recordId, workspace: state.selection },
    });
    const g = payload.generation;
    $("generation").textContent =
      "模型：" +
      (g.model || "未返回") +
      " · 状态：" +
      g.status +
      " · 引用数：" +
      (g.citations || []).length +
      "\n\n" +
      g.answer;
  } catch (err) {
    $("generation").textContent = describeError(err);
  }
}

async function loadRecords() {
  if (!state.csrf) return;
  try {
    const payload = await api("/api/records");
    const list = $("records");
    list.innerHTML = "";
    (payload.records || []).forEach((rec) => {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = rec.question.slice(0, 40) + " · " + rec.status;
      li.appendChild(label);
      const link = document.createElement("a");
      link.href = "/api/export/" + rec.record_id;
      link.textContent = "导出";
      li.appendChild(link);
      list.appendChild(li);
    });
    if (!list.children.length) {
      const li = document.createElement("li");
      li.textContent = "暂无记录";
      list.appendChild(li);
    }
  } catch (err) {
    /* records are optional */
  }
}

$("login-form").addEventListener("submit", doLogin);
$("logout").addEventListener("click", doLogout);
$("ask").addEventListener("submit", doQuery);
$("generate").addEventListener("click", doGenerate);
$("refresh-records").addEventListener("click", loadRecords);
