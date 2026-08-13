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

## 当前验证进度（2026-08-13）

```text
总任务  [████████░░] 78%  已完成阶段 3/8；其余阶段均有已验证子项，预计仍取决于数据发布与跨仓库迁移
Phase 2 [██████████] 100%  私有阵容已只依赖文档化的 `core` / `extensions` / install 契约；渲染、查询和持久化均通过公开端口收口
当前任务[██████████] 100%  `d9215799` / `2b0442b0` 与本次公开查询/缓存端口、私有库 `65f09ec` / `64dba01` 已验证公开安装、动作注册、发布数据阵容快照、渲染、查询和缓存端口；公共 13 项、私有 20 项本轮针对性测试通过
```

本次完成的跨仓库证据：

- `seerapi` 提交 `7976961` 在构建期生成 `partner_upgrade` 的魂印显示分类；全量
  `pytest` 为 219 passed，Ruff 和编译通过。该仓库当前环境未安装 BasedPyright，不能把
  缺少的工具误报为类型检查通过。
- `IronsBot` 提交 `ae793f54`、`0644060d` 将运行时伙伴描述匹配替换为已发布的
  `display_kind`，并把精灵渲染值对象迁到 Seer 领域；全量 pytest 按三组共 1371 passed，
  Ruff、BasedPyright、静态架构检查、编译和 `git diff --check` 均通过。
- `seerapi` 提交 `e80f4a3` 将构建期已经生成的魂印 PNG 写入
  `render_asset_manifest`，每项带真实 SHA-256、素材种类、素材键和 release revision；
  同时将 manifest revision/count 写入发布 metadata。全量 pytest 为 220 passed，Ruff、
  编译和 `git diff --check` 通过。它只覆盖构建自产的 `soulmark_icon_png`，不代表远程
  精灵、皮肤或其他图片资产已具备 manifest，因此不能作为早期 L3 命中的完成证据。

下一步只审计尚未采用 snapshot -> document 管线的渲染路径；未满足同等发布事实和缓存
验证前，不得把 Phase 4 标为完成。

## 阶段账本与报告纪律

阶段表不是“计划完成率”表。每一行必须同时标明已验证证据、下一道完成门和阻塞原因；
没有已提交的验证证据时，不得把工作项计入百分比或进度条。跨仓库任务必须分别记录
每个仓库的提交和验证，不能把一个仓库通过的测试写成整个阶段完成。

### 跨仓库证据账本

每个跨仓库工作项在开始实现前必须先在本文件或对应任务记录写一条证据账本。账本至少
包含：目标契约、影响仓库、唯一正常路径、删除/禁止的旧路径、验收测试、发布依赖和回滚
点。实现完成后补写每个仓库的 commit、实际执行的验证命令、结果和未完成边界。

禁止用“接口已经定义”“文档已经写好”或“一个仓库测试通过”替代端到端证据。若上游
发布物尚未生成、下游尚未消费、生产尚未具备安全迁移条件，状态必须是 `in_progress`。
一个子任务可以 `completed`，但它的父阶段仍必须保留未完成门槛。

跨仓库接口改动按以下顺序推进：先发布上游 schema/facts 与 fixture，再让消费者实现
严格读取和拒绝不兼容 schema，最后迁移实际扩展或生产数据。不得为了让中间状态可运行
恢复旧字段、旧导入、双读或静默降级。确实无法避免的临时桥接必须登记删除条件、最迟
删除阶段和阻止新增调用方的测试。

