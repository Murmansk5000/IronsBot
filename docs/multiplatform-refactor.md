# IronsBot 多平台架构重构工作分解

本文把长期架构目标拆成可独立验证的阶段工作项。它的职责是记录迁移顺序、依赖、
完成证据和回滚边界；长期所有权、目标契约和 transition 准入规则以
[ARCHITECTURE.md](../ARCHITECTURE.md) 为准，工作方式以
[engineering-workflow.md](engineering-workflow.md) 为准。

本轮生产基线保持 NoneBot2、OneBot v11、NapCat、Docker/Unraid 和 Python 3.10+
不变。QQ Official 仅是未来兼容目标：在真实功能需要前，不安装
`nonebot-adapter-qq`，不创建空适配器目录，也不写入官方凭据。

## 总体约束

- 涉及仓库：`IronsBot`、`seerapi`、`ironsbot-private`。每个仓库单独提交、单独
  验证；未经明确要求不得 push、改生产 TOML、环境变量或挂载数据。
- 每一阶段必须先在临时目录、临时 SQLite 或测试 fixture 中验证。持久化迁移只允许
  停机的一次性工具读取旧库，默认 dry-run，`--apply` 才能写入。
- 新跨功能代码只能扩展 target 契约，或减少 transition 的一个调用方。不得为了
  交付速度再引入旧接口消费者、双读/双写、兼容 facade 或平台专用业务逻辑。
- `ironsbot/**/*.py` 的 800 行限制继续由
  `tests/test_structure_size_hygiene.py` 强制；按真实职责拆分，不通过移动到
  `utils`、`shared`、`common` 或万能基类规避。
- 任何阶段都要保留当前 OneBot 用户行为，除非有明确产品决定和特征测试一并更新。

## 状态词与进度

阶段和工作项只能使用下列状态：

- `planned`：目标已定义，尚未开始实现。
- `in_progress`：正在调查或实现；尚未满足完成门槛。
- `blocked`：缺少用户决策、发布数据或外部状态，无法安全推进。
- `completed`：唯一正常路径、删除项和验证证据均已完成。

进度报告按“program -> phase -> task”三层给出。进度分子只能计算已经验证并提交的
工作项；测试运行中、草稿和等待 release 均不得计入。预计时间是当前证据下的区间，
范围或依赖变化时必须同步说明原因。

```text
Program  [████░░░░░░] 40%  verified phases: 2/7  estimated remaining: 4-7 h
Phase 3  [██████░░░░] 60%  verified tasks: 3/5  estimated remaining: 1-2 h
Task     [████████░░] 80%  remaining: boundary tests and smoke test  20-40 min
```

示例中的数字不是当前状态；实际状态由本次任务报告和提交证据决定。

## 阶段工作项

### Phase 0 — 基线、设计和防扩张检查

**目标契约：** `baseline` 与文档/测试保护。

**唯一目标路径：** 架构文档清楚区分 `target`、`transition` 和 `baseline`；静态
检查阻止核心层、服务层和 renderer 重新依赖传输、数据库或生命周期副作用。

**完成条件：**

- 三个仓库的当前 HEAD、工作区、远端、目录边界和现有行为已审计；
- 运行全量测试、Ruff、BasedPyright、compileall、静态架构检查及启动/关闭 smoke
  test，并记录真实失败而不是掩盖；
- `ARCHITECTURE.md`、工作约定和 800 行检查准确描述目标；
- 特征测试保护：core/services 无 adapter import，renderer 无持久化/网络访问，插件
  import 不启动 SQLite、任务或 scheduler。

**回滚：** 仅文档和测试提交可直接回退，不改变生产数据。

### Phase 1 — 平台身份、出站消息和状态迁移

**目标契约：** `ActorRef`、`ConversationRef`、`IncomingMessageRef`、
`OutboundMessage`、`OutboundMessenger` 与一次性状态迁移。

**唯一目标路径：** 服务和仓储只接收平台无关身份；共享 QQ 状态以独立
`platform/kind/id/scope` 列保存。OneBot 的数值 QQ 只在配置/事件/投递适配边界转换。

**完成条件：**

