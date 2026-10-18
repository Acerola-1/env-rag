# I3 Knowledge API接入共享IAM

标准OpenSpec apply实施前，除生成的contextFiles外还必须读取本包[共同契约](contract.md)、[公开验收矩阵](acceptance.md)和[冻结基线](baseline.json)。进度统一维护tasks.md；不使用goal模式、不依赖另一个长运行目标管理器。匿名实施完整说明见[实施入口](../../../docs/handoffs/knowledge-remote-iam-apply.md)。

## Why
现有8099网关以本地registry维护主体和角色授权。需要增加显式remote部署，与独立IAM统一人类和服务账号身份、企业及有效资源许可，同时保持local离线部署与air/water资料边界。

## What Changes
- 为现有KnowledgeService和aiohttp服务器接入local/remote授权提供者；remote只通过固定IAM HTTP核验。
- 以精确knowledge读码与显式tenant/resource/workspace映射授权，不再从local角色推断remote权限。
- 查询、生成、缓存、记录、来源、文档与导出采用一致的实时复核；保留实际存储namespace和技术就绪检查。
- 增加remote人类会话/SSO及企业选择，服务账号供无人值守脚本使用，实例key继续只在网关到实例的一跳。
- 先完成真实IAM加受控后端的最小闭环，再验证实际只读PG/LightRAG和浏览器；历史数据不迁移、不重入库。

## Capabilities
### New Capabilities
- knowledge-remote-iam：Knowledge API的远程身份、资源映射、实时撤销和local兼容部署。

### Modified Capabilities
无。本包新增remote能力并继承已验收workspace-access-control语义，不更改检索算法或既有Gate4状态。

## Impact
主要涉及src/env_rag_final/access/{auth,gateway,registry,server,__main__}.py、受控HTTP授权模块、最小静态页面接线及tests；技术注册表与远程身份拆开。IAM/Agent仓库只读。产品起点1aa52b0；交付隔离remote实例及可审查diff，不切换现有8099、air/water实例或共享资料库，不commit/push/archive。
