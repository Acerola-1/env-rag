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
  answerRequest: 0,
  recordsRequest: 0,
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

function invalidateResult() {
  state.generation += 1;
  state.answerRequest += 1;
  state.recordsRequest += 1;
  state.recordId = null;
  state.lastResult = null;
  $("generate").disabled = false;
  $("generation").hidden = true;
  $("generation").textContent = "";
  $("result-panel").hidden = true;
  $("evidence").innerHTML = "";
  $("records").innerHTML = "";
}

function selectWorkspace(value) {
  state.selection = value;
  // Switching is a client-side act: no model request, and any response from a
  // previous selection is invalidated.
  invalidateResult();
  $("ask-status").textContent = "已切换知识库：" + value + "（未发起模型请求）";
}

async function doLogin(ev) {
  ev.preventDefault();
  invalidateResult();
  const gen = state.generation;
  $("login-error").hidden = true;
  try {
    const payload = await api("/api/login", {
      method: "POST",
      body: { user_id: $("user_id").value, password: $("password").value },
    });
    if (gen !== state.generation) return;
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
    if (gen !== state.generation) return;
    $("login-error").textContent = describeError(err);
    $("login-error").hidden = false;
  }
}

async function doLogout() {
  const csrf = state.csrf;
  invalidateResult();
  state.csrf = null;
  state.user = null;
  state.workspaces = [];
  state.selection = null;
  $("password").value = "";
  $("who").textContent = "未登录";
  $("logout").hidden = true;
  $("login-panel").hidden = false;
  $("app-panel").hidden = true;
  try {
    await api("/api/logout", { method: "POST", headers: {"X-RAG-Token": csrf}, body: {} });
  } catch (err) { /* The UI is already cleared; no late response may restore it. */ }
}

async function doQuery(ev) {
  ev.preventDefault();
  invalidateResult();
  const gen = state.generation;
  $("ask-status").textContent = "查询中…";
  $("result-panel").hidden = true;
  const route = $("route").value;
  const body = {
    workspace: state.selection,
    question: $("question").value,
    route: route,
    mode: route === "pg" ? null : $("mode").value,
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
    complete: "清单范围完整",
    retrieved: "已检索（范围完整性未确认）",
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
      "[" + index + "] " + item.workspace + " · " + ({table_row:"表格行",prose_item:"条款",document:"文档",chunk:"原文分块",lightrag_chunk:"原文分块",entity:"图谱实体",relationship:"图谱关系"}[item.kind] || "证据") + " · " + (item.doc_name || item.chunk_id || "来源关系");
    li.appendChild(head);
    const body = document.createElement("pre");
    if (item.kind === "table_row") {
      body.textContent = [item.caption, item.header, item.cells, item.units, item.footnotes]
        .filter(Boolean).map(x => typeof x === "string" ? x : JSON.stringify(x)).join("\n");
    } else {
      body.textContent = item.text || item.content || "";
    }
    li.appendChild(body);
    const links = document.createElement("div");
    links.className = "evidence-links";
    const textLink = document.createElement("a");
    textLink.textContent = "本条证据全文";
    textLink.href = "/api/source/" + state.recordId + "/" + index + "/text";
    if (state.recordId) links.appendChild(textLink);
    if (state.recordId && item.doc_id) {
      [ ["文档解析全文", "document-text"], ["下载 PDF", "pdf"] ].forEach(([label, kind]) => {
        const link = document.createElement("a");
        link.textContent = label;
        link.href = "/api/source/" + encodeURIComponent(state.recordId) + "/" + index + "/" + kind;
        if (kind === "pdf") link.download = item.doc_name || "source.pdf";
        links.appendChild(link);
      });
    }
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
  const gen = state.generation;
  const recordId = state.recordId;
  const request = ++state.answerRequest;
  const current = () => gen === state.generation && recordId === state.recordId && request === state.answerRequest;
  $("generate").disabled = true;
  $("generation").hidden = false;
  $("generation").textContent = "生成中…";
  try {
    const payload = await api("/api/generate", {
      method: "POST",
      body: { record_id: state.recordId, workspace: state.selection },
    });
    if (!current()) return;
    const g = payload.generation;
    $("generation").textContent =
      "模型：" +
      (g.model || "未返回") +
      " · 状态：" +
      ({success:"已生成",unverified:"引用待核对",context_limit:"超出回答上下文",requires_fresh_complete_evidence:"请先重新检索",no_evidence:"缺少证据"}[g.status] || g.status) + " · 范围：" + ({complete:"清单完整",partial:"部分证据",retrieved:"完整性未确认"}[g.coverage_status] || "未确认") + " · 回答内容需核对" +
      " · 引用数：" +
      (g.citations || []).length +
      "\n\n" +
      g.answer;
  } catch (err) {
    if (current()) $("generation").textContent = describeError(err);
  } finally {
    if (current()) $("generate").disabled = false;
  }
}

async function loadRecords() {
  if (!state.csrf) return;
  const gen = state.generation;
  const user = state.user;
  const request = ++state.recordsRequest;
  try {
    const payload = await api("/api/records");
    if (gen !== state.generation || user !== state.user || request !== state.recordsRequest) return;
    const list = $("records");
    list.innerHTML = "";
    (payload.records || []).forEach((rec) => {
      const li = document.createElement("li");
      const label = document.createElement("span");
      label.textContent = rec.question.slice(0, 40) + " · " + (rec.requires_fresh_query ? "需重新查询" : rec.status);
      li.appendChild(label);
      const link = document.createElement("a");
      link.href = "/api/export/" + rec.record_id;
      link.textContent = "导出";
      if (!rec.requires_fresh_query) li.appendChild(link);
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

function syncRouteMode() { $("mode").disabled = $("route").value === "pg"; }
$("route").addEventListener("change", syncRouteMode);
syncRouteMode();
