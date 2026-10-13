# workspace 权限交付 · 验收报告

- run id: `wa-20261012-r1`
- 生成时间: 2026-10-13 09:08:59

## 1. 运行身份

- `lightrag-air`: 镜像 `ghcr.io/hkuds/lightrag:latest`，WORKSPACE=`air`，PG=`air`／Qdrant=`air`／Neo4j=`air`（库 `neo4j`），embedding=`Qwen/Qwen3-Embedding-4B`(2560d)，端口 [9622]
- `lightrag-water`: 镜像 `ghcr.io/hkuds/lightrag:latest`，WORKSPACE=`water`，PG=`water`／Qdrant=`water`／Neo4j=`water`（库 `neo4j`），embedding=`Qwen/Qwen3-Embedding-4B`(2560d)，端口 [9623]

## 2. 服务回执（真实请求）

- llm: HTTP 200 · model=deepseek-v4.1-flash · returned=deepseek-v4.1-flash
- embedding: HTTP 200 · model=Qwen/Qwen3-Embedding-4B · dim=2560
- rerank: HTTP 200 · model=Qwen/Qwen3-Reranker-4B

## 3. 入库终态

- `air`: 共 67 项 · done=63、duplicate=4
- `water`: 共 164 项 · done=159、duplicate=5

## 4. 旧数据保护

- 对照 `default`（原文／状态／向量／图谱／active 派生身份／配置与 gold 哈希）: **一致**

## 5. 其他证据

- chunk-identity-proof.json: 见 `chunk-identity-proof.json`
- lightrag-init-probe.json: 见 `lightrag-init-probe.json`
- acceptance-matrix.json: 见 `acceptance-matrix.json`
- third-workspace.json: 见 `third-workspace.json`
- pg-tasks.json: 见 `pg-tasks.json`
- retrieval-sweep.json: 见 `retrieval-sweep.json`
- lifecycle.json: 见 `lifecycle.json`
- browser/operations.json: 见 `browser/operations.json`
- browser screenshots: desktop-air-generation.png、desktop-air-query.png、desktop-air-records.png、desktop-dual-query.png、desktop-no-access.png、desktop-water-lightrag.png、narrow-air.png、narrow-no-access.png
- 已披露的操作事故: 清理派生表时误删了 default 的 5 条 corpus_runs 与 7 条 search_builds 历史行；已依据 reports/pg-retrieval/phase-1/build-manifest.json 与 reports/pg-retrieval/phase-2/index-manifest.json 逐字段原值恢复，protected-before-after.json 复验为 0 差异。