| 阶段 | 当前状态 | 已验证范围 | 下一个完成门 | 不得误报为 |
| --- | --- | --- | --- | --- |
| Phase 0 | `completed` | 目标/过渡术语、架构守卫、800 行限制和工作约定已建立 | 后续变更持续遵守并更新证据 | 所有架构迁移完成 |
| Phase 1 | `in_progress` | 类型化平台身份、出站 port 和一次性状态迁移已落地 | 删除剩余旧整数身份与旧路径读取 | 已完成多平台投递 |
| Phase 2 | `completed` | 内置插件已采用标准 NoneBot TOML 清单、`PluginMetadata`、`PluginContribution`、安装上下文和唯一 `CommandCatalog`；`d9215799` 将安装 API 从 `runtime` 收进 `core.plugin_install`，并以公开 `PlayerLineupExtensionContext` 注册私有动作、解析发布数据阵容快照；`2b0442b0` 与私有库 `64dba01` 已将阵容资源、最终图片缓存和 HTML 渲染迁到 `PlayerLineupRenderPort`；本次 `PlayerLineupQueryPort` 已收口无头请求、配额、错误语义与公共玩家格式化，`PlayerLineupCacheFactory` 已收口缓存迁移、读写和 SQLite 实现。私有运行包对公共 `services` / `integrations` 的导入审计为零。公共 13 项、私有 20 项本轮针对性测试通过 | 后续新扩展复用同一 install/context/command 契约；不得重建第二套插件发现或装配入口 | 所有外部扩展均已随当前公开契约验证 |
| Phase 3 | `completed` | OneBot 出站统一由 `OneBotOutboundMessenger` 实现核心 `OutboundMessenger` 端口；旧 `OneBotDelivery`、数值 target 模型和测试夹具均已删除。管理通知、活动提醒、定时消息、幸运橱窗、战队资源和 B 站动态均统一走 `ProactiveMessageDelivery` | 后续只允许在 `integrations/onebot` 增加真实平台转换；新业务不得重新引入数值 target 或批量投递对象 | QQ Official 已接入 |
| Phase 4 | `in_progress` | 资源准备、确定性文档内容键、部分 SeerAPI 效果事实，以及全部现有最终图渲染入口的请求级 L3 早期命中已验证 | SeerAPI 发布完整 render asset manifest，并对每一类素材做范围完整性验证 | 渲染数据发布契约完成 |
| Phase 5 | `in_progress` | 通用别名、玩家 ID 解析、命令认领与 AI 记忆异步化已验证 | 真实私有扩展迁到公开 core 命令契约；所有直接命令与米米号入口以覆盖测试证明使用同一契约 | 业务服务重构完成 |
| Phase 6 | `in_progress` | 新内容分类状态已不再猜测旧索引 | 逐项审计并删除剩余隐式 fallback、配置兼容和伪成功结果，且以错误语义测试证明 | 错误语义收口完成 |
| Phase 7 | `planned` | 无 | 建立 `FakeOfficialPlatform` capability 验收 | 真实 QQ Official 已接入 |

**Main 吸收记录（2026-08-13）：** 已以 V5 的类型化 B 站服务为唯一业务路径吸收
`main` 的发布时段加密轮询需求。`BiliBoostWindow`、秒级时钟、槽位去重和 cron
注册均不依赖 OneBot 数值 target；发现新动态后仅结束当前 burst，空响应或失败仍会继续
后续偏移探测。未直接 cherry-pick `main` 的旧 monitor 实现，避免恢复数值身份、旧投递
和旧 service API。

**Main 菜单路由审计（2026-08-13）：** 审计 `49adfecd`、`0484e65a` 和
`0e4b5c69` 后确认 V5 已有持久队列路由和文本化 @ 菜单选择兼容；本次仅吸收尚未覆盖的
NapCat reply segment 事实。`event.reply` 缺失时，OneBot 输入适配器会从当前消息、再从
原始消息读取 reply segment，命令输入分类与群菜单锚点共用同一解析结果。没有 cherry-pick
旧 `main` 的 runtime 目录实现，也没有重新引入临时 fallback matcher。

**渲染版本快照（2026-08-13）：** `SeerDatabase` 在 SeerAPI 内存库原子换版完成时
刷新发布版本；最终图片缓存读取该内存快照，不再为每个 `get`/`put` 额外开 SQLite
session。未加载数据仍显式返回 `unknown`，因此不会写入无发布版本的缓存。该项是下一步
`RenderRequestKey` 在 SQL/HTTP 之前安全命中的版本基础，不代表早期缓存本身已经完成。

**请求级渲染缓存（2026-08-13）：** `a167843a` 将已发布精灵信息、属性克制、巅峰池、
巅峰票选、巅峰精灵榜和新内容菜单改为先构造确定性请求键，再查最终图片缓存。命中路径
不读取 SQLite、不加载素材、不调用 presenter 或原生 HTML 渲染；针对性测试覆盖了零素材
请求命中。发布版本现在同时要求 `ApiMetadata.generate_time` 和
`render_asset_manifest_revision`，缺少 manifest 的旧 release 返回 `unknown` 并禁用最终图
缓存，避免将不完整素材固定为图片。`9879c441` / 私有 `dbd30c0` 随后将私有阵容通过
公开 `PlayerLineupRenderPort` 迁到同一早期命中顺序；现有最终图入口已无“先加载素材再查
缓存”的路径。Phase 4 未完成门只剩 SeerAPI 完整 manifest 的范围验证，而非运行时顺序。

