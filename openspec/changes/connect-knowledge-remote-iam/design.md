# I3设计与阶段

## Context
起点1aa52b04976a94ad6e969775ced07cf1828ca81e（dev，比origin/dev领先1提交，不能reset到远端）。当前正式网关入口为env_rag_final.access（8099），早期src/env_rag_final/web不是本次入口。KnowledgeService、AuthContext、Registry承担当前本地鉴权；记录/缓存已绑定user/enterprise/policy_revision/workspaces。registry同时保存技术namespace和本地主体/角色，不能整份废弃。
当前部署有air/water两个独立LightRAG workspace，底层存储和原PDF/解析产物受保护。add-pg-scoped-retrieval及Gate4未完成，不被本包覆盖。

## Goals / Non-Goals
本轮完成可单独启动的remote适配、真实IAM人类/机器授权、完整资料出口边界、local回归、只读实际检索与浏览器。正式8099保持原配置，不迁账号/历史记录、不重入库、不改检索/精排/融合算法、不初始化查询存储、不改IAM/Agent源码。跨项目组合联调与生产启用另放行。

## Decisions
### 两个明确部署模式
ENV_RAG_AUTH_MODE=local|remote在启动时固定；缺省local维持当前行为，非法模式失败。remote缺IAM URL/issuer/内部client/SSO及安全会话存储/映射等必要配置即失败，不因测试环境/请求头/网络故障自动回local。
local provider封装当前Registry主体/角色逻辑，local运行对IAM请求数0；remote provider只以IAM响应裁决，不能并联本地principal/grants产生OR许可。technical目录独立加载，在remote模式不依赖“必须存在本地角色grant”才能解析workspace。

### 统一上下文与async边界
normalize返回不可变且可序列化的非秘密上下文，区分human/service_account、主体ID、tenant UUID、精确权限、选中workspace、映射/技术目录版本。原始IAM token只在受控服务端会话或本次Bearer传输中，不能被dataclass.as_dict或repr带入记录/日志。
human保留真实session/四修订/ctx；machine这些字段为null，使用真实service_account/credential字段和权限摘要。每个受保护新入口和网关实际新后端发送前都在线核验；同步记录/缓存方法若改为async，必须逐调用者await，不能出现未执行的coroutine守卫。不能在aiohttp事件循环使用asyncio.run或阻塞HTTP。
500ms IAM总deadline、连接复用和错误语义按contract.md；检索/模型自身的长timeout不等于允许身份核验也等待180秒。

### 显式映射与选择
映射键为(当前IAM tenant UUID,knowledge:lib:<library_code>)，值为已有技术workspace ID。映射自服务端配置、可校验/版本化；未知tenant/resource/ws、重复冲突、保留default或错误namespace在启动或使用前拒绝。不能把任意前端library字符串拼进URL或PG schema。
可用集合=实时IAM精确读码∩显式映射∩技术就绪集合；IAM已做资源目录/entitlement求交，消费方仍必须检查精确许可，不能把active=true或某角色名当许可。all只展开这个集合；显式集合含任何无权/未知库整体拒绝，不静默裁剪，也不返回库名/数量供枚举。
技术目录/语料状态变更使相关缓存/记录失效，与IAM修订分别处理；不发明IAM第五修订。多个企业映射同一公共材料库必须显式配置，私有记录和缓存始终包含企业/主体，不据此合并身份。

### 每个数据出口和竞态
在query/generate、PG/LightRAG/网关自身模型/embedding/rerank发送、重试、cache hit、records/list/detail、export、source/document/PDF/解析片段读取前执行当前许可检查。保留原workspace_snapshots、chunk/doc/source归属及内容指纹，不用remote身份替代语料守卫。
屏障测试放在“前一调用完成、下一调用尚未获准”处；撤销成功后的新受保护调用后端增量0。已在飞并被授权的第三方请求无法追溯撤回，不把LightRAG内部已受理任务的取消宣称为已实现；其回执仍不得通过失效上下文进入新用户/记录。生成输出回送、缓存入库/记录落盘前复核原上下文，切企业/撤销后不写到新的企业。
记录与缓存按(auth mode,principal type,principal ID,tenant,必要会话/凭据和修订,权限摘要,workspace集合,映射/目录及语料版本)隔离。remote不会按同名local用户自动继承历史记录；需要显式映射的旧记录保持不可用并报告。

### 人类会话和机器主体
remote /api/login或SSO兼容门面在服务端取得知识库受众会话，页面只拿应用handle和非秘密身份。SSO按contract.md的实际ticket/state接口，state与发起会话/精确回调绑定，消费后清理URL；API返回的token不得进JS/localStorage/报告。
人类需有效当前企业/成员；多企业首次必须选择，不自动第一家。切企业由IAM CAS处理，本地UI按session/user/tenant/ctx/epoch拒绝迟到结果；机器固定企业且没有切企业功能。
Bearer用于无人值守，内部client凭据与服务账号令牌分开；服务账号仅含knowledge受众与单库读码。网关到LightRAG只注入原instance key，禁止透传IAM token、身份cookie或内部client密钥。

## 分阶段推进
| 阶段 | 最小闭环 | 放行条件 |
|---|---|---|
| G0 | 固定源码/现有失败、IAM真实协议、独立资源及显式映射 | 配置有据，local/remote与资料只读范围明确 |
| G1 | 单库Bearer→真实IAM机器核验→受控后端返回，local对照 | air正例；water/错企业/错受众/无权限/断网后端0 |
| G2 | 扩展实际PG/LightRAG与所有记录/来源/文件/缓存/生成出口 | 边界/撤销/ABA/重试和原检索状态不回退 |
| G3 | remote人类登录/SSO→多企业选择→查询，local页面保留 | 浏览器切企业/退出迟到响应与CSRF/Origin反例 |
| G4 | 全离线回归、最小真实只读联调、性能/资源/秘密交接 | K矩阵逐项可定位，受阻项明确，无未授权原库写入 |

使用标准OpenSpec apply；进度只维护tasks.md及其末尾短“实施备注”，不另建goal/checkpoint文件；原始证据按run追加，避免过程文档膨胀。每阶段修通小闭环再推进，不逐任务要求用户确认，也不先大改所有模块。

## Migration Plan
在独立记录根目录和候选502xx网关运行remote，原8099与现有credentials/registry不覆盖。配置显式tenant/library/workspace映射，不从local角色或用户名推测IAM UUID。回退为停止新remote实例，保留其新记录与审计；若另启local，是独立配置/记录域，不让remote断网自动读取local历史账号。现场账号/历史记录迁移另行评审。

## Risks / Trade-offs
权限撤销会使旧记录重新读取被拒绝；这是授权边界，不以保留历史UI访问绕过。元数据/连接池可复用，但正向授权不可TTL缓存。真实模型/embedding调用计费，验收使用最小已授权样本并记录账本；压力只测鉴权和受控传输，不能重建语料或对真实模型压测。