- feature、冷却、订阅、限流、管理通知和持久化公开 API 均使用类型化身份；
- `ironsbot.state_migration` 支持 dry-run、备份、临时构建、事务复制、校验、原子替换
  和幂等重跑；
- 空库、正常旧库、重复记录、损坏记录和中断都有测试；
- `ironsbot-private` 仅使用公开的身份/状态 contract；不读取应用 composition。

**删除条件：** 运行时没有旧整数身份列读取、懒迁移、双读或双写。

### Phase 2 — 标准 NoneBot 插件装载

**目标契约：** 标准 `[tool.nonebot.plugins]` 清单、`PluginMetadata`、
`PluginContribution`、`PluginInstallContext`、`MatcherFactory` 和
`CommandCatalog`。

**唯一目标路径：** 内置和私有插件均由 `nonebot.load_from_toml()` 从声明式清单加载。
私有插件只从窄 extension context 获取已声明的领域能力。

**完成条件：**

- 清单外插件不会装载，装载后不重复注册 matcher/lifecycle；
- 每个顶层插件提供自己的元数据和贡献；
- 没有反射发现、应用插件注册表、旧 bootstrap 模块或私有 JSON 清单；
- 直接命令仍由唯一 `CommandCatalog` 验证，Matcher 仅负责构造和绑定。

**删除条件：** 不存在 `PluginDefinition`、`MatcherRegistry` 或任意第二份插件发现
来源。

### Phase 3 — OneBot 适配和投递边界

**目标契约：** OneBot 仅作为 `plugins/onebot` 与 `integrations/onebot` 的传输适配器；
服务通过 `OutboundMessenger` 或更窄的领域通知 port 投递。

**唯一目标路径：** 事件在 OneBot context adapter 处一次转换为核心身份和消息引用。
主动发送与事件回复分别走 `send()`/`reply()`，均保持正确路由、队列、限流、退订、
失败分类和 trace。

**完成条件：**

- `plugins/onebot` 外没有 OneBot `Event`、`Bot`、`MessageSegment` 或 NapCat 类型；
- 所有仍依赖 `OneBotMessageTarget`/`OneBotDelivery` 的旧调用只位于 OneBot integration，且
  每次迁移都减少一个服务消费者；
- 路由只可选显式 Bot 或配置默认 Bot，二者均不可用时返回可观测失败；
- 文本、图片、远程图片、@、被动回复、主动群/私聊及失败结果均有适配器测试。

**删除条件：** `OneBotMessageTarget` 与 `OneBotDelivery` 不再被服务或 core 公开；其余旧
调用完成 one-direction 迁移后才可删除类型。

### Phase 4 — 渲染、发布事实和素材管线

**目标契约：** `repository -> immutable snapshot -> presenter -> RenderDocument -> renderer`
以及统一 `AssetStore` / `RenderCoordinator`。

**唯一目标路径：** `seerapi` 在构建期发布确定性事实、关系和 PNG 资产；IronsBot
repository 准备快照，renderer 不读 SQL/HTTP/文件系统、不猜关联、不做 SWF 转换。

**完成条件：**

- 资产 cache、最终图片 cache、singleflight、并发、完整性和超时策略集中实现；
- renderer 在首次 `await` 前已不持有 DB session；
- 宠物、属性、竞技池、排行、投票和阵容逐项迁移并有快照/像素/缓存测试；
- release schema、所需表和完整资源在构建端与消费端均验证。

**删除条件：** 运行时 SWF 转换、renderer 数据库读取和文本关联猜测全部删除。

**当前收口记录（2026-08）**

- 精灵资料、属性克制、巅峰池、投票和精灵排行已经采用“快照/素材 ->
  presenter -> `RenderDocument` -> HTML port”的单向链路；纯 presenter 不得
  新增 SQLite、HTTP、文件读取或当前时间依赖。
- 专属效果、魂印顺序和魂印 PNG 已由 SeerAPI 构建期事实提供。无法由原始包表达、
  但需要展示的魂印必须写入 SeerAPI 的
  `pet_soulmark_display_addition`，并附带 `source`，不得在 IronsBot presenter
  中按精灵 ID 特判。
