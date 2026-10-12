/* Shared selection contract: hidden comparison choices never leak into a single query. */
(() => {
  "use strict";
  const modes = ["naive", "local", "global", "hybrid", "mix"];
  const strategies = [...modes, "pg", ...modes.map(mode => `pg+${mode}`), "bypass"];
  function resolve(workflow, route, mode, comparison) {
    if (workflow === "compare") {
      if (!Array.isArray(comparison) || comparison.some(item => !strategies.includes(item))) {
        throw new Error("对照路线无效，请重新选择。");
      }
      return [...new Set(comparison)];
    }
    if (workflow !== "ask") throw new Error("使用方式无效，请重新选择。");
    if (route === "pg" || route === "bypass") return [route];
    if (!modes.includes(mode)) throw new Error("LightRAG 模式无效，请重新选择。");
    if (route === "lightrag") return [mode];
    if (route === "combined") return [`pg+${mode}`];
    throw new Error("检索路线无效，请重新选择。");
  }
  globalThis.RAGSelection = Object.freeze({ resolve });
})();