**资源清单获取可靠性（2026-08-13）：** SeerAPI `8805abb` 在 GitHub REST API 的 commit/tree
读取受匿名限流影响时，回退到 blob-filtered Git clone 和 `git ls-tree -r`。该路径只读取提交与
目录对象，不下载 PNG blob；实测 REST 403 后仍从 `c562516e2e350c93810cf090599db2a117d5724c`
读取 39,766 个资源 blob 条目。构建期 manifest 因此不再把公共 API 限流误判为素材不完整。
尚未完成的是将每个 renderer 的全部素材家族都列入 scope 证明，不得把当前 pet/new-content
inventory 泛化为所有未来渲染器。

**镜像依赖审计（2026-08-13）：** 已删除 IronsBot 未导入、也不由 `seerapi`
传递依赖的 `unitypy`。锁定闭包同步移除纹理解码、音频、压缩等 11 个运行时包；
HTML 渲染、二维码登录和 SVG 光栅化依赖仍因存在真实调用而保留。Docker 引擎在本机未
运行，故这一轮以 `uv export --no-dev` 闭包和启动/渲染 smoke 测试作为可复现证据；
发布前 CI 或 Docker 环境仍应记录实际 image size。

**身份边界收口（2026-08-13）：** 私有阵容的公开请求与查询 port 已从 `Any`
收紧为 `ActorRef` / `ConversationRef`。私有实现无法再构造无身份的实时无头查询；
公共队列、配额、操作追踪和未来平台适配均获得相同的类型化调用路径。

**持续收口与镜像基线（2026-08-13）：** `b16c3dfc` 无损压缩四张内置固定图片，
运行时资产减少约 2.58 MB，并移除六项仅由核心依赖传递提供的重复声明；Docker 继续
显式复制运行时文件，且以 `--no-compile` / `PYTHONDONTWRITEBYTECODE=1` 避免把
`.pyc` 写入镜像或运行时挂载目录。`4aa06839` 以 V5 的持久菜单会话吸收 main 的
文本化机器人 @ 回复兼容，未恢复临时 matcher 路径。`b5ca2892` 删除 B站正文/图片
投递之外无生产调用的合并渲染兼容函数；`596d13fc` 将图片网络并发测试改为显式栅栏，
稳定验证四个并发槽位。全量 `pytest` 为 1392 passed，Ruff、编译和
`git diff --check` 通过。Docker 引擎本机仍不可用，实际最终镜像大小必须由 CI 或
Docker 环境记录，不得把源码资产差额误报为镜像实测值。

**B站投递目标职责拆分（2026-08-13）：** `943dbe86` 将原本同时承载目标模型、
TOML 规则编译和运行时目标解析的 `services.bilibili.targets` 分成
`target_models`、`target_rules` 与编排模块三层；投递、监控和 OneBot 适配只导入各自
需要的窄类型或规则函数，不保留旧的聚合渲染兼容入口。B站目标/投递相关 44 项测试与
全量 1392 项 pytest、Ruff、编译和 `git diff --check` 均通过。该拆分是领域内职责
收口，不代表已与 `main` 的大规模目录重排合并；主线后续更新必须逐项按目标契约审计。

**Docker 协议边界拆分（2026-08-13）：** Docker 更新集成不再把 Unix socket daemon
API、OCI Registry v2、镜像归档和管理员用例编排混在 `docker.client`。`daemon` 只负责
本机 Docker API，`registry` 只负责镜像引用、认证和远程 manifest/config 查询，`client`
只组合这两种协议实现重启、更新检查和私有扩展归档。测试改为直接从所属协议模块导入，
不保留旧工具导出的兼容入口；Docker 更新相关 28 项和全量 1392 项 pytest、Ruff、编译及
`git diff --check` 均通过。

**玩家详情生命周期拆分（2026-08-13）：** `PlayerService` 不再同时维护默认米米号、
绑定/额度、基础资料请求与后台详情预热。后者已迁到 `PlayerDetailService`，唯一拥有详情
短期缓存、in-flight future、超时清理和后台任务；主服务只通过这个窄服务编排快捷详情。
组合层、架构身份守卫和测试均直接依赖新边界，不保留旧模块导出。主服务从 794 行降至
441 行；玩家详情、绑定和架构定向 53 项与全量 1392 项 pytest、Ruff、编译、
`git diff --check` 均通过。