- `new_content` 使用 `NewContentSnapshotBuilder` 在第一次素材 I/O 前完成详情、
  皮肤资源、称号和群星牌引用的同步读取，冻结为 `NewContentPreparedItem`。素材
  适配器只消费其中的 `NewContentAssetRequest`，再交给纯 presenter 生成不可变
  文档；不得把新的数据库读取或展示推断放回 HTML 模板或纯 presenter。
- 最终图片缓存统一在素材准备和 `RenderDocument` 生成之后，使用
  `render_document_cache_key()` 对文档的全部确定性值做哈希。data URI 资产包含在
  文档中，因此图片资源更新会自然失效旧最终图；不得恢复“只用精灵 ID/榜单参数
  先查最终缓存”的快捷路径。
- 私有阵容渲染也复用该内容键；私有模板和本地 Pillow 装饰源码以
  `renderer_fingerprint` 作为显式上下文参与键计算，不能维护第二套按阵容参数命中
  的最终缓存。

### Phase 5 — 业务服务和通用解析

**目标契约：** 领域服务、统一别名解析和 `PlayerIdResolver`。

**唯一目标路径：** AI、玩家、榜单、订阅和战队等业务各自只拥有领域规则；所有
米米号语义入口使用同一 resolver，实体别名只共享结果 contract，不共享领域存储。

**完成条件：**

- AI 使用 CommandCatalog 认领输入，不维护私有保留词；
- 玩家多分区查询独立失败、渐进返回；榜单显式返回来源和缓存时间；
- 每个玩家 ID 参数都接受数字、允许的别名和一个直接 @ 已绑定用户；
- 删除插件专用数字正则、重复规范化函数和手工命令保护词表。

**删除条件：** 无需向 AI、帮助、榜单或插件同步维护第二份命令/别名规则。

### Phase 6 — 兜底、配置和错误语义

**目标契约：** 明确的失败、重试、陈旧缓存与配置验证语义。

**唯一目标路径：** 没有数据、超时、缓存过期和平台不支持均返回可观察的真实结果，
不会伪造默认值、静默选任意 Bot 或无限期复用旧数据。

**完成条件：**

- 删除属性默认 1.0、数据库异常空结果、玩家默认分区、B站伪名称、无限期旧缓存和
  任意在线 Bot 路由；
- 只保留有限重试、单记录隔离、明确 stale 标志与管理员诊断；
- TOML 仅存行为配置，凭据仅来自环境变量，schema `extra=forbid`，无旧字段别名。

**删除条件：** 正常运行路径不存在隐式兼容或会伪装成功的 fallback。

### Phase 7 — 未来平台验收

**目标契约：** 测试中的 `FakeOfficialPlatform`，不是实际 QQ Official 集成。

**唯一目标路径：** 同一业务服务可在 OneBot 与 fake official capabilities 下处理
文本、图片、权限、绑定和订阅；不触碰真实官方账号或凭据。

**完成条件：**

- 模拟字符串 OpenID、群 scope、回复截止时间、图片上传、禁止主动消息、trace ID 和
  官方错误码；
- help/about、Seer 文本/图片、feature policy、玩家绑定、AI 与订阅在两个平台的
  capability 差异下均有测试；
- 全仓 Ruff、pytest、BasedPyright、compileall、架构检查、安全/依赖审计与真实
  OneBot smoke test 通过。

**删除条件：** 无。本阶段只证明目标可接入真实官方适配器，不提前启用它。

## 工作项登记模板

每次开始一个小任务，先在任务说明或 PR 描述中填以下内容；完成时补充真实证据：

```text
工作项：<领域职责>
状态：planned | in_progress | blocked | completed
契约：target | transition | baseline

目标：<用户或系统行为>
所有权：<服务 / port / repository / renderer / platform adapter>
复用：<现有 contract；若新建，说明为什么是最小通用边界>
范围：<仓库、公开行为、schema、配置>
不在范围：<明确不做什么>
迁移：<一次性工具、备份、校验、删除条件；无则写无>
验证：<测试、静态检查、compile、smoke test>
回滚：<提交或备份恢复点>

进度：<program / phase / task>
预计：<区间、置信度及仍待验证项>
```

这份记录不能以“同一个 AI 曾经生成过”代替事实核验。合并文档时先按
target/transition/baseline 收口职责；Git 冲突只表明文本同时被改过，不代表两份设计
都应保留。
