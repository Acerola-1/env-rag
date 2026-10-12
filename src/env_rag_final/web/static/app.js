(() => {
  "use strict";

  const STRATEGY_LABELS = {
    naive: "naive",
    local: "local",
    global: "global",
    hybrid: "hybrid",
    mix: "mix",
    pg: "PG",
    "pg+naive": "PG + naive",
    "pg+local": "PG + local",
    "pg+global": "PG + global",
    "pg+hybrid": "PG + hybrid",
    "pg+mix": "PG + mix",
    bypass: "bypass · 纯模型，不检索",
  };

  const STATUS_LABELS = {
    retrieved: "已取得证据",
    ok: "已取得证据",
    generated_pending_semantic_review: "已生成 · 语义未审核",
    context_budget_exceeded: "上下文超过预算 · 未生成",
    model_failure: "模型调用失败",
    stale: "来源已变化",
    degraded: "部分路径降级",
    budget_failure: "预算不足",
    budget_exhausted: "生成额度用尽 · 未发请求",
    success: "完成",
    complete: "完成",
    completed: "完成",
    partial: "部分结果",
    ambiguous: "需要确认范围",
    missing: "未找到",
    unavailable: "不可用",
    failure: "失败",
    failed: "失败",
    error: "失败",
    pending: "等待中",
    running: "处理中",
    reserved: "已预留",
    issued: "已发出",
    not_requested: "未请求生成",
    skipped: "未生成",
    not_generated: "未生成",
    generated: "已生成",
  };

  const dom = {
    main: document.querySelector(".main"),
    form: document.querySelector("#query-form"),
    question: document.querySelector("#question"),
    clearQuestion: document.querySelector("#clear-question"),
    questionError: document.querySelector("#question-error"),
    strategies: document.querySelector("#strategy-fieldset"),
    strategyInputs: Array.from(document.querySelectorAll('input[name="strategies"]')),
    workflowFieldset: document.querySelector("#workflow-fieldset"),
    workflowInputs: Array.from(document.querySelectorAll('input[name="workflow"]')),
    routeInputs: Array.from(document.querySelectorAll('input[name="route"]')),
    ordinaryPanel: document.querySelector("#ordinary-selection"),
    comparisonPanel: document.querySelector("#comparison-selection"),
    ordinaryMode: document.querySelector("#ordinary-mode"),
    nativeModeField: document.querySelector("#native-mode-field"),
    nativeModeHelp: document.querySelector("#native-mode-help"),
    selectionPreview: document.querySelector("#selection-preview"),
    strategyLegend: document.querySelector("#strategy-legend"),
    workspaceTitle: document.querySelector("#workspace-title"),
    workspaceEyebrow: document.querySelector("#workspace-eyebrow"),
    workspaceDescription: document.querySelector("#workspace-description"),
    selectionCount: document.querySelector("#selection-count"),
    generate: document.querySelector("#generate-toggle"),
    modeDescription: document.querySelector("#mode-description"),
    scopeKind: document.querySelector("#query-kind"),
    tableNumber: document.querySelector("#table-number"),
    scope: document.querySelector("#query-scope"),
    submit: document.querySelector("#submit-query"),
    queryStatus: document.querySelector("#query-status"),
    resultsSummary: document.querySelector("#results-summary"),
    resultsTitle: document.querySelector("#results-title"),
    resultsHeading: document.querySelector(".results-heading"),
    emptyState: document.querySelector("#empty-state"),
    results: document.querySelector("#results-list"),
    budgetState: document.querySelector("#budget-state"),
    budgetValues: document.querySelector("#budget-values"),
    savedRecordsButton: null,
    savedQueryLabel: null,
    savedQueryFilter: null,
  };

  if (!dom.form || !dom.question || !dom.results) return;

  const state = {
    token: null,
    queryBusy: false,
    savedRecordsBusy: false,
    generatingRecordId: null,
    requestSequence: 0,
    results: [],
    savedRecords: [],
    savedQueryGroups: [],
    selectedSavedQuery: null,
    showingSavedRecords: false,
    budget: null,
    lastSubmission: null,
    generationErrors: new Map(),
    composing: false,
    comparisonConfigured: false,
  };

  function element(tagName, className, text) {
    const node = document.createElement(tagName);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function isRecord(value) {
    return Boolean(value) && typeof value === "object" && !Array.isArray(value);
  }

  function displayValue(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "string") return value;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    try {
      return JSON.stringify(value, null, 2) ?? String(value);
    } catch {
      return String(value);
    }
  }

  function appendTextField(parent, label, value, className = "data-field") {
    const row = element("div", className);
    row.append(element("dt", "data-label", label));
    row.append(element("dd", "data-value", displayValue(value)));
    parent.append(row);
  }

  function statusLabel(value) {
    if (value === null || value === undefined || value === "") return "未返回";
    const key = String(value).toLowerCase();
    return STATUS_LABELS[key] || String(value);
  }

  function setStatus(message, tone = "neutral") {
    dom.queryStatus.textContent = message;
    dom.queryStatus.dataset.tone = tone;
  }

  function updateSelectionCount() {
    const count = selectedStrategies().length;
    dom.selectionCount.textContent = `${count} 份结果`;
    const labels = selectedStrategies().map(strategy => STRATEGY_LABELS[strategy]);
    dom.selectionPreview.textContent = comparisonEnabled()
      ? `${count} 条独立路线 → ${count} 份结果。${count ? labels.join(" / ") : "请至少选择一条路线"}。结果分别展示，不合成总答案。`
      : `本次路线：${labels[0]} → 1 份结果`;
    dom.selectionPreview.dataset.many = String(count > 3);
  }

  function comparisonEnabled() {
    return dom.workflowInputs.some(input => input.checked && input.value === "compare");
  }

  function selectedStrategies() {
    return globalThis.RAGSelection.resolve(
      comparisonEnabled() ? "compare" : "ask",
      dom.routeInputs.find(input => input.checked)?.value,
      dom.ordinaryMode.value,
      dom.strategyInputs.filter(input => input.checked).map(input => input.value),
    );
  }

  function chooseComparison(strategies) {
    dom.strategyInputs.forEach(input => { input.checked = strategies.includes(input.value); });
    state.comparisonConfigured = true;
    updateSelectionCount();
    updateModeDescription();
    announceSelection();
  }

  function announceSelection() {
    if (state.queryBusy || state.savedRecordsBusy || state.generatingRecordId !== null) return;
    const count = selectedStrategies().length;
    setStatus(count ? `已选择 ${count} 条路线；点击${comparisonEnabled() ? "运行对照" : "开始查询"}后执行。` : "请至少选择一条对照路线。", count ? "neutral" : "warning");
  }

  function syncSelection() {
    const comparison = comparisonEnabled();
    if (comparison && !state.comparisonConfigured) chooseComparison(["local", "pg+local"]);
    dom.ordinaryPanel.hidden = comparison;
    dom.comparisonPanel.hidden = !comparison;
    const route = dom.routeInputs.find(input => input.checked)?.value;
    dom.nativeModeField.hidden = route === "pg" || route === "bypass";
    dom.ordinaryMode.disabled = state.queryBusy || state.savedRecordsBusy || state.generatingRecordId !== null || dom.nativeModeField.hidden;
    dom.nativeModeHelp.textContent = route === "combined"
      ? `PG + ${dom.ordinaryMode.value} 已包含两路检索，只返回一份结果。`
      : `使用 LightRAG 原生 ${dom.ordinaryMode.value} 模式。`;
    dom.strategyLegend.textContent = comparison ? "选择要对照的完整路线" : "选择一条检索路线";
    dom.workspaceTitle.textContent = comparison ? "一题，多路对照" : "查知识库，看原文";
    dom.workspaceEyebrow.textContent = comparison ? "ONE QUESTION · COMPARE ROUTES" : "KNOWLEDGE · SOURCES";
    dom.workspaceDescription.textContent = comparison ? "各路线分别执行、分别回答，便于核对差异。" : "一次提问，一条路线；回答和原文在一起。";
    document.title = comparison ? "对照实验 — 环境知识库" : "知识库问答 — 环境知识库";
    dom.submit.querySelector(".button-label").textContent = comparison ? "运行对照" : "开始查询";
    updateSelectionCount();
    updateModeDescription();
    announceSelection();
  }

  function updateModeDescription() {
    const strategies = selectedStrategies();
    const nativeModes = Array.from(new Set(strategies
      .filter((strategy) => strategy !== "pg" && strategy !== "bypass")
      .map((strategy) => strategy.startsWith("pg+") ? strategy.slice(3) : strategy)));
    const usesPg = strategies.some((strategy) => strategy === "pg" || strategy.startsWith("pg+"));
    const modeNames = strategies.map((strategy) => {
      if (strategy === "pg") return "PG → PG 检索";
      if (strategy === "bypass") return "纯模型 → 不查知识库";
      if (strategy.startsWith("pg+")) return `PG + ${strategy.slice(3)} → 两路证据合并`;
      return `LightRAG ${strategy} → 原生检索`;
    });
    const lines = [`${comparisonEnabled() ? "对照路线" : "当前路线"}：${modeNames.length ? modeNames.join("；") : "尚未选择"}`];

    if (nativeModes.length) {
      if (comparisonEnabled()) lines.push(`涉及 ${nativeModes.length} 种 LightRAG 模式；相同模式的检索证据可以复用。`);
      const graphModes = nativeModes.filter((mode) => mode !== "naive");
      const retrievalCalls = ["向量服务"];
      if (graphModes.length) retrievalCalls.unshift("关键词模型");
      lines.push(`只检索也可能调用${retrievalCalls.join("与")}，按模型平台账号计费。`);
    } else if (usesPg) {
      lines.push("PG 检索本身不调用关键词模型或向量服务。");
    }
    if (usesPg && comparisonEnabled() && strategies.length > 1) lines.push("本次各路线共用一份 PG 检索记录，各自保留结果。");
    if (dom.generate.checked) {
      lines.push(`生成已开启：最多生成 ${strategies.length} 份回答，最多调用答案模型 ${strategies.length} 次，按模型平台账号计费。`);
    } else {
      lines.push("未开启生成：不调用答案模型。需要时可对返回的证据单独生成回答。");
    }
    dom.modeDescription.textContent = lines.join("\n");
  }

  function updateBusyControls() {
    const busy = state.queryBusy || state.savedRecordsBusy || state.generatingRecordId !== null;
    dom.form.setAttribute("aria-busy", String(busy));
    if (dom.main) dom.main.setAttribute("aria-busy", String(busy));
    dom.submit.disabled = busy || state.generatingRecordId !== null;
    dom.clearQuestion.disabled = busy || dom.question.value.length === 0;
    dom.strategies.disabled = busy;
    dom.workflowFieldset.disabled = busy;
    dom.ordinaryMode.disabled = busy || dom.nativeModeField.hidden;
    dom.comparisonPanel.querySelectorAll("button").forEach(button => { button.disabled = busy; });
    dom.question.disabled = busy;
    dom.generate.disabled = busy;
    dom.scopeKind.disabled = busy;
    dom.tableNumber.disabled = busy;
    dom.scope.disabled = busy;
    dom.results.querySelectorAll("button[data-generate]").forEach((button) => {
      button.disabled = busy || state.generatingRecordId !== null;
    });
    dom.results.querySelectorAll("button[data-clarify]").forEach((button) => {
      button.disabled = busy || state.generatingRecordId !== null;
    });
    if (dom.savedRecordsButton) {
      dom.savedRecordsButton.disabled = busy || state.generatingRecordId !== null;
      dom.savedRecordsButton.textContent = state.savedRecordsBusy ? "正在读取…" : "查看已保存结果";
      dom.savedRecordsButton.setAttribute("aria-busy", String(state.savedRecordsBusy));
    }
    if (dom.savedQueryFilter) {
      dom.savedQueryFilter.disabled = busy || state.generatingRecordId !== null || !state.showingSavedRecords;
    }
  }

  function setQuestionError(message) {
    dom.questionError.textContent = message || "";
    dom.questionError.hidden = !message;
    if (message) {
      dom.question.setAttribute("aria-invalid", "true");
    } else {
      dom.question.removeAttribute("aria-invalid");
    }
  }

  function collectOptions(base = {}) {
    const options = { ...base };
    const kind = dom.scopeKind.value.trim();
    const tableNumber = dom.tableNumber.value.trim();
    const scope = dom.scope.value.trim();
    if (kind) options.kind = kind;
    if (tableNumber) options.table_number = tableNumber;
    if (scope) options.scope = scope;
    return options;
  }

  function createUuid() {
    if (!globalThis.crypto || typeof globalThis.crypto.getRandomValues !== "function") {
      throw new Error("当前浏览器无法生成安全的请求编号。请在本机安全上下文中打开页面后重试。");
    }
    const bytes = new Uint8Array(16);
    globalThis.crypto.getRandomValues(bytes);
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
  }

  async function loadConfig() {
    const response = await fetch("/api/config", {cache:"no-store"});
    if (!response.ok) throw new Error("本机服务未就绪。");
    const config = await response.json();
    state.token = config.token;
    renderBudget(config.budget);
  }

  async function requestJson(path, body) {
    if (!state.token) await loadConfig();
    let response;
    try {
      response = await fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json", "X-RAG-Token": state.token },
        body: JSON.stringify(body),
        cache: "no-store",
      });
    } catch {
      throw new Error("无法连接本机服务。请确认服务已启动后重试。");
    }

    let data;
    try {
      data = await response.json();
    } catch {
      throw new Error(response.ok ? "服务返回了无法识别的内容。" : `服务请求失败（HTTP ${response.status}）。`);
    }
    if (!response.ok) throw new Error(data.error || `服务请求失败（HTTP ${response.status}）。`);
    if (!isRecord(data)) throw new Error("服务返回的记录格式不正确。");
    return data;
  }

  async function requestSavedRecords() {
    if (!state.token) await loadConfig();
    let response;
    try {
      response = await fetch("/api/records", {
        method: "GET",
        headers: { Accept: "application/json", "X-RAG-Token": state.token },
        cache: "no-store",
      });
    } catch (_error) {
      throw new Error("读取已保存结果失败；请确认本机服务仍在运行。");
    }

    let data = null;
    try {
      data = await response.json();
    } catch (_error) {
      throw new Error(response.ok ? "服务返回了无法识别的已保存记录。" : `读取保存记录失败（HTTP ${response.status}）。`);
    }
    if (!response.ok) throw new Error(data?.error || `读取保存记录失败（HTTP ${response.status}）。`);
    if (isRecord(data) && data.error) throw new Error(String(data.error));
    if (!Array.isArray(data) && !isRecord(data)) throw new Error("服务返回的已保存记录格式不正确。");
    return data;
  }

  function normalizeResults(results) {
    if (Array.isArray(results)) return results.filter(isRecord);
    if (!isRecord(results)) return [];
    return Object.entries(results).map(([strategy, value]) => {
      if (isRecord(value)) return { strategy: value.strategy || strategy, ...value };
      return { strategy, answer: value };
    });
  }

  function snapshotFromControls(overrides = {}) {
    return {
      query: overrides.query ?? dom.question.value.trim(),
      strategies: overrides.strategies ?? selectedStrategies(),
      generate: overrides.generate ?? dom.generate.checked,
      options: overrides.options ? { ...overrides.options } : collectOptions(),
    };
  }

  function validateSubmission(snapshot) {
    if (!snapshot.query) {
      setQuestionError("请先输入问题。");
      setStatus("问题不能为空。", "error");
      dom.question.focus();
      return false;
    }
    setQuestionError("");
    if (!snapshot.strategies.length) {
      setStatus("至少选择一种检索策略。", "error");
      const firstStrategy = dom.strategyInputs[0];
      if (firstStrategy) firstStrategy.focus();
      return false;
    }
    return true;
  }

  async function runQuery(overrides = {}) {
    if (state.queryBusy || state.savedRecordsBusy || state.generatingRecordId !== null) return;

    const snapshot = snapshotFromControls(overrides);
    if (!validateSubmission(snapshot)) return;

    let submissionId;
    try {
      submissionId = createUuid();
    } catch (error) {
      setStatus(error.message, "error");
      return;
    }

    const request = {
      query: snapshot.query,
      strategies: snapshot.strategies,
      generate: snapshot.generate,
      submission_id: submissionId,
    };
    if (Object.keys(snapshot.options).length > 0) request.options = snapshot.options;

    const sequence = ++state.requestSequence;
    if (dom.resultsTitle) dom.resultsTitle.textContent = "本次结果";
    state.showingSavedRecords = false;
    state.savedRecords = [];
    state.savedQueryGroups = [];
    state.selectedSavedQuery = null;
    if (dom.savedQueryLabel) dom.savedQueryLabel.hidden = true;
    state.queryBusy = true;
    state.lastSubmission = snapshot;
    state.results = [];
    state.budget = null;
    state.generationErrors.clear();
    dom.results.replaceChildren();
    dom.emptyState.hidden = false;
    dom.emptyState.querySelector("h3").textContent = "正在检索";
    dom.emptyState.querySelector("p").textContent = "正在按所选策略读取证据，请稍候。";
    dom.resultsSummary.textContent = `${snapshot.strategies.length} 个策略已提交。`;
    setStatus("正在检索所选策略…", "busy");
    updateBusyControls();

    try {
      const payload = await requestJson("/api/query", request);
      if (sequence !== state.requestSequence) return;
      state.results = normalizeResults(payload.results);
      state.budget = payload.budget ?? null;
      renderBudget(state.budget);
      renderResults();
      const count = state.results.length;
      setStatus(count ? `已返回 ${count} 条策略记录。` : "服务未返回策略记录。", count ? "success" : "warning");
      if (!count) {
        dom.emptyState.querySelector("h3").textContent = "没有策略记录";
        dom.emptyState.querySelector("p").textContent = "服务没有返回可展示的结果，请检查策略状态后再试。";
      }
      dom.resultsSummary.textContent = count
        ? `返回 ${count} 条记录；每张卡只展示该策略本次检索得到的内容。`
        : "本次没有可展示的结果。";
    } catch (error) {
      if (sequence !== state.requestSequence) return;
      renderBudget(state.budget);
      dom.emptyState.hidden = false;
      dom.emptyState.querySelector("h3").textContent = "本次请求未完成";
      dom.emptyState.querySelector("p").textContent = error.message;
      dom.resultsSummary.textContent = "没有收到可展示的策略记录。";
      setStatus(error.message, "error");
    } finally {
      if (sequence === state.requestSequence) {
        state.queryBusy = false;
        updateBusyControls();
      }
    }
  }

  function formatElapsed(value) {
    if (value === null || value === undefined || value === "") return "不可用";
    const number = Number(value);
    if (!Number.isFinite(number) || number < 0) return "不可用";
    return `${new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 1 }).format(number)} ms`;
  }

  function pickArray(...values) {
    for (const value of values) {
      if (Array.isArray(value)) return value;
    }
    return [];
  }

  function getChunks(result) {
    return pickArray(
      result.chunks,
      result.evidence?.chunks,
      result.merged_evidence?.chunks,
      result.pg?.chunks,
      result.pg_result?.chunks,
      result.native?.chunks,
      result.data?.chunks,
      result.raw_data?.data?.chunks,
      result.retrieval?.chunks,
    ).filter(isRecord);
  }

  function getEntities(result) {
    return pickArray(
      result.entities,
      result.evidence?.entities,
      result.native?.entities,
      result.data?.entities,
      result.raw_data?.data?.entities,
      result.retrieval?.entities,
    );
  }

  function getRelationships(result) {
    return pickArray(
      result.relationships,
      result.relations,
      result.evidence?.relationships,
      result.evidence?.relations,
      result.native?.relations,
      result.data?.relationships,
      result.data?.relations,
      result.raw_data?.data?.relationships,
      result.raw_data?.data?.relations,
      result.retrieval?.relationships,
    );
  }

  function getEnumeration(result) {
    return result.enumeration || result.pg?.enumeration || result.data?.enumeration || result.answer?.enumeration || null;
  }

  function getEnumerationItems(result) {
    const enumeration = getEnumeration(result);
    const answer = enumeration?.answer;
    if (Array.isArray(answer?.items)) return answer.items;
    if (Array.isArray(enumeration?.items)) return enumeration.items;
    return [];
  }

  function getDiscovery(result) {
    return result.pg?.discovery ?? result.pg_result?.discovery ?? result.discovery ?? null;
  }

  function getRecordId(result) {
    return result.record_id ?? result.recordId ?? result.id ?? null;
  }

  function safePathSegment(value) {
    const text = String(value ?? "");
    if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/.test(text) || text === "." || text === "..") return null;
    return encodeURIComponent(text);
  }

  function getChunkIndex(chunk, arrayIndex) {
    // Transport indexes refer to this record's actual 0-based chunk array.
    return arrayIndex;
  }

  function sourceUrl(recordId, chunkIndex, fileType) {
    const safeRecordId = safePathSegment(recordId);
    const index = Number(chunkIndex);
    if (!safeRecordId || !Number.isInteger(index) || index < 0 || !["pdf", "text"].includes(fileType)) return null;
    return `/api/source/${safeRecordId}/${index}/${fileType}`;
  }

  function documentSourceUrl(recordId, docId, fileType) {
    const safeRecordId = safePathSegment(recordId);
    const safeDocId = safePathSegment(docId);
    if (!safeRecordId || !safeDocId || !["pdf", "text"].includes(fileType)) return null;
    return `/api/document/${safeRecordId}/${safeDocId}/${fileType}`;
  }

  function documentSourceTargetId(cardIndex, docId) {
    return `document-source-${cardIndex + 1}-${encodeURIComponent(String(docId))}`;
  }

  function makeSourceLinks(parent, recordId, chunk, chunkIndex) {
    const links = element("div", "source-links");
    const index = getChunkIndex(chunk, chunkIndex);
    const fileAvailability = isRecord(chunk.files) ? chunk.files : {};
    const pdfAvailable = chunk.pdf_available ?? chunk.source_pdf_available ?? fileAvailability.pdf?.available;
    const textAvailable = chunk.text_available ?? chunk.source_text_available ?? fileAvailability.text?.available;
    const addLink = (fileType, label, available) => {
      const url = sourceUrl(recordId, index, fileType);
      if (!url || available === false) {
        links.append(element("span", "unavailable-label", `${label}不可用`));
        return;
      }
      const link = element("a", "source-link", label);
      link.href = url;
      if (fileType === "pdf") {
        link.download = "";
      } else {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      links.append(link);
    };
    addLink("pdf", "下载原始 PDF", pdfAvailable);
    addLink("text", "查看解析文本", textAvailable);
    parent.append(links);
  }

  function collectReferenceIds(value, target = new Set(), depth = 0) {
    if (value === null || value === undefined || depth > 3) return target;
    if (typeof value === "string" || typeof value === "number") {
      target.add(String(value));
      return target;
    }
    if (Array.isArray(value)) {
      value.forEach((item) => collectReferenceIds(item, target, depth + 1));
      return target;
    }
    if (isRecord(value)) {
      for (const key of ["reference_id", "referenceId", "ref_id", "citation_id"]) {
        if (value[key] !== undefined && value[key] !== null) target.add(String(value[key]));
      }
      for (const key of ["references", "sources", "citations"]) {
        if (value[key] !== undefined) collectReferenceIds(value[key], target, depth + 1);
      }
    }
    return target;
  }

  function isCatalogRowCitation(citation) {
    return isRecord(citation) && (
      citation.kind === "catalog_row" ||
      (citation.catalog_row !== undefined && citation.catalog_row !== null)
    );
  }

  function findChunkTarget(citation, chunks, cardIndex) {
    let raw = citation;
    let explicitIndex = null;
    const catalogRow = isCatalogRowCitation(citation);
    if (isRecord(citation)) {
      const chunkReference = citation.reference_id ?? citation.referenceId ?? citation.ref_id ?? citation.chunk_id ?? citation.chunk_ids?.[0];
      raw = catalogRow ? chunkReference : chunkReference ?? citation.id ?? citation.index ?? citation.chunk_index;
      const possibleIndex = catalogRow ? citation.chunk_index : citation.index ?? citation.chunk_index;
      if (possibleIndex !== undefined && /^\d+$/.test(String(possibleIndex))) explicitIndex = Number(possibleIndex);
    }
    if (raw !== null && raw !== undefined) {
      const token = String(raw).trim();
      const match = chunks.findIndex((chunk) => {
        const ids = collectReferenceIds(chunk);
        return ids.has(token) || String(chunk.chunk_id ?? chunk.id ?? "") === token;
      });
      if (match >= 0) return `evidence-chunk-${cardIndex + 1}-${match + 1}`;
      if (catalogRow) return null;
      if (explicitIndex === null) {
        const numeric = token.match(/^\[?(\d+)\]?$/);
        if (numeric) explicitIndex = Number(numeric[1]);
      }
    }
    if (catalogRow) return null;
    if (explicitIndex !== null && explicitIndex >= 1 && explicitIndex <= chunks.length) {
      return `evidence-chunk-${cardIndex + 1}-${explicitIndex}`;
    }
    return null;
  }

  function findDocumentSourceTarget(citation, result, cardIndex) {
    if (!isCatalogRowCitation(citation)) return null;
    const catalogRow = isRecord(citation.catalog_row) ? citation.catalog_row : null;
    const docId = citation.doc_id ?? citation.document_id ?? catalogRow?.doc_id ?? catalogRow?.document_id;
    if (docId === undefined || docId === null) return null;
    const sources = Array.isArray(result?.document_sources) ? result.document_sources : [];
    const source = sources.find((item) => isRecord(item) && String(item.doc_id ?? "") === String(docId));
    return source ? documentSourceTargetId(cardIndex, source.doc_id) : null;
  }

  function formatCitationLocator(citation) {
    const locator = citation?.locator;
    if (isRecord(locator)) {
      const labels = {
        block: "文本块",
        text_block: "文本块",
        paragraph: "段落",
        table: "表格",
        table_row: "表格行",
        catalog_row: "目录行",
      };
      const kind = typeof locator.kind === "string" ? locator.kind : "";
      const label = labels[kind] || (kind ? `定位 ${kind}` : "原文定位");
      const blockId = locator.blockid ?? locator.block_id;
      return blockId === undefined || blockId === null
        ? label
        : `${label} · 块 ${displayValue(blockId)}`;
    }
    if (locator !== undefined && locator !== null && locator !== "") return displayValue(locator);
    if (isCatalogRowCitation(citation)) {
      return `目录行 · ${citation.doc_name ?? citation.doc_id ?? "未记录文档"}`;
    }
    return citation?.table_id ?? "原文";
  }

  function citationNode(citation, chunks, cardIndex, result = null) {
    if (Array.isArray(citation)) {
      const group = element("span", "citation-list");
      citation.forEach((item, index) => {
        if (index) group.append(document.createTextNode("、"));
        group.append(citationNode(item, chunks, cardIndex, result));
      });
      return group;
    }
    const text = isRecord(citation)
      ? `${formatCitationLocator(citation)}${citation.row_in_fragment !== undefined ? ` · 原始行 ${citation.row_in_fragment}` : ""}`
      : displayValue(citation);
    const locatorDetails = isRecord(citation) && isRecord(citation.locator)
      ? `完整定位：${displayValue(citation.locator)}`
      : null;
    const targetId = findChunkTarget(citation, chunks, cardIndex)
      || findDocumentSourceTarget(citation, result, cardIndex);
    if (!targetId) {
      const span = element("span", "citation", text);
      if (locatorDetails) {
        span.title = locatorDetails;
        span.setAttribute("aria-label", `${text}；${locatorDetails}`);
      }
      return span;
    }
    const link = element("a", "citation", text);
    link.href = `#${targetId}`;
    link.setAttribute("aria-label", `查看本卡中与引用 ${text} 对应的证据${locatorDetails ? `。${locatorDetails}` : ""}`);
    if (locatorDetails) link.title = locatorDetails;
    link.addEventListener("click", (event) => {
      const target = document.getElementById(targetId);
      if (!target) return;
      event.preventDefault();
      for (let node = target; node; node = node.parentElement) {
        if (node instanceof HTMLDetailsElement) node.open = true;
      }
      requestAnimationFrame(() => {
        target.scrollIntoView({ behavior: "smooth", block: "center" });
        target.focus({ preventScroll: true });
      });
    });
    return link;
  }

  function markdownCitationNode(id, result, chunks, cardIndex) {
    const citation = result.generation_reference_map?.[id] || `[${id}]`;
    const node = citationNode(citation, chunks, cardIndex, result);
    const citationLeaves = node.classList?.contains("citation")
      ? [node]
      : Array.from(node.querySelectorAll?.(".citation") ?? []);
    if (citationLeaves.length) {
      citationLeaves.forEach((leaf) => { leaf.textContent = `[${id}]`; });
    } else {
      node.textContent = `[${id}]`;
    }
    return node;
  }

  function renderAnswer(parent, result, chunks, cardIndex) {
    const section = element("section", "answer");
    section.append(element("h4", "subsection-title", "回答"));
    const answer = result.answer ?? result.llm_response?.content ?? result.response ?? null;
    let answerText = null;
    if (typeof answer === "string") answerText = answer;
    else if (isRecord(answer)) {
      answerText = answer.text ?? answer.content ?? answer.summary ?? answer.message ?? null;
    }

    if (answerText) {
      const copy = element("div", "answer-copy");
      copy.append(window.RAGMarkdown.render(answerText, (id) => markdownCitationNode(id, result, chunks, cardIndex)));
      section.append(copy);
    } else if (answer === null || answer === undefined || answer === "") {
      section.append(element("p", "empty-copy", "本条记录没有回答文本。"));
    } else if (!isRecord(answer) || !Array.isArray(answer.items)) {
      const details = element("details", "answer-data");
      details.append(element("summary", "", "查看回答结构"));
      const pre = element("pre", "json-view", displayValue(answer));
      details.append(pre);
      section.append(details);
    } else {
      if (getEnumerationItems(result).length) {
        section.append(element("p", "empty-copy", "清单条目在下方“范围清单”阶段单独列出。"));
      } else {
        const details = element("details", "answer-data");
        details.append(element("summary", "", "查看回答结构"));
        details.append(element("pre", "json-view", displayValue(answer)));
        section.append(details);
      }
    }

    parent.append(section);
  }

  function generatedAnswerText(result) {
    const answer = result.answer;
    if (typeof answer === "string" && answer.trim()) return answer;
    if (isRecord(answer)) {
      const text = answer.text ?? answer.content ?? answer.summary ?? answer.message;
      if (typeof text === "string" && text.trim()) return text;
    }
    const fallback = result.llm_response?.content ?? result.response;
    return typeof fallback === "string" && fallback.trim() ? fallback : null;
  }

  function renderEnumerationItem(item, index, chunks, cardIndex, result) {
    const article = element("li", "enumeration-item");
    article.append(element("h5", "enumeration-item-title", `第 ${index + 1} 项`));
    if (isRecord(item)) {
      if (item.doc_name !== undefined) {
        const documentName = element("p", "enumeration-doc");
        documentName.append(element("span", "data-label", "文档："));
        documentName.append(document.createTextNode(displayValue(item.doc_name)));
        article.append(documentName);
      }
      if (item.cells !== undefined) {
        const cells = element("dl", "enumeration-cells");
        if (Array.isArray(item.cells)) {
          item.cells.forEach((cell, cellIndex) => {
            const label = isRecord(cell)
              ? cell.label ?? cell.name ?? cell.column ?? `单元格 ${cellIndex + 1}`
              : `单元格 ${cellIndex + 1}`;
            const value = isRecord(cell) ? cell.value ?? cell.text ?? cell.content ?? cell : cell;
            appendTextField(cells, label, value, "enumeration-cell");
          });
        } else if (isRecord(item.cells)) {
          Object.entries(item.cells).forEach(([label, value]) => appendTextField(cells, label, value, "enumeration-cell"));
        } else {
          appendTextField(cells, "内容", item.cells, "enumeration-cell");
        }
        article.append(cells);
      }
      if (item.text !== undefined && item.text !== null) {
        const text = element("p", "enumeration-text", displayValue(item.text));
        article.append(text);
      }
      if (item.citation !== undefined && item.citation !== null) {
        const citation = element("p", "enumeration-citation");
        citation.append(element("span", "data-label", "引用："));
        citation.append(citationNode(item.citation, chunks, cardIndex, result));
        article.append(citation);
      }
    } else {
      article.append(element("p", "enumeration-text", displayValue(item)));
    }
    return article;
  }

  function renderChunkDetails(chunk, index, cardIndex, recordId) {
    const details = element("details", "evidence-item");
    details.id = `evidence-chunk-${cardIndex + 1}-${index + 1}`;
    details.tabIndex = -1;
    const chunkId = chunk.chunk_id ?? chunk.id ?? "未提供 chunk_id";
    const docName = chunk.doc_name ?? chunk.document_name ?? chunk.file_name ?? chunk.doc_id ?? "来源文档";
    details.append(element("summary", "evidence-summary", `${docName} · ${chunkId}`));

    const fields = element("dl", "evidence-fields");
    appendTextField(fields, "chunk_id", valueOrUnrecorded(chunk.chunk_id ?? chunk.id));
    appendTextField(fields, "doc_id", valueOrUnrecorded(chunk.doc_id ?? chunk.full_doc_id ?? chunk.document_id));
    appendTextField(fields, "file_path", valueOrUnrecorded(chunk.file_path ?? chunk.source_path));
    appendTextField(fields, "sources", valueOrUnrecorded(chunk.sources ?? chunk.source ?? chunk.references));
    appendTextField(fields, "敏感值掩码", chunk.content_redacted === undefined
      ? "未记录"
      : chunk.content_redacted === true ? "已应用" : "未应用");
    appendTextField(fields, "原文 SHA-256", valueOrUnrecorded(chunk.content_sha256));
    appendTextField(fields, "展示 SHA-256", valueOrUnrecorded(chunk.display_content_sha256));
    details.append(fields);

    if (chunk.content !== undefined && chunk.content !== null) {
      if (chunk.content_redacted === true) {
        details.append(element("p", "redaction-note", "展示文本有敏感值掩码；原文 SHA 与展示 SHA 分列，核对请看来源文件。"));
        details.append(element("p", "data-label", "展示文本"));
      }
      const content = element("pre", "chunk-content", displayValue(chunk.content));
      details.append(content);
    } else {
      details.append(element("p", "empty-copy", "content：未记录。"));
    }
    makeSourceLinks(details, recordId, chunk, index);
    return details;
  }

  function valueOrUnrecorded(value) {
    return value === undefined || value === null || value === "" ? "未记录" : value;
  }

  function availabilityLabel(value) {
    if (value === true) return "可用";
    if (value === false) return "不可用";
    return "未记录";
  }

  function makeDocumentSourceLinks(parent, recordId, source) {
    const links = element("div", "source-links");
    const addLink = (fileType, label, available) => {
      if (available !== true) {
        links.append(element("span", "unavailable-label", `${label} · ${availabilityLabel(available)}`));
        return;
      }
      if (recordId === undefined || recordId === null || recordId === ""
        || source.doc_id === undefined || source.doc_id === null || source.doc_id === "") {
        links.append(element("span", "unavailable-label", `${label} · 未记录`));
        return;
      }
      const url = documentSourceUrl(recordId, source.doc_id, fileType);
      if (!url) {
        links.append(element("span", "unavailable-label", `${label} · 链接不可用`));
        return;
      }
      const link = element("a", "source-link", label);
      link.href = url;
      if (fileType === "pdf") {
        link.download = "";
      } else {
        link.target = "_blank";
        link.rel = "noopener noreferrer";
      }
      links.append(link);
    };
    addLink("pdf", "下载原始 PDF", source.pdf_available);
    addLink("text", "查看解析文本", source.text_available);
    parent.append(links);
  }

  function renderDocumentSources(parent, result, cardIndex, recordId) {
    const sourcesRecorded = Array.isArray(result.document_sources);
    const sources = sourcesRecorded ? result.document_sources : [];
    const section = element("details", "evidence document-sources");
    section.append(element("summary", "evidence-heading", sourcesRecorded
      ? `文档来源 · ${sources.length}`
      : "文档来源 · 未记录"));
    const body = element("div", "evidence-body");
    if (!sourcesRecorded) {
      body.append(element("p", "empty-copy", "document_sources：未记录。"));
    } else if (!sources.length) {
      body.append(element("p", "empty-copy", "本条记录没有文档来源条目。"));
    } else {
      sources.forEach((source, index) => {
        if (!isRecord(source)) {
          body.append(element("pre", "json-view", displayValue(source)));
          return;
        }
        const sourceRow = element("details", "evidence-item document-source");
        const docIdPresent = source.doc_id !== undefined && source.doc_id !== null && source.doc_id !== "";
        sourceRow.id = docIdPresent
          ? documentSourceTargetId(cardIndex, source.doc_id)
          : `document-source-${cardIndex + 1}-unrecorded-${index + 1}`;
        sourceRow.tabIndex = -1;
        const label = valueOrUnrecorded(source.doc_name);
        sourceRow.append(element("summary", "evidence-summary", displayValue(label)));

        const fields = element("dl", "evidence-fields document-source-fields");
        appendTextField(fields, "doc_id", valueOrUnrecorded(source.doc_id));
        appendTextField(fields, "doc_name", valueOrUnrecorded(source.doc_name));
        appendTextField(fields, "pdf_available", availabilityLabel(source.pdf_available));
        appendTextField(fields, "text_available", availabilityLabel(source.text_available));
        sourceRow.append(fields);
        makeDocumentSourceLinks(sourceRow, recordId, source);
        body.append(sourceRow);
      });
    }
    section.append(body);
    parent.append(section);
  }

  function renderEvidenceDetails(parent, title, items, renderItem, extraClass = "") {
    const details = element("details", `evidence ${extraClass}`.trim());
    const summary = element("summary", "evidence-heading", `${title} · ${items.length}`);
    details.append(summary);
    const body = element("div", "evidence-body");
    if (!items.length) {
      body.append(element("p", "empty-copy", "本条记录没有这类证据。"));
    } else {
      items.forEach((item, index) => body.append(renderItem(item, index)));
    }
    details.append(body);
    parent.append(details);
  }

  function appendStageJson(parent, label, value) {
    if (value === undefined || value === null) return false;
    const details = element("details", "evidence-stage-data");
    details.append(element("summary", "", label));
    details.append(element("pre", "json-view", displayValue(value)));
    parent.append(details);
    return true;
  }

  function appendStageList(parent, label, values) {
    if (!Array.isArray(values) || !values.length) return false;
    const details = element("details", "evidence-stage-data");
    details.append(element("summary", "", `${label} · ${values.length}`));
    const list = element("ol", "stage-record-list");
    values.forEach((value) => {
      const item = element("li", "");
      item.append(element("pre", "json-view", displayValue(value)));
      list.append(item);
    });
    details.append(list);
    parent.append(details);
    return true;
  }

  function evidenceStage(parent, title, count = null) {
    const details = element("details", "evidence evidence-stage");
    details.append(element("summary", "evidence-heading", count === null ? title : `${title} · ${count}`));
    const body = element("div", "evidence-stage-body");
    details.append(body);
    parent.append(details);
    return body;
  }

  function renderCandidateStage(parent, result) {
    const discovery = getDiscovery(result);
    const pg = isRecord(result.pg) ? result.pg : isRecord(result.pg_result) ? result.pg_result : null;
    const native = isRecord(result.native) ? result.native : null;
    const discoveryCandidates = Array.isArray(discovery?.discovery_candidates)
      ? discovery.discovery_candidates
      : Array.isArray(discovery?.candidates) ? discovery.candidates : [];
    const typedTargets = pickArray(pg?.typed_targets);
    const choices = pickArray(pg?.choices);
    const count = discoveryCandidates.length + typedTargets.length + choices.length;
    const body = evidenceStage(parent, "发现候选", count || null);
    let hasData = false;

    if (discovery) {
      hasData = true;
      if (discoveryCandidates.length) {
        appendStageList(body, "PG discovery candidates", discoveryCandidates);
      } else {
        appendStageJson(body, "PG discovery 记录", discovery);
      }
    }
    hasData = appendStageList(body, "PG typed_targets", typedTargets) || hasData;
    hasData = appendStageList(body, "PG choices", choices) || hasData;
    if (native?.raw_data !== undefined) {
      hasData = appendStageJson(body, "LightRAG 原始检索返回（native.raw_data）", native.raw_data) || hasData;
    }
    if (Array.isArray(native?.receipts) && native.receipts.length) {
      hasData = appendStageList(body, "原生检索调用回执", native.receipts) || hasData;
    }
    if (result.failure_receipts !== undefined) {
      hasData = appendStageJson(body, "失败调用回执", result.failure_receipts) || hasData;
    }
    if (result.local_failure !== undefined) {
      hasData = appendStageJson(body, "原生检索失败记录", result.local_failure) || hasData;
    }
    if (result.native_skipped !== undefined) {
      hasData = appendStageJson(body, "native_skipped", result.native_skipped) || hasData;
    }
    if (!hasData) body.append(element("p", "empty-copy", "独立候选发现字段：未记录。"));
  }

  function renderMergedSourceStage(parent, result, chunks, cardIndex, recordId) {
    const body = evidenceStage(parent, "合并原文", chunks.length);
    if (chunks.length) {
      const list = element("div", "evidence-stage-chunks");
      chunks.forEach((chunk, index) => list.append(renderChunkDetails(chunk, index, cardIndex, recordId)));
      body.append(list);
    } else if (result.merged_evidence !== undefined) {
      appendStageJson(body, "记录中的 merged_evidence", result.merged_evidence);
    } else if (result.evidence !== undefined) {
      appendStageJson(body, "记录中的 evidence", result.evidence);
    } else {
      body.append(element("p", "empty-copy", "合并原文 chunks：未记录。"));
    }
  }

  function renderFinalModelStage(parent, result) {
    const messages = Array.isArray(result.generation_messages) ? result.generation_messages : [];
    let evidenceCount = null;
    if (isRecord(result.generation_reference_map)) {
      evidenceCount = `${Object.keys(result.generation_reference_map).length} 个范围项引用`;
    } else if (Array.isArray(result.used_evidence)) {
      evidenceCount = `${result.used_evidence.length} 个 chunk 证据`;
    }
    const issued = isRecord(result.answer_call);
    const body = evidenceStage(parent, issued ? "最终模型使用" : "准备的模型证据（未发送）", evidenceCount);
    if (!issued) body.append(element("p", "empty-copy", "本条记录没有答案模型实发凭证；以下是准备材料，不代表模型已经使用。"));
    let hasData = false;

    const metadata = element("dl", "evidence-fields stage-metadata");
    if (result.generation_status !== undefined) {
      appendTextField(metadata, "生成状态", statusLabel(result.generation_status));
    }
    appendTextField(metadata, "模型消息数", Array.isArray(result.generation_messages) ? messages.length : "未记录");
    if (isRecord(result.generation_reference_map)) {
      appendTextField(metadata, "范围项引用数", Object.keys(result.generation_reference_map).length);
    } else if (Array.isArray(result.used_evidence)) {
      appendTextField(metadata, "chunk 证据数", result.used_evidence.length);
    } else {
      appendTextField(metadata, "模型证据数", "未记录");
    }
    if (metadata.childElementCount) {
      body.append(metadata);
      hasData = true;
    }
    if (messages.length) {
      messages.forEach((message, index) => {
        if (!isRecord(message)) {
          appendStageJson(body, `生成消息 ${index + 1}`, message);
          hasData = true;
          return;
        }
        const details = element("details", "evidence-stage-data");
        details.append(element("summary", "", `${message.role || "消息"} · ${index + 1}`));
        details.append(element("pre", "chunk-content", displayValue(message.content)));
        body.append(details);
        hasData = true;
      });
    } else if (typeof result.native?.native_prompt === "string") {
      hasData = appendStageJson(body, "检索阶段保存的 native_prompt", result.native.native_prompt) || hasData;
    }

    for (const [key, label] of [
      ["used_evidence", "实际记录的 used_evidence"],
      ["generation_reference_map", "generation_reference_map"],
      ["generation_context_sha256", "generation_context_sha256"],
      ["answer_call", "答案调用回执"],
      ["generation_failure", "答案生成失败记录"],
    ]) {
      if (result[key] !== undefined) hasData = appendStageJson(body, label, result[key]) || hasData;
    }
    if (!hasData) body.append(element("p", "empty-copy", "本条记录未保存最终模型消息或原生提示词。"));
  }

  function renderScopeStage(parent, result, chunks, cardIndex) {
    const enumeration = getEnumeration(result);
    const items = getEnumerationItems(result);
    const body = evidenceStage(parent, "范围清单", items.length || null);
    if (items.length) body.parentElement.open = true;
    let hasData = false;
    if (enumeration && enumeration.coverage_status !== undefined) {
      const metadata = element("dl", "evidence-fields stage-metadata");
      appendTextField(metadata, "coverage_status", statusLabel(enumeration.coverage_status));
      body.append(metadata);
      hasData = true;
    }
    if (items.length) {
      const list = element("ol", "enumeration-list stage-enumeration-list");
      items.forEach((item, index) => list.append(renderEnumerationItem(item, index, chunks, cardIndex, result)));
      body.append(list);
      hasData = true;
    } else if (enumeration) {
      hasData = appendStageJson(body, "记录中的 enumeration", enumeration) || hasData;
    }
    if (!hasData) body.append(element("p", "empty-copy", "范围清单：未记录。"));
  }

  function renderEvidenceStages(parent, result, chunks, cardIndex, recordId) {
    const stages = element("section", "evidence-stages");
    stages.append(element("h4", "subsection-title", "证据形成过程"));
    renderCandidateStage(stages, result);
    renderMergedSourceStage(stages, result, chunks, cardIndex, recordId);
    renderFinalModelStage(stages, result);
    renderScopeStage(stages, result, chunks, cardIndex);
    parent.append(stages);
  }

  function renderJsonItem(item, index, label) {
    const details = element("details", "evidence-item graph-item");
    details.append(element("summary", "evidence-summary", `${label} ${index + 1}`));
    details.append(element("pre", "json-view", displayValue(item)));
    return details;
  }

  function choicesFor(result) {
    return pickArray(
      result.pg?.choices,
      result.pg_result?.choices,
      result.choices,
      result.enumeration?.choices,
      result.data?.choices,
    ).filter(isRecord);
  }

  function isAmbiguous(result) {
    const statuses = [result.status, result.pg?.status, result.pg_result?.status, result.enumeration?.status];
    return statuses.some((value) => String(value || "").toLowerCase() === "ambiguous");
  }

  function renderClarification(parent, result) {
    const choices = choicesFor(result);
    if (!choices.length || !isAmbiguous(result) || !state.lastSubmission) return;
    const section = element("section", "clarification");
    section.append(element("h4", "subsection-title", "选择文档以继续原问题"));
    section.append(element("p", "helper-copy", "选择后会带上原问题和 document 范围重新提交。"));
    const label = element("label", "", "目标文档");
    const select = element("select", "clarification-select");
    select.setAttribute("aria-label", "选择目标文档");
    const placeholder = element("option", "", "请选择要查看的文档");
    placeholder.value = ""; select.append(placeholder);
    for (const choice of choices) {
      if (!choice.doc_id) continue;
      const option = element("option", "", choice.doc_name || choice.doc_id);
      option.value = choice.doc_id; select.append(option);
    }
    label.append(select); section.append(label);
    const button = element("button", "clarification-choice", "使用所选文档继续");
    button.type = "button"; button.dataset.clarify = "true"; button.disabled = true;
    select.addEventListener("change", () => {button.disabled = !select.value || state.queryBusy;});
    button.addEventListener("click", () => {
      if (!select.value) return;
      const original = state.lastSubmission;
      runQuery({query:original.query, strategies:[result.strategy], generate:original.generate,
                options:{...original.options,document:select.value}});
    });
    section.append(button);

    parent.append(section);
  }

  function appendRecordActions(parent, result, cardIndex) {
    const recordId = getRecordId(result);
    const safeId = safePathSegment(recordId);
    const actions = element("div", "toolbar result-actions");
    if (safeId) {
      const exportLink = element("a", "export-button", "导出本卡 JSON");
      exportLink.href = `/api/export/${safeId}`;
      actions.append(exportLink);

      const generation = String(result.generation_status ?? "").toLowerCase();
      const generationDone = ["success", "complete", "completed", "generated"].includes(generation)
        || result.llm_response?.llm_generated === true;
      const waitingForClarification = isAmbiguous(result) && choicesFor(result).length > 0;
      const canGenerate = !generationDone && (generation === "not_requested" || (state.budget?.mode === "interactive" && generation === "budget_exhausted" && !result.answer_call)) && !waitingForClarification && !["missing","stale","failure","budget_failure"].includes(result.status);
      if (canGenerate) {
        const button = element("button", "generate-button", "生成本次证据的回答");
        button.type = "button";
        button.dataset.generate = "true";
        button.addEventListener("click", () => generateForCard(recordId, cardIndex));
        actions.append(button);
      }
    }
    if (actions.childElementCount) parent.append(actions);
  }

  function resultAnswerExists(result) {
    return generatedAnswerText(result) !== null;
  }

  async function generateForCard(recordId, cardIndex) {
    if (state.queryBusy || state.savedRecordsBusy || state.generatingRecordId !== null) return;
    const safeId = safePathSegment(recordId);
    if (!safeId) return;
    state.generatingRecordId = String(recordId);
    setStatus("正在为已检索的记录生成回答，不会重新检索…", "busy");
    updateBusyControls();
    renderResults();
    try {
      const payload = await requestJson("/api/generate", { record_id: recordId });
      if (payload.budget) {state.budget = payload.budget; renderBudget(state.budget);}
      const record = isRecord(payload.result) ? payload.result : isRecord(payload.record) ? payload.record : payload;
      const currentIndex = state.results.findIndex((item) => String(getRecordId(item)) === String(recordId));
      if (currentIndex >= 0 && isRecord(record)) {
        state.results[currentIndex] = record;
        state.generationErrors.delete(String(recordId));
      } else if (cardIndex >= 0 && cardIndex < state.results.length && isRecord(record)) {
        state.results[cardIndex] = record;
        state.generationErrors.delete(String(recordId));
      }
      if (isRecord(record)) replaceSavedRecord(recordId, record);
      if (payload.budget !== undefined) {
        state.budget = payload.budget;
        renderBudget(state.budget);
      }
      const generated = String(record.generation_status || "").startsWith("generated");
      setStatus(generated ? "已更新这张结果卡的回答；检索记录保持不变。" : `生成状态：${statusLabel(record.generation_status)}；检索清单保持不变。`, generated ? "success" : "error");
      renderResults();
    } catch (error) {
      state.generationErrors.set(String(recordId), error.message);
      setStatus(error.message, "error");
      renderResults();
    } finally {
      state.generatingRecordId = null;
      updateBusyControls();
      renderResults();
    }
  }

  function renderResult(result, cardIndex) {
    const card = element("article", "result-card");
    card.id = `result-card-${cardIndex + 1}`;
    const strategy = result.strategy ?? result.actual_strategy ?? "未标记策略";
    const status = result.status ?? "unknown";
    const generationStatus = result.generation_status ?? (resultAnswerExists(result) ? "generated" : "not_requested");
    const queryText = savedRecordQuestion(result) ?? "未记录";
    const generationProfile = result.generation_profile ?? result.parameters?.generation_profile;
    const chunks = getChunks(result);
    const recordId = getRecordId(result);
    card.setAttribute("aria-busy", String(state.generatingRecordId !== null && String(recordId) === state.generatingRecordId));

    const header = element("header", "result-card-header");
    const titleGroup = element("div", "result-title-group");
    titleGroup.append(element("p", "eyebrow", "策略结果"));
    titleGroup.append(element("h3", "result-strategy", STRATEGY_LABELS[strategy] || strategy));
    titleGroup.append(element("p", "result-query", `问题：${queryText}`));
    header.append(titleGroup);
    const badges = element("div", "result-badges");
    const statusBadge = element("span", "badge status", statusLabel(status));
    statusBadge.dataset.status = String(status);
    badges.append(statusBadge);
    badges.append(element("span", "badge", `生成：${statusLabel(generationStatus)}`));
    if (generationProfile === "uniform_evidence") badges.append(element("span", "badge", "统一提示实验"));
    header.append(badges);
    card.append(header);

    const metadata = element("dl", "result-meta");
    appendTextField(metadata, "实际策略", strategy);
    appendTextField(metadata, "检索状态", statusLabel(status));
    appendTextField(metadata, "检索耗时", formatElapsed(result.retrieval_ms));
    appendTextField(metadata, "生成耗时", formatElapsed(result.generation_ms ?? result.answer_call?.elapsed_ms));
    appendTextField(metadata, "首次执行耗时", formatElapsed(result.elapsed_ms));
    appendTextField(metadata, "生成状态", statusLabel(generationStatus));
    if (recordId !== null && recordId !== undefined) appendTextField(metadata, "记录编号", recordId);
    card.append(metadata);

    const error = state.generationErrors.get(String(recordId));
    if (error) card.append(element("p", "inline-error", error));

    renderAnswer(card, result, chunks, cardIndex);
    renderClarification(card, result);
    renderEvidenceStages(card, result, chunks, cardIndex, recordId);
    renderDocumentSources(card, result, cardIndex, recordId);
    renderEvidenceDetails(card, "实体", getEntities(result), (entity, index) => renderJsonItem(entity, index, "实体"), "entity-evidence");
    renderEvidenceDetails(card, "关系", getRelationships(result), (relation, index) => renderJsonItem(relation, index, "关系"), "relationship-evidence");
    appendRecordActions(card, result, cardIndex);
    return card;
  }

  function renderResults() {
    dom.results.replaceChildren();
    const hasResults = state.results.length > 0;
    dom.emptyState.hidden = hasResults;
    if (!hasResults) return;
    state.results.forEach((result, index) => {
      dom.results.append(renderResult(result, index));
    });
    updateBusyControls();
  }

  function savedRecordQuestion(record) {
    return typeof record?.query === "string" && record.query.length > 0 ? record.query : null;
  }

  function savedQueryGroups(records) {
    const groups = [];
    const byQuery = new Map();
    records.forEach((record, index) => {
      const query = savedRecordQuestion(record);
      if (query === null) {
        groups.push({ query: null, label: `问题未记录 · 保存记录 ${index + 1}`, records: [record] });
        return;
      }
      let group = byQuery.get(query);
      if (!group) {
        group = { query, records: [] };
        byQuery.set(query, group);
        groups.push(group);
      }
      group.records.push(record);
    });
    groups.forEach((group, index) => { group.value = `saved-query-${index}`; });
    return groups;
  }

  function populateSavedQueryFilter(records) {
    if (!dom.savedQueryFilter || !dom.savedQueryLabel) return null;
    state.savedQueryGroups = savedQueryGroups(records);
    dom.savedQueryFilter.replaceChildren();
    for (const group of state.savedQueryGroups) {
      const option = element("option", "", group.query === null ? group.label : group.query);
      option.value = group.value;
      dom.savedQueryFilter.append(option);
    }
    if (!state.savedQueryGroups.length) {
      dom.savedQueryLabel.hidden = true;
      state.selectedSavedQuery = null;
      return null;
    }

    const lastRecord = records[records.length - 1];
    const lastQuestion = savedRecordQuestion(lastRecord);
    const defaultGroup = lastQuestion !== null
      ? state.savedQueryGroups.find((group) => group.query === lastQuestion)
      : state.savedQueryGroups.find((group) => group.query === null && group.records[0] === lastRecord);
    const selected = defaultGroup || state.savedQueryGroups[state.savedQueryGroups.length - 1];
    dom.savedQueryFilter.value = selected.value;
    dom.savedQueryLabel.hidden = false;
    state.selectedSavedQuery = selected.value;
    return selected;
  }

  function applySavedQueryFilter(value, announce = true) {
    const group = state.savedQueryGroups.find((candidate) => candidate.value === value);
    if (!group) return;
    state.selectedSavedQuery = group.value;
    state.showingSavedRecords = true;
    state.results = group.records.slice();
    if (dom.resultsTitle) dom.resultsTitle.textContent = "已保存结果";
    const question = group.query === null ? "未记录" : group.query;
    dom.resultsSummary.textContent = `问题：${question} · ${group.records.length} 条策略记录（共 ${state.savedRecords.length} 条保存记录）`;
    renderResults();
    if (announce) setStatus(`已切换到该问题的 ${group.records.length} 条保存策略。`, "neutral");
  }

  function replaceSavedRecord(recordId, record) {
    const replaceIn = (records) => {
      const index = records.findIndex((item) => String(getRecordId(item)) === String(recordId));
      if (index >= 0) records[index] = record;
    };
    replaceIn(state.savedRecords);
    state.savedQueryGroups.forEach((group) => replaceIn(group.records));
  }

  async function loadSavedRecords() {
    if (state.queryBusy || state.savedRecordsBusy || state.generatingRecordId !== null) return;
    state.savedRecordsBusy = true;
    setStatus("正在读取服务已保存的结果…", "busy");
    updateBusyControls();
    try {
      const payload = await requestSavedRecords();
      const recordsValue = Array.isArray(payload) ? payload : payload.records ?? payload.results ?? [];
      const records = Array.isArray(recordsValue)
        ? normalizeResults(recordsValue)
        : isRecord(recordsValue) ? Object.values(recordsValue).filter(isRecord) : [];
      state.savedRecords = records;
      state.showingSavedRecords = true;
      state.generationErrors.clear();
      state.lastSubmission = null;
      if (dom.resultsTitle) dom.resultsTitle.textContent = "已保存结果";
      if (isRecord(payload) && payload.budget !== undefined) {
        state.budget = payload.budget;
        renderBudget(state.budget);
      }
      const selected = populateSavedQueryFilter(records);
      if (selected) {
        applySavedQueryFilter(selected.value, false);
      } else {
        state.results = [];
        state.showingSavedRecords = true;
        state.selectedSavedQuery = null;
        dom.resultsSummary.textContent = "已读取 0 条服务保存记录。";
        dom.emptyState.querySelector("h3").textContent = "没有已保存结果";
        dom.emptyState.querySelector("p").textContent = "本机服务当前没有可显示的检索记录。";
        renderResults();
      }
      setStatus(selected
        ? `已读取 ${records.length} 条保存记录；当前问题有 ${selected.records.length} 条策略结果。`
        : "当前没有已保存结果。", selected ? "success" : "neutral");
    } catch (error) {
      setStatus(error.message, "error");
    } finally {
      state.savedRecordsBusy = false;
      updateBusyControls();
    }
  }

  function installSavedRecordsButton() {
    if (!dom.resultsHeading) return;
    const actions = element("div", "results-tools");
    const filterLabel = element("label", "saved-query-filter-label", "按问题筛选");
    const filter = element("select", "saved-query-filter");
    filter.setAttribute("aria-label", "按问题筛选已保存结果");
    filter.disabled = true;
    filterLabel.hidden = true;
    filterLabel.append(filter);
    filter.addEventListener("change", () => applySavedQueryFilter(filter.value));
    const button = element("button", "saved-records-button", "查看已保存结果");
    button.type = "button";
    button.setAttribute("aria-describedby", "results-summary");
    button.addEventListener("click", loadSavedRecords);
    actions.append(filterLabel, button);
    dom.resultsHeading.append(actions);
    dom.savedQueryLabel = filterLabel;
    dom.savedQueryFilter = filter;
    dom.savedRecordsButton = button;
  }

  function renderBudget(budget) {
    dom.budgetValues.replaceChildren();
    if (!isRecord(budget)) {
      dom.budgetState.textContent = "未返回";
      dom.budgetValues.append(element("p", "empty-copy", "服务尚未返回预算信息。"));
      return;
    }
    state.budget = budget;
    document.querySelector("#budget-title").textContent = budget.mode === "interactive" ? "累计使用记录" : "验收预算";
    dom.budgetState.textContent = budget.mode === "interactive" ? "日常问答" : "已更新";
    const names = {retrieval:"原生检索",answer:"答案生成",extra_answer:"PG/组合生成",keyword:"关键词抽取",embedding:"向量化批次"};
    const table = element("table", "budget-table");
    const head = element("tr");
    for (const title of ["请求", "已调用", "预留", "上限"]) head.append(element("th", "", title));
    const thead = element("thead"); thead.append(head); table.append(thead);
    const tbody = element("tbody");
    for (const [key, cap] of Object.entries(budget.caps || {})) {
      const row = element("tr");
      row.append(element("td", "", names[key] || key));
      row.append(element("td", "", budget.issued?.[key] || 0));
      row.append(element("td", "", budget.reserved?.[key] || 0));
      row.append(element("td", "", cap === null ? "未设累计上限" : cap));
      tbody.append(row);
    }
    table.append(tbody); dom.budgetValues.append(table);
    if (budget.mode === "interactive") dom.budgetValues.append(element("p", "empty-copy", "日常问答不沿用验收次数上限；费用与余额由模型平台账号决定。PG/组合生成已包含在答案生成中，不重复计算。"));

  }

  dom.form.addEventListener("submit", (event) => {
    event.preventDefault();
    if (state.composing || event.isComposing) {
      setStatus("请先结束输入法组合输入，再提交问题。", "warning");
      return;
    }
    runQuery();
  });

  dom.question.addEventListener("compositionstart", () => {
    state.composing = true;
  });
  dom.question.addEventListener("compositionend", () => {
    state.composing = false;
  });
  dom.question.addEventListener("keydown", (event) => {
    const submitShortcut = event.key === "Enter" && (event.metaKey || event.ctrlKey);
    if (!submitShortcut || event.isComposing || state.composing || event.keyCode === 229) return;
    event.preventDefault();
    dom.form.requestSubmit();
  });
  dom.question.addEventListener("input", () => {
    dom.clearQuestion.disabled = state.queryBusy || dom.question.value.length === 0;
    if (dom.question.value.trim()) setQuestionError("");
  });
  dom.clearQuestion.addEventListener("click", () => {
    dom.question.value = "";
    setQuestionError("");
    dom.clearQuestion.disabled = true;
    setStatus("问题已清空。", "neutral");
    dom.question.focus();
  });
  dom.strategyInputs.forEach((input) => input.addEventListener("change", () => {
    state.comparisonConfigured = true;
    updateSelectionCount();
    updateModeDescription();
    announceSelection();
  }));
  dom.workflowInputs.forEach(input => input.addEventListener("change", syncSelection));
  dom.routeInputs.forEach(input => input.addEventListener("change", syncSelection));
  dom.ordinaryMode.addEventListener("change", syncSelection);
  document.getElementById("compare-pg-local").addEventListener("click", () => chooseComparison(["local", "pg+local"]));
  document.getElementById("compare-three").addEventListener("click", () => chooseComparison(["local", "pg", "pg+local"]));
  dom.generate.addEventListener("change", updateModeDescription);

  installSavedRecordsButton();
  syncSelection();
  updateBusyControls();
  loadConfig().catch((error) => setStatus(error.message, "error"));
})();