**战队资源订阅边界拆分（2026-08-13）：** 订阅目标、群/私聊持久化 DTO、一次性群提示
和订阅命令解析均已迁至 `services.team.resource_subscriptions`；SQLite store、OneBot
适配与通知 sender 直接使用该模块。`TeamResourceService` 仅保留资源查询、阈值判断、
扫描、功能策略和调度编排，未提供旧模型再导出。战队资源定向 24 项与全量 1392 项
pytest、Ruff、编译、`git diff --check` 均通过。

开始持续任务时，报告必须同时给出总任务、当前阶段和当前小任务的进度及预计剩余时间；
估算只描述当前可见范围，遇到新增依赖、发布阻塞或验证失败时必须立即重新估算。推荐
格式如下，百分比只使用已验证并提交的工作项计数：

```text
总任务  [████░░░░░░] 40%  已验证工作项 8/20  预计剩余 6-10 h
当前阶段[██████░░░░] 60%  已验证工作项 3/5   预计剩余 1-2 h
当前小任务[████████░░] 80%  剩余：边界测试与 smoke test  20-40 min
```

报告中无法可靠估算时，必须写“尚不能估算，原因：…”，不能用看似精确的数字掩盖未知
依赖。完成报告还要把最终提交、验证命令、未完成项和回滚点写回阶段账本或任务记录。

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
- `ironsbot.state_migration` 保持唯一部署 CLI；参数解析、退出码和输出在
  `ironsbot.state_migration_cli`，而 dry-run、备份、临时构建、事务复制、校验、原子替换
  和幂等重跑在迁移服务中；
- 空库、正常旧库、重复记录、损坏记录和中断都有测试；
- `ironsbot-private` 仅使用公开的身份/状态 contract；不读取应用 composition。

**删除条件：** 运行时没有旧整数身份列读取、懒迁移、双读或双写。

### Phase 2 — 标准 NoneBot 插件装载

**目标契约：** 标准 `[tool.nonebot.plugins]` 清单、`PluginMetadata`、
`PluginContribution`、`PluginInstallContext`、`MatcherFactory` 和
`CommandCatalog`。

**唯一目标路径：** 内置和私有插件均由 `nonebot.load_from_toml()` 从声明式清单加载。
私有插件只从窄 extension context 获取已声明的领域能力。

组合根只协调四个稳定领域的 builder：`common`、`seer`、`messaging` 和
`operations`。每个 builder 返回类型化组件包；`operations` 已用
`OperationsComponents` 迁出数据同步、无头客户端、服务器状态和重启装配。
`common` 已用 `CommonComponents` 收口当前宿主的策略、会话、推送订阅、路由、
限流、推广和管理通知；OneBot 仅在显式组合的 `OneBotOutboundMessenger` 边界实现
核心出站端口。
`messaging` 已用 `MessagingComponents` 收口定时消息、图片、战队审核提醒及其
投递适配，并只接收 common builder 提供的依赖。
`seer` 已用 `SeerComponents` 收口玩家、榜单、渲染、战队资源和幸运橱窗的装配；
当前 OneBot 账号/提及/通知编译仍标记为 Phase 3 的适配边界。
`bilibili` 已用 `BilibiliComponents` 收口账号目标、Cookie、历史、登录和 HTTP
装配；消息 builder 只接收其公开订阅选项。
后续 builder 只能迁移既有装配代码，不能引入第二个 service locator 或由插件反向
构造基础设施。

**完成条件：**

- 清单外插件不会装载，装载后不重复注册 matcher/lifecycle；
- 每个顶层插件提供自己的元数据和贡献；
- 没有反射发现、应用插件注册表、旧 bootstrap 模块或私有 JSON 清单；
- 直接命令仍由唯一 `CommandCatalog` 验证，Matcher 仅负责构造和绑定。

**删除条件：** 不存在 `PluginDefinition`、`MatcherRegistry` 或任意第二份插件发现
来源。

**完成证据（2026-08-06）：**

- `ironsbot/manifests/full.toml` 和 `core.toml` 是唯一内置插件发现来源；私有扩展也
  只通过其标准 NoneBot TOML 清单加载。
- `bootstrap()` 只在受限 `PluginInstallContext` 生命周期内调用
  `nonebot.load_from_toml()`；模块加载完成后上下文立即失效，不能成为运行时
  service locator。
- 每个顶层 OneBot 插件声明 `PluginMetadata` 并提交 `PluginContribution`；命令由
  `CommandCatalog` 统一收集和校验，matcher 只负责平台事件适配与绑定。
- 组合根只协调领域 builder；所有 builder 返回类型化组件包。它们不能反向装配基础
  设施、反射发现插件或引入第二个命令/插件注册表。
- 验证：`uv run pytest -q tests/test_nonebot_manifest.py
  tests/test_plugin_import_hygiene.py tests/test_plugin_install_context.py
  tests/test_plugin_registry.py tests/test_command_catalog.py
  tests/test_architecture_target_hygiene.py`（64 passed）；
  `uv run python scripts/check_repo.py --static`；全量 `uv run pytest -q`
  （1377 passed）。

**后续边界：** Phase 3 可以替换 OneBot 的入站和出站实现，但不能修改此阶段已经
封存的发现、贡献、命令收集和 builder 装配路径；若确有新的平台插件，必须由同一
TOML 清单、元数据和贡献机制接入。

### Phase 3 — OneBot 适配和投递边界

**目标契约：** OneBot 仅作为 `plugins/onebot` 与 `integrations/onebot` 的传输适配器；
服务通过 `OutboundMessenger` 或更窄的领域通知 port 投递。

**唯一目标路径：** 事件在 OneBot context adapter 处一次转换为核心身份和消息引用。
主动发送与事件回复分别走 `send()`/`reply()`，均保持正确路由、队列、限流、退订、
失败分类和 trace。

**完成条件：**

- `integrations/onebot` 外没有 OneBot `Event`、`Bot`、`MessageSegment` 或 NapCat 类型；
- 不保留 `OneBotMessageTarget`、`OneBotDelivery` 或其数值批量投递模型；新旧业务均只
  通过 `ConversationRef`、`ActorRef` 与 `OutboundMessenger` 交接；
- 路由只可选显式 Bot 或配置默认 Bot，二者均不可用时返回可观测失败；
- 文本、图片、远程图片、@、被动回复、主动群/私聊及失败结果均有适配器测试。

**删除结果：** `OneBotMessageTarget` 与 `OneBotDelivery` 已被删除；OneBot 适配器只在
`ConversationRef` 路由之后，将核心消息 part 渲染成 OneBot 消息。

**完成证据（2026-08-06）：**

- `ProactiveMessageDelivery` 已成为主动文本发送的唯一服务级入口，接受
  `ConversationRef`、`OutboundMessage` 和显式投递请求；统一完成 feature/订阅过滤、
  推广文案、每日退订提示、散发节奏与失败汇总。
- 管理通知、活动结束提醒、定时文本、幸运橱窗和战队资源通知均通过
  `OutboundMessenger` 进行最后一跳发送。`CommonComponents` 不提供旧投递对象、旧
  数值 target 或出站实现给插件资源。
- B 站全文/链接推送已改用 `TextPart` 和 `RemoteImagePart`，链接、正文、订阅过滤、
  推广、历史提示、重试和管理员失败通知均通过同一主动投递链完成；保留的 OneBot
  渲染器只处理用户主动查询的即时回复。
- 验证：`tests/test_proactive_delivery.py` 覆盖订阅、去重、推广、退订提示、失败与
  五类 sender；`tests/test_bilibili_outbound_delivery.py` 覆盖动态文本/远程图片、
  两阶段推送、提示、重试与管理员告警；全量 `pytest` 为 1367 passed，Ruff、BasedPyright、
  `compileall` 和静态检查均通过。架构测试禁止在服务层和 composition 中重新引入旧投递类。

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
- 伙伴系统导致的魂印强化分区由 SeerAPI 在
  `pet_soulmark_display.display_kind` 中发布为 `partner_upgrade`。`PetInfoRepository`
  将该字段冻结到快照；`pet_info_presentation` 只消费显示分类，不再根据伙伴描述猜测
  展示位置。
- 精灵资料的值对象已从 renderer 包迁入 `services.seer.pet_info_views`。Seer 数据仓库、
  素材适配器、presenter 与 document renderer 都依赖同一纯值契约，仓库不再反向导入
  renderer 命名空间。
- `new_content` 使用 `NewContentSnapshotBuilder` 在第一次素材 I/O 前完成详情、
  皮肤资源、称号和群星牌引用的同步读取，冻结为 `NewContentPreparedItem`。素材
  适配器只消费其中的 `NewContentAssetRequest`，再交给纯 presenter 生成不可变
  文档；不得把新的数据库读取或展示推断放回 HTML 模板或纯 presenter。
- 当前最终图片缓存仍在素材准备和 `RenderDocument` 生成之后使用
  `render_document_cache_key()`，其 data URI 确实能保证 miss 路径的像素正确性；但这
  不满足“L3 命中零 SQL/HTTP/presenter”的目标。后续必须由发布数据的 revision 和素材
  manifest 生成 `RenderRequestKey`，先用该键查询 L3，再在 miss 路径以文档内容键做
  完整性校验。不得恢复只含精灵 ID/榜单参数、却没有发布数据和素材版本的快捷键。
- SeerAPI 已为构建期嵌入 `soulmark_icon` 的全部 PNG 发布
  `render_asset_manifest`：按 `(asset_kind, asset_key)` 唯一记录真实 PNG SHA-256、
  `release_revision`、可用状态和来源，并发布顺序无关的 manifest revision。它不额外
  下载素材，也不替代原有 SWF -> PNG 构建管线；消费端可以把这一类素材版本放入将来的
  `RenderRequestKey`。
- 这仍只是第一种发布素材。SeerAPI 尚未发布覆盖 `pet_head`、`pet_body`、
  `element_type`、`mintmark`、`item`、`sign_buff`、预览图等远端渲染素材的完整
  manifest。因此早期 L3 命中仍是明确的跨仓库前置工作：IronsBot 只能引用已发布的
  版本，不能在命中判断时对 HTTP 素材做探测。完整表、模型、构建完整性测试和消费端
  schema 校验完成前，不得把 Phase 4 标为完成。
- 私有阵容渲染也复用该内容键；私有模板和本地 Pillow 装饰源码以
  `renderer_fingerprint` 作为显式上下文参与键计算，不能维护第二套按阵容参数命中
  的最终缓存。
- 2026-08-05 验证：SeerAPI 全量 pytest `218 passed`、Ruff 通过；本轮新增的
  特殊效果 ORM 已可单独通过 BasedPyright。SeerAPI 仍有 38 条既有静态类型问题
  （旧模型抽象基类、旧解析器和构建脚本），必须作为独立清债工作处理，不能靠降低
  目标阶段的静态检查要求掩盖。

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

**当前收口记录（2026-08）：**

- `AliasLookup`、`AliasMatch` 与 `AliasResolution` 是实体别名匹配的共享
  contract；精灵、刻印、刻印系列、宝石与玩家账户各自保存数据，但不再复制
  规范化与多结果语义。
- `CommandCatalog`、`CommandContract`、`CommandContext` 与玩家引用输入 matcher
  是 `core` 契约；`runtime` 只保留插件贡献和安装流程。服务、OneBot 适配器和插件
  都只能依赖该核心契约，不能让领域服务反向依赖 runtime。
- `PlayerIdResolver` 统一处理数字、当前会话可见的玩家别名、一个直接 @ 已绑定
  成员及默认绑定。它由 application composition 只构造一次，经
  `ApplicationResources` 注入公开 Seer 的玩家、快捷查询、榜单玩家查询和命令目录；
  OneBot matcher 只能把事件转换为 `MessageInputContext`，不得临时拼接别名 lookup
  或 resolver。私有阵容扩展的目标也是只通过该 resolver 的
  `has_known_reference()` 进行命令目录认领，真正的消息级解析仍由公开的详情扩展
  入口完成；但当前外部包仍引用已迁出的
  `runtime.commands` / `runtime.player_reference_commands`。私有包现已改为导入
  `core.command_catalog` / `core.player_reference_commands`，并在私有仓库通过其真实
  `pyproject.toml` 的 `nonebot.load_from_toml()` 隔离 smoke test；不得恢复旧 runtime
  路径。剩余的 OneBot 可见性和公共 service 依赖仍须投影到 `ironsbot.extensions` 的
  窄 context，完成前不得把该扩展计入完整跨仓库边界的完成证据。
- `CommandContract.routing_matcher` 已用于参数化玩家命令。AI 的私聊回退仅由
  `CommandCatalog` 判定命令归属；目录只认领实际可解析的参数，不能以宽泛关键字
  抢占普通聊天。
- 公开赛尔查询的命令描述已从 OneBot 插件移入
  `services.seer.command_contracts`；插件只把该领域 contract 提交给目录。后续命令
  迁移必须复用同一模式，不得把领域输入说明重新写进 matcher。
- 榜单帮助的用户口令、范围和权限同样位于
  `services.seer.rank_command_contracts`；OneBot 侧只把事件转为上下文并渲染已筛选的
  目录结果。
- 数据更新的命令文字、语法解析和管理员目录描述位于
  `services.operations.data_sync_commands`；OneBot matcher 只从事件取纯文本，并调用
  同一个领域解析器。
- 开服查询和镜像维护共用的操作口令位于
  `services.operations.command_text`，其中开服查询的目录描述位于
  `services.operations.server_status_commands`、镜像维护的目录描述位于
  `services.operations.docker_commands`；插件不再拥有这份跨操作命令定义。
- 活动查询的用户命令描述位于
  `services.activity.command_contracts`；活动插件只保留 NoneBot 事件适配、权限
  matcher、回复和定时任务注册。
- B 站的命令文字和纯文本解析位于 `services.bilibili.commands`，命令契约位于
  `services.bilibili.command_contracts`；OneBot rule 只保留事件权限、消息 state 和
  事件到纯文本解析器的适配。
- 关于、帮助、战队资源和幸运橱窗分别由 `services.about_commands`、
  `services.help_commands`、`services.team.resource_commands` 和
  `services.seer.lucky_skin_commands` 提供命令契约；插件不再直接构造
  `CommandContract`。
- AI 长期记忆使用异步 `AiMemoryStore` port。SQLite 实现在 worker thread 中完成
  读写，`AiService` 显式 await 读取和记录；事件循环不再直接执行记忆数据库操作。
- 新增内容索引要求发布 `new_content_category_state`。缺少分类状态的旧数据版本会
  明确报告不支持，不再用全局 baseline 猜测每一类内容是否可比较。

**命令来源迁移台账：** 每次把命令迁出插件时，必须在同一提交更新这里；未列出的
新命令不得在 matcher 内自建第二份示例、权限或帮助说明。

| 领域 | 当前唯一命令 contract 来源 | OneBot 插件允许保留的内容 | 状态 |
| --- | --- | --- | --- |
| 赛尔查询 | `services.seer.command_contracts` | 事件转换、参数交给 service、回复 | 已迁移 |
| 榜单帮助与管理 | `services.seer.rank_command_contracts` | 事件转换、回复 | 已迁移 |
| 活动查询 | `services.activity.command_contracts` | 事件转换、权限 matcher、回复、定时任务 | 已迁移 |
| 会议查询 | `services.messaging.meeting` | 事件转换、权限 matcher、回复 | 已迁移 |
| 配置型文本与推送管理 | `services.messaging.command_contracts` | 事件转换、配置执行、回复和定时任务 | 已迁移 |
| 配置型图片命令 | `services.messaging.sendpic` | 事件转换、图片发送、回复 | 已迁移 |
| AI 聊天与意图 | `services.ai.command_contracts` | 事件转换、AI 调用、回复和平台 notice 上下文 | 已迁移 |
| 数据更新 | `services.operations.data_sync_commands` | 事件转换、异步执行、回复 | 已迁移 |
| 开服与容器维护 | `services.operations.command_text`、`server_status_commands`、`docker_commands` | 事件转换、平台操作、回复 | 已迁移 |
| B 站动态 | `services.bilibili.commands`、`bilibili.command_contracts` | 事件权限、state、回复和调度 | 已迁移 |
| 战队资源订阅 | `services.team.resource_commands` | 事件转换、订阅执行和回复 | 已迁移 |
| 幸运橱窗 | `services.seer.lucky_skin_commands` | 事件转换、登录确认、回复和调度 | 已迁移 |
| 关于 | `services.about_commands` | 事件转换、版本读取和回复 | 已迁移 |
| 帮助 | `services.help_commands` | 事件转换、菜单会话和回复 | 已迁移 |
| 私有阵容扩展 | `core.command_catalog`、`core.player_reference_commands` | 私有扩展的事件转换、阵容服务调用和回复 | 已迁出历史 `runtime.*` 命令模块并验证真实 manifest；待将剩余 OneBot/service 依赖投影为 extension context |

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
