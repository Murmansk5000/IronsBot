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
- `seerapi` 与 `ironsbot-private` 的生产包和构建脚本同样以 800 行作为长期上限。当前
  `seerapi/scripts/build_seerapi_data_db.py`（727 行）已经满足该限制；
  `scripts/build_new_content_index.py` 已拆至 280 行。新功能
  不得继续写入这些聚合脚本，后续拆分必须按下载协议、二进制解析、资源转换、manifest
  发布和 SQLite 写入等真实职责迁出，并以每次提交的行数下降和构建验证作为证据。
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
Program  [████□□□□]  verified phases: 4/8; percentage awaits a weighted acceptance baseline
Phase    [█████░░░░░]  verified work is counted only after its stated acceptance criteria pass
Task     [██████████] completed only after code, tests, and evidence are committed
```

进度条只表达已验证的阶段或当前任务完成状态。除非 Spec 已定义可审计的加权验收项，禁止报出整体百分比或总体 ETA。

## 本轮验证（2026-09-12）

总任务 `[████□□□□]`：阶段 1 身份/状态迁移收口验收完成，账本从 3/8 更新为 4/8。
下方早期记录保留当时的测试与状态；跨仓库发布、真实平台和素材完整性门槛仍未完成，
暂无可靠总体 ETA。

- 本轮用户明确要求 pull 后，干净的主检出目录执行 `git pull --ff-only origin main`，
  从 `ba08f749` 快进到 `55a39fd1`，未合并入 V5。新增 10 项提交涉及战队查询与
  玩家菜单、私聊战队概览、群星牌觉醒变体合并、推送队列加固、Docker 交接失败
  恢复、B站抽奖/中奖订阅拆分、技能预览筛选和模块拆分。已检查日志、变更文件和
  部分配置差异，尚未完成逐项行为审计或移植，不能视为 V5 已获得这些能力。
- 前次只读观察的本地 `main` 为 `ba08f749`。从 `4b82881b` 起新增 11 个提交：
  B站 Opus/专栏正文补全、图片合并与历史摘要持久化，巅峰池有效期/投票展示，
  当前 fork 的页脚链接，自发指令超级管理员权限，以及橱窗别名候选昵称。
  已读取提交、相关代码和 Docker 差异；本轮没有 fetch/pull/merge 或移植。
  迁入时分别归属 HTTP integration、内容/投递 service、历史 repository、渲染
  view model、平台身份权限边界和玩家引用服务，不能复制旧插件内部依赖。
  `4b82881b` 的消息数组配置同样仍待独立迁入，不能误认为已在 V5 生效。
  Docker 差异仅新增项目链接构建参数与环境变量；本机 Linux 引擎不可连接，
  尚无实际镜像尺寸证据。
- 先前只读观察的本地 `main` 为 `d8c5c7ee`（下列早期拉取记录保留其当时状态）。
  `d15c02f8` 撤销背包徽标变更，与 `963a83c3` 的净差异为空；随后 `dbcfb241`
  修正大师池测试注解，`d8c5c7ee` 增加固定口令分条回复。仅查看，未 fetch、pull、
  合并或移植；分条回复需单独验证配置互斥、顺序和平台中立投递。
  先前读取的大师池/每周竞技点变化仍待移植：`master_pool` 的 SQL 读取放到
  repository，新增命令接入当前
  catalog，并让大师池类别参与快照、素材范围和 L3 键验证；不能直接恢复 main 中
  的 renderer 数据访问或旧分类推断。这是待移植产品变化，不是已验收功能。
- 后续用户明确要求拉取最新代码后已执行 `git fetch origin`：远端 main 没有新提交，
  也没有对应 V5 远端分支；未执行 main 合并或重写当前分支。
- 本次再次明确要求 pull 后，已在主检出目录执行 `git pull --ff-only origin main`，
  返回 Already up to date；main 仍为 `f19c7089`，没有合入 V5。
- 私有扩展安装去掉部分复制回退，增加有限权限重试；激活失败恢复旧包，恢复失败
  保留有效备份并报告路径。见
  [安装失败保护 Spec](specs/2026-09-05-extension-install-failure-safety.md)，
  提交 `3d5590a6`，安装/启动测试 26 passed。
- 新增内容菜单规划迁到 `services.seer.new_content_menu`；OneBot 只保留权限、会话、
  渲染适配与详情服务调用。普通预告/版本/赛季查询适配器降到 95 行，未保留旧菜单
  实现或重导出。见 [菜单边界 Spec](specs/2026-09-05-new-content-menu-boundary.md)。
- 本轮完整回归 1541 passed；其后类型边界修正的相关测试 12 passed。全仓
  BasedPyright 0 errors，Ruff、compileall 与 diff 检查通过。
- 没有新增运行依赖。再次检查本机 Docker 时 Linux engine pipe 不存在，实际镜像
  大小与层体积仍待可用构建环境测量。文件职责拆分不等同于镜像变小。
- 镜像层审计发现，COPY wheelhouse 后再删除仍会保留其镜像层；V5 改为 BuildKit
  只读挂载并冻结运行依赖导出。发布测量绑定本次构建 digest 并上传逐层记录；
  Docker 静态与 Bash 模拟测量测试 16 passed。见
  [镜像预算 Spec](specs/2026-08-15-runtime-image-budget.md)，实际构建减重尚未验收。
- 查询提示统一到 `services.operations.request_feedback`：入口、玩家保护与封包
  调度共享同一上下文及一次性发送状态，工作流可显式保存反馈对象。删除未使用的
  整数 QQ 去重器及 OneBot 群身份辅助模块，现用 ActorRef 去重逻辑不变。生产代码
  净减少 258 行，无配置或数据库迁移。见
  [查询提示 Spec](specs/2026-09-05-request-feedback-consolidation.md)。全仓回归
  1551 passed（87 条已有依赖告警）；BasedPyright、Ruff、compileall、diff 检查通过。
- 两套离线迁移共用 `state_migration_files` 的安装/删除/补偿恢复计划。修复 sidecar
  失败漏恢复、旧库清理中途失败丢失已删除源文件的问题；不引入运行时兼容。
  [迁移安装 Spec](specs/2026-09-05-offline-state-installation.md) 的临时库故障测试
  28 passed，全仓 1562 passed（87 条已有依赖告警），类型、Ruff、编译、diff 均通过。
  未操作生产数据；只保证可捕获异常下的补偿恢复，不宣称断电时的跨库原子性。
- `SqliteDatabase` 同版本连接改为只读检查；仅有待执行迁移时获取写锁，锁内重查
  版本。两个真实 WAL 并发读用例由锁超时转为通过；初始化竞争、过新版本、替换文件
  重查和失败回滚均有测试。见
  [SQLite 读路径 Spec](specs/2026-09-05-sqlite-schema-read-path.md)。专项 23 passed，
  全仓 1573 passed（87 条已有依赖告警），类型、Ruff、编译和 diff 检查通过。
  无新配置、schema 或运行依赖；不把此项误报为镜像体积或生产查询耗时测量。
- Phase 7 首批模拟平台验收完成：出站上下文保留回复序号/截止时间，推送失败日志
  保留 trace ID；真实命令权限、绑定和退订仓储通过字符串身份隔离及 capability 测试。
  [验收 Spec](specs/2026-09-05-platform-capability-acceptance.md) 专项 33 passed，
  全仓 1589 passed（87 条已有依赖告警），类型、Ruff、编译和 diff 检查通过。
  模拟器只在测试目录，无新增运行依赖；Phase 7 仅进入 `in_progress`，未接入真实官方
  平台，未把完整 AI/Seer 流程或真实 OneBot smoke test 记为完成。
- AI 平台测试复现两个合法群作用域身份因冒号拼接产生相同会话键、串用短期历史。
  改为完整身份字段的结构化 JSON 编码；保留现有长期记忆策略和 typed SQLite 查询。
  [AI 会话隔离 Spec](specs/2026-09-05-ai-platform-session-isolation.md) 专项
  32 passed，全仓 1596 passed（87 条已有依赖告警），类型、Ruff、编译和 diff 通过。
  验证了真实 AiService/记忆仓储、受限投递及管理员通知；未新增运行依赖或 schema。
- 阶段 1 按原完成条件做关闭审计，见
  [身份边界收尾 Spec](specs/2026-09-05-platform-identity-closure.md)。修复跨群作用域
  权限误判、未声明 channel/guild 被当作私聊、以及 scoped 管理员阻断整批通知的问题；
  戳一戳限流也在 OneBot 边界转换成 ConversationRef。身份状态库只读当前列，旧转换器
  仅由离线 CLI 路径调用。空/正常/重复/损坏/中断迁移测试、实际私有扩展测试通过。
  公共 1608 passed（87 条已有依赖告警），私有 24 passed，类型、Ruff、编译、diff 通过。
  未修改生产状态或 TOML；阶段 4/5/6/7 的完成条件不变。
- 阶段 5 修复玩家别名认领与执行的权限分歧：共用 actor + conversation 的引用
  lookup，六种公开玩家命令和私有阵容都沿同一接口，不新增 AI 保留词。
  [认领一致性 Spec](specs/2026-09-05-player-reference-ownership.md) 修复前 6 项失败，
  修复后专项 58 passed、公开全量 1644 passed、私有 26 passed；类型、Ruff、编译和
  diff 检查通过。还复现了参数化榜单目录认领缺失，见 Phase 5 未完成项；总进度
  保持 4/8。历史进度展示和私有扩展旧迁移文字已明确更新，无生产或依赖变更。
- 榜单 map 的别名、名次/页码/区间、全服分数和玩家引用均由领域 parser 认领；
  管理常量不再放在插件里重复维护。公共目录保留 `/`，活动与 B站前缀语法也复用
  各自 parser。[榜单认领 Spec](specs/2026-09-05-rank-command-ownership.md) 专项
  640 passed，公开全量 2209 passed（87 条既有依赖告警），私有 26 passed；
  BasedPyright、Ruff、compileall、diff 检查通过，无新增运行依赖或配置变更。
  声明迁移不等同于全部参数化输入已验收；Phase 5 剩余项见后文，总进度仍为 4/8。
- 订阅类命令复用领域 parser：B站推送参数、战队管理别名、橱窗关注均被目录
  正确认领，橱窗帮助的组合示例拆为真实可输入命令。战队快捷口令与 TOML 同源，
  空口令和关闭功能不会留下无效 matcher。见
  [订阅命令 Spec](specs/2026-09-05-subscription-command-ownership.md)。公开全量
  2261 passed，私有 26 passed；公开代码与测试类型检查、Ruff、编译、diff 通过。
  无新依赖或配置，未进行生产部署或镜像体积测量；总进度仍为 4/8。
- 推送管理、TD、恢复订阅及时间菜单入口改为 direct，各自登记 command/help ID，
  不再与数字回复一起豁免；私聊时间权限与实际入口对齐。订阅命令文本与时间入口
  常量由领域模块提供，未放宽 core conversation 认领。见
  [推送菜单 Spec](specs/2026-09-05-push-menu-command-ownership.md)。公开全量
  2286 passed，私有 26 passed，类型、Ruff、编译与 diff 通过；生产净增 9 行，
  无新运行模块、依赖或配置。总进度仍为 4/8。
- 配置文本与自动关键词各自安装一个 matcher，共用领域选择和回复发送；仅关键词
  配置不再漏注册，精确优先且单一命中。自动入口保留 automatic 目录语义，不结束
  旧菜单，冷却键与精确口令分离。见
  [配置回复 Spec](specs/2026-09-05-configured-reply-registration.md)。公開全量
  2302 passed，私有 26 passed，类型、Ruff、编译与 diff 通过；没有新模块或依赖。
  本地 main 只读确认仍为 f19c7089；总进度保持 4/8。

## 既有阶段验证基线（2026-08-15）

本节仅记录当时的验收基线，不是当前进度；当前总进度见上方“本轮验证”。

```text
历史基线（2026-08-15）：当时已完成阶段 3/8；不是当前状态
Phase 2 [██████████] 100%  私有阵容已只依赖文档化的 `core` / `extensions` / install 契约；渲染、查询和持久化均通过公开端口收口
当前任务[██████████] 100%  `d9215799` / `2b0442b0` 与本次公开查询/缓存端口、私有库 `65f09ec` / `64dba01` 已验证公开安装、动作注册、发布数据阵容快照、渲染、查询和缓存端口；公共 13 项、私有 20 项本轮针对性测试通过
```

这里刻意不写总体百分比或完成日期。此前的 `79%` 没有可复查的阶段权重，不能由
“已完成阶段 3/8”推导出来。下一次恢复百分比前，必须先为每个未完成阶段登记有限的
验收切片、依赖与预计工时；届时百分比只由已提交且验证通过的切片权重计算。实际
更新进度时仍须同时报告阶段和当前工作项，不能用总百分比掩盖外部发布、数据迁移或
跨仓库 smoke test 尚未完成的事实。

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

- `seerapi` 提交 `39c3339` 将 remote asset repository 和 immutable Git revision 升级为
  manifest v2 的显式 metadata；IronsBot `a7dd38f4` 在原子加载时验证该契约，并只用
  发布 revision 构造受保护素材 URL。SeerAPI 全量 260 passed；IronsBot 全量 1521
  passed、Ruff、静态检查、BasedPyright、编译和 diff 检查通过。

- **渲染资产范围审计（2026-08-15）：** `pet_info`、属性和巅峰 renderer 的图片
  家族均由当前 `pet_info` scope 覆盖。`new_content_standard` 额外发布
  `skin_image_resolution.head_resource_id` 中不属于普通精灵的专属头像；外部群星牌 URL
  即使成功获取也不写入最终图缓存。公共 `seer_data` 的全部 renderer adapter 进入最终图
  版本指纹，私有阵容继续使用自己的私有源码/模板指纹。幸运橱窗使用皮肤 body，当前没有
  完整 inventory，故其 L3 最终图缓存保持禁用；这比错误声明素材范围完整更安全。

**真实发布消费者 smoke（2026-08-15）：** 以本地生成的 SeerAPI release 验证后，
IronsBot 正确读取 immutable repository revision，并为精灵头像生成固定 revision URL。
该素材快照实际缺少 9 个精灵头像、12 个 body、1 个刻印图标、11 个装备和 11 个称号，
所以 metadata 正确发布空 `complete_scopes`，下游 L3 final-image cache 全部保持禁用。
这证明消费者不会用不完整 manifest 缓存图片；Phase 4 的剩余工作是向素材仓库发布这些
缺失资源，而不是放宽缓存准入或恢复 `main` fallback。

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
| Phase 1 | `completed` | 身份/权限/冷却/订阅/限流/通知与状态 API 均使用类型化身份；旧身份转换仅在离线 CLI；迁移异常与私有扩展契约均已验收，见 2026-09-05 closure Spec | 后续身份调用必须沿用 core refs；不得恢复旧列读取或私聊身份猜测 | 真实 QQ Official 已接入 |
| Phase 2 | `completed` | 内置插件已采用标准 NoneBot TOML 清单、`PluginMetadata`、`PluginContribution`、安装上下文和唯一 `CommandCatalog`；`d9215799` 将安装 API 从 `runtime` 收进 `core.plugin_install`，并以公开 `PlayerLineupExtensionContext` 注册私有动作、解析发布数据阵容快照；`2b0442b0` 与私有库 `64dba01` 已将阵容资源、最终图片缓存和 HTML 渲染迁到 `PlayerLineupRenderPort`；本次 `PlayerLineupQueryPort` 已收口无头请求、配额、错误语义与公共玩家格式化，`PlayerLineupCacheFactory` 已收口缓存迁移、读写和 SQLite 实现。私有运行包对公共 `services` / `integrations` 的导入审计为零。公共 13 项、私有 20 项本轮针对性测试通过 | 后续新扩展复用同一 install/context/command 契约；不得重建第二套插件发现或装配入口 | 所有外部扩展均已随当前公开契约验证 |
| Phase 3 | `completed` | OneBot 出站统一由 `OneBotOutboundMessenger` 实现核心 `OutboundMessenger` 端口；旧 `OneBotDelivery`、数值 target 模型和测试夹具均已删除。管理通知、活动提醒、定时消息、幸运橱窗、战队资源和 B 站动态均统一走 `ProactiveMessageDelivery` | 后续只允许在 `integrations/onebot` 增加真实平台转换；新业务不得重新引入数值 target 或批量投递对象 | QQ Official 已接入 |
| Phase 4 | `in_progress` | 资源准备、确定性文档内容键、部分 SeerAPI 效果事实，以及全部现有最终图渲染入口的请求级 L3 早期命中已验证；已发布素材使用 v2 immutable repository revision | 对每一类 renderer 素材做范围完整性验证，并完成新 release consumer smoke | 渲染数据发布契约完成 |
| Phase 5 | `in_progress` | 通用别名、玩家 ID 解析、命令认领与 AI 记忆异步化已验证；真实私有扩展公开契约已在 Phase 2 验收 | 剩余领域参数化输入覆盖、玩家查询缓存策略及完整发布链路验收 | 业务服务重构完成 |
| Phase 6 | `in_progress` | 新内容分类状态已不再猜测旧索引 | 逐项审计并删除剩余隐式 fallback、配置兼容和伪成功结果，且以错误语义测试证明 | 错误语义收口完成 |
| Phase 7 | `in_progress` | 首批模拟平台测试覆盖出站值、命令权限、绑定仓储和订阅投递 | 完整 Seer/AI 流程、审计与真实 OneBot smoke test | 真实 QQ Official 已接入 |

**配置兼容收口（2026-08-13）：** 玩家实时查询额度只接受
`seer.player.query_limits.bound_other_daily_limit`。已删除
`other_target_action_daily_limit` 的模型迁移器、运行时协议字段和示例配置；旧字段受
`extra="forbid"` 直接拒绝。`tests/test_app_config_loader.py` 记录拒绝行为，避免后续为
旧 TOML 恢复双字段或隐式重命名。

**群星牌 schema 收口（2026-08-13）：** `AutocardService` 只读取 SeerAPI 发布的
`autocard_role` 官方字段和 `autocard_role_raw` sidecar，已删除旧版仅含 `raw_json` 的
回退查询与测试夹具。缺少当前表结构会走既有“更新数据库”错误语义，不再双读旧发布物。
对应 SeerAPI 提交 `246f55c` 同步删除新内容索引对旧角色表的回退，并将索引 fixture
统一为官方表和 sidecar；两个仓库不再对同一发布物接受不同 schema。

**群星牌 repository 边界（2026-08-13）：** `AutocardService` 已移除直接
SQLAlchemy/Session/JSON 访问，只通过 `integrations.seer_data.autocard_repository` 获取
准备好的 `AutocardDataset`。当前 schema 查询、JSON 解包与数据错误属于集成层；服务层
只保留命令语义、搜索和展示格式化。
`AutocardSanctuaryService` 同样只接收
`autocard_sanctuary_repository` 的结构化场地效果行；两个群星牌服务均不再直接执行 SQL。

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

**主线功能吸收与镜像静态审计（2026-08-13）：** `22616886` 将当前 `main` 的
启动时钟诊断、B站动态详情补全/异步投递、查询回复锚点与新增内容图片菜单吸收到 V5 的
组合边界。B站后台任务由 `ApplicationLifecycle` 注入的 task owner 创建，领域服务不再自行
调用 `asyncio.create_task`；新增内容的自动展开项与同一 `Prompt` 的 `a1`、`a2` 等输入键
保持一致，不会出现图片中可见但会话无法选择的项目。完整 pytest 为 **1502 passed**，Ruff、
compileall 与 diff 检查通过。静态 Docker 审计确认运行镜像仍只显式复制运行代码、配置模板、
入口脚本和字体，仓库测试/文档/脚本/数据均被排除；二维码、HTML 渲染和 SVG 光栅化依赖
均有真实调用，不能为压缩镜像而删除。此工作站 Docker daemon 未启动，实际镜像字节大小仍须
由 CI 或 Docker 构建环境记录。

**渲染版本快照（2026-08-13）：** `SeerDatabase` 在 SeerAPI 内存库原子换版完成时
刷新发布版本；最终图片缓存读取该内存快照，不再为每个 `get`/`put` 额外开 SQLite
session。未加载数据仍显式返回 `unknown`，因此不会写入无发布版本的缓存。该项是下一步
`RenderRequestKey` 在 SQL/HTTP 之前安全命中的版本基础，不代表早期缓存本身已经完成。

**发布数据库装载契约（2026-08-15）：** `DatabaseManager` 现支持每个数据源的 staged
load validator。SeerAPI 在内存替换前必须证明存在 `api_metadata`、`ironsbot_metadata`，且
`ironsbot_schema_contract_version` 等于消费者支持的版本；失败时保留旧内存库和旧本地文件，
`/更新数据` 会返回具体契约原因。该校验不接受旧 schema 的双读或静默降级。

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

**构建职责拆分（2026-08-13）：** SeerAPI `6c2936d` 将 render asset repository 的 REST
commit/tree 获取、匿名限流后的 Git tree 回退和 `ls-tree` blob 解析迁出发布构建编排；构建器只
保留素材清单的领域枚举和写库。构建脚本动态加载测试、直接 `python scripts/build_seerapi_data_db.py
--help`、包导入、51 项构建测试、Ruff、编译和 diff 检查均通过。真实 smoke 在 REST 403 时
仍从 Git tree 读取 39,766 个 blob 条目。此项只拆协议边界，不改变 manifest schema、发布字段
或运行时消费契约。

**群星牌来源边界（2026-08-13）：** SeerAPI `2480a8f` 将群星牌四份官方 JSON 的读取与
`data` 信封规范化迁入 `scripts/autocard_sources.py`。构建编排层继续持有本地/远端来源选择、
网络下载、SQLite 写入与发布顺序；新模块不接触环境变量、网络或数据库，因而可由纯输入输出
测试独立验证。Ruff、`50 passed` 的构建相关测试、CLI 帮助、编译和 diff 检查均通过。这是
`build_seerapi_data_db.py` 按真实职责逐步拆分的下一块边界，尚未改变群星牌表结构或发布产物。

**发布元数据投影边界（2026-08-15）：** SeerAPI `9d197bd` 将 `ironsbot_metadata` 的
构造与 SQLite upsert 迁入 `scripts/release_metadata.py`。该投影只接收已经完成的构建事实，
不读取环境、网络或 SQLite 以外的输入；全量 SeerAPI pytest 为 **269 passed**，Ruff、编译和
diff 检查通过。入口脚本降至 1,226 行，尚未完成的边界只剩最终发布编排与真实 release consumer smoke。

**发布构建编排边界（2026-08-15）：** SeerAPI `13730e4` 将最终 SQLite 发布事务、
官方来源读取及经典皮肤素材探测分别迁入 `release_publication.py`、
`release_source_loaders.py` 与 `release_skin_image_loader.py`。入口脚本现在为 **727 行**，
只保留 CLI、构建顺序、配置装配和 SQLite 健康检查；所有新增生产模块均低于 800 行。
构建相关 56 项、SeerAPI 全量 **269 passed**、Ruff、编译、CLI `--help` 与 diff 检查通过。
真实 release 和 IronsBot 消费者 smoke 仍是 release gate，不能由本地单元测试替代。

**镜像体积基线（2026-08-15）：** Docker 发布工作流现在在 push 后拉取刚发布的首个
镜像标签，并把 Docker 报告的本地未压缩体积写入 GitHub Actions Summary。当前工作站的
Docker daemon 未启动，不能伪造实际大小；后续只在有连续发布基线后，才为增长设置预算或
删除运行依赖。静态审计确认 tests/docs/scripts/dev 依赖均不进入最终镜像，HTML 渲染、
Pillow、SQLAlchemy 与中文字体有真实运行时调用，不能以“瘦身”为由直接移除。

**效果元数据来源边界（2026-08-13）：** SeerAPI `e82d738` 将官方
`effectDes.json` 与 `signIconFight.json` 的纯解析和值对象迁入
`scripts/effect_metadata_sources.py`。发布构建器继续持有 URL、下载、失败日志和 SQLite
写入，新模块不依赖环境变量、网络或数据库。旧私有解析器入口已删除；构建相关 49 项、
SeerAPI 全量 **259 passed**、Ruff、脚本 CLI 帮助、编译和 diff 检查均通过。该步骤让
`build_seerapi_data_db.py` 净减少 81 行，为后续按来源继续拆出商店、契约和配置包二进制解析
建立同一边界，不改变已发布表或 IronsBot 查询语义。

**兑换商店来源边界（2026-08-13）：** SeerAPI `1699a74` 将战令商店、活动商店与
微光秘境三种官方 JSON 格式的纯解析和值对象迁入
`scripts/item_exchange_sources.py`。构建器只以来源 key/name 绑定通用解析器，并继续负责
下载、货币名称补全、失败日志和 SQLite 写入；三个专用包装入口均已删除。构建相关 49 项、
SeerAPI 全量 **259 passed**、Ruff、脚本 CLI 帮助、编译和 diff 检查均通过。此项没有改变
兑换价格表或发布契约，但后续商店来源可以直接复用对应解析器，而不再在构建总脚本增加补丁。

**伙伴契约来源边界（2026-08-13）：** SeerAPI `c143cfe` 将 ConfigPackage 提取出的
伙伴契约 JSON 校验、v1 描述顺序规范化和值对象迁入
`scripts/partner_contract_sources.py`。构建器继续提供 schema、契约类型和货币等发布参数，
以及网络下载、错误包装和 SQLite 写入；来源模块不读取环境、不访问网络或数据库。构建相关
49 项、SeerAPI 全量 **259 passed**、Ruff、编译和 diff 检查均通过。此项不改变已发布伙伴表，
但使来源格式变动能够在独立模块和测试中处理，而不再膨胀发布编排脚本。

**ConfigPackage 二进制解码边界（2026-08-13）：** SeerAPI `7b194ba` 将 Unity
PackageManifest、刻印品质、皮肤商店、道具说明、魂印图标和群星牌赛季效果的字节协议解码迁入
`scripts/config_package_sources.py`。发布构建器保留版本/manifest 下载、Unity TextAsset 提取、
来源选择和 SQLite 写入；解码模块不依赖环境、网络、UnityPy 或数据库。构建相关 49 项、
SeerAPI 全量 **259 passed**、Ruff、CLI 帮助、编译和 diff 检查均通过。构建主脚本从 4,671 行
降至 4,218 行，模块本身 331 行，未改变发布 schema 或运行时消费语义。

**渲染素材 manifest 边界（2026-08-15）：** SeerAPI `86c2de5` 将发布 SQLite 的素材 ID
枚举、immutable repository snapshot 匹配、scope 完整性、revision 与 consumer metadata 迁入
`scripts/render_asset_manifest_build.py`。发布构建器只保留环境配置、snapshot adapter、效果图标
生成、SQLite 表替换与 metadata 写入时机；新模块不读环境、网络、文件、FFDec 或 CLI。旧
manifest helper 已删除，构建主脚本从 4,553 行降至 4,122 行。SeerAPI 全量 **260 passed**、
Ruff、CLI 帮助、compileall 和 diff 检查通过。已发布 schema/metadata key 和 IronsBot 消费语义
没有变化；真实 release consumer smoke 仍是 Phase 4 的未完成门。

**效果图标 PNG renderer 边界（2026-08-15）：** SeerAPI `c1faedf` 将 FFDec sprite/shape
导出、PNG 透明度与尺寸校验、原子缓存读写以及有限并发迁入
`scripts/effect_icon_png_renderer.py`；`effect_icon_build_types.py` 统一传递已解析的构建配置和值对象。
构建器仍保留 Flash/Unity 来源选择与发布 SQLite 编排，因而没有把 Java、FFDec、UnityPy 或 Pillow
引入 IronsBot runtime。SeerAPI 全量 **260 passed**、Ruff、CLI 帮助、编译和 diff 检查均通过；
构建主脚本从 4,122 行降至 3,542 行。Flash/Unity source adapter 与 resolver/shard 仍待拆分。

**效果图标 source-path 边界（2026-08-15）：** SeerAPI `6ff44d0` 和 `1f8d029` 将 Flash/Unity
URL、Unity asset path、来源 URL 与 ID 解析迁入纯 `scripts/effect_icon_source_paths.py`，并补充
只依赖 `EffectIconBuildConfig` 的直接契约测试。构建器删除 50 行路径规则；Unity bundle 解码和
Flash HTTP 探测仍在发布编排层，未将未完成的 source adapter 伪装成已完成。

**私有扩展验证入口（2026-08-13）：** 私有仓库 `a278d11` 不再把测试 `pythonpath`
固定为本机相邻的 `../IronsBot`。测试启动时优先读取 `IRONSBOT_PUBLIC_ROOT`，再回退到
`public-runtime` 或传统 sibling 目录；因此 V5 工作树、CI 检出路径和标准本地布局均能验证同一
公开扩展契约。以 V5 公共环境实测私有测试 **24 passed**、Ruff 通过。该项只改变开发验证路径，
不改变运行时私有扩展安装或镜像内容。

**命令与榜单缓存契约收口（2026-08-13）：** IronsBot `c2a6f85e` 删除榜单玩家查询对
轻量测试桩的 `getattr()`/直接缓存读取回退，所有调用者现在必须实现
`RankService.cached_player_lookup()` 正式接口。同期，Docker 打包的戳一戳命令引入时间清单从
“每个命令一次 Git 子进程”改为单次顺序历史扫描；实测生成从约 **31.6 秒** 降至约 **7.2 秒**，
修复 Windows 上 30 秒测试超时。相关定向测试 32 项、IronsBot 全量 **1503 passed**、Ruff、
编译和 diff 检查均通过；这不改变用户可用命令或榜单查询语义。

**镜像依赖审计（2026-08-13）：** 已删除 IronsBot 未导入、也不由 `seerapi`
传递依赖的 `unitypy`。锁定闭包同步移除纹理解码、音频、压缩等 11 个运行时包；
HTML 渲染、二维码登录和 SVG 光栅化依赖仍因存在真实调用而保留。Docker 引擎在本机未
运行，故这一轮以 `uv export --no-dev` 闭包和启动/渲染 smoke 测试作为可复现证据；
发布前 CI 或 Docker 环境仍应记录实际 image size。

**身份边界收口（2026-08-13）：** 私有阵容的公开请求与查询 port 已从 `Any`
收紧为 `ActorRef` / `ConversationRef`。私有实现无法再构造无身份的实时无头查询；
公共队列、配额、操作追踪和未来平台适配均获得相同的类型化调用路径。

**玩家快捷查询职责拆分（2026-08-13）：** `player_shortcut_contracts` 现在唯一拥有
收集、巅峰和群星牌快捷命令的输入模型、语义请求和请求反馈；
`player_shortcut_queries` 只负责线上数据组合、排名与本地样本写入。删除旧聚合模块后，
OneBot 菜单、文本快捷入口、玩家服务与测试都直接依赖各自的窄边界。玩家 94 项、结构和
导入卫生 4 项测试、Ruff、编译与 diff 检查通过。该项减少 Phase 5 的服务职责混杂，
不改变用户命令或增加运行时依赖。

**Matcher 装配职责拆分（2026-08-13）：** `matcher_support` 现在唯一拥有 NoneBot
回调签名绑定、组合期 runtime-context token、菜单锚点与会话访问帮助函数；`matchers`
只保留 matcher 注册、命令准入、冷却和持久菜单入口。工厂从 760 行降至 609 行，公共
OneBot 导入面保持稳定但不创建第二套运行时路径。运行时、会话、插件导入卫生和生命周期
36 项测试、Ruff、编译与 diff 检查通过。

**核心语义请求直连（2026-08-13）：** 删除 `runtime.semantic_requests` 的常驻重导出层；
OneBot matcher、提示会话和测试均直接依赖 `core.semantic_requests`。这消除了 runtime 对 core
模型的伪所有权，也避免未来平台适配因历史导入路径被迫依赖 NoneBot runtime。会话、matcher、
提示和玩家详情 45 项针对性测试、Ruff、编译及 diff 检查通过。

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

**关闭证据（2026-09-05）：** 原完成门逐项清单和仓储/CLI/私有契约审计见
[身份边界收尾 Spec](specs/2026-09-05-platform-identity-closure.md)。公共全仓
1608 passed、私有全仓 24 passed，类型、Ruff、编译和 diff 检查通过。
平台身份与赛尔领域数字已按所有权区分；不能为减少检索命中而把米米号改成 ActorRef。
这是代码与临时数据的验收，不是生产迁移、真实官方平台或全部渲染发布的完成声明。

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
- 新增内容发布索引、赛季时间和 Flash 座驾素材读取已经分别迁入
  `integrations.seer_data.new_content_repository`、`season_repository` 与
  `flash_mount_repository`。`NewContentService`、赛季倒计时和装备服务只消费
  脱离 Session 的值对象；新功能必须沿用这一 repository 边界，而不是在 service
  内恢复 SQLAlchemy、JSON 或 Flash 文件访问。
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
- SeerAPI 现已为 `pet_head`、`pet_body`、`element_type`、`mintmark`、`item`、
  `sign_buff`、`suit`、`equip` 和 `title` 发布 remote asset manifest，并通过 v2
  metadata 将 repository/revision 固定给 consumer。IronsBot 只按该 revision 请求这些
  素材，不能在命中判断时对 mutable HTTP 素材做探测。预览图、任意 URL 群星牌图和未来
  renderer 仍未纳入该契约；在逐 renderer 范围验证及真实 release smoke 完成前，不得把
  Phase 4 标为完成。
- 私有阵容渲染也复用该内容键；私有模板和本地 Pillow 装饰源码以
  `renderer_fingerprint` 作为显式上下文参与键计算，不能维护第二套按阵容参数命中
  的最终缓存。
- 2026-08-05 验证：SeerAPI 全量 pytest `218 passed`、Ruff 通过；本轮新增的
  特殊效果 ORM 已可单独通过 BasedPyright。SeerAPI 仍有 38 条既有静态类型问题
  （旧模型抽象基类、旧解析器和构建脚本），必须作为独立清债工作处理，不能靠降低
  目标阶段的静态检查要求掩盖。

**逐素材家族证明（2026-09-05，Phase 4 切片）：** SeerAPI `e383e83` 从既有
manifest inventory 分别证明属性素材及头像/属性素材，不再让缺少无关立绘或刻印
禁用属性图、巅峰池/投票/精灵榜缓存。私有阵容通过公开端口复用同一头像/属性
加载器，消费者也共用该 scope；不新增清单或缓存。见
[独立范围 Spec](specs/2026-09-05-renderer-scope-independence.md)：生产代码构建端
净增 9 行，消费端只改一处映射。SeerAPI 全量 287 passed；公共渲染/缓存 64、
HTTP 素材源 4、映射调整后的数据库/阵容 13、私有扩展 26 passed，相关静态检查
通过。未发布 release、未改生产数据或 main。座驾发布、皮肤 body 完整范围和真实
release 消费验收仍未完成，不将该项写成 Phase 4 已验收；总进度保持 4/8。

**皮肤立绘发布范围（2026-09-12，Phase 4 切片）：** SeerAPI `ce42f5f` 在既有
manifest 增加独立 `skin_body` 范围，读取已解析 body ID，使用同一不可变仓库树，
复用 `pet_body` 素材类型并与已有精灵立绘去重。未解析/零 ID、空库存、缺列或缺图
不声明完整，且不会影响属性/巅峰/精灵既有范围。见
[立绘 Spec](specs/2026-09-12-skin-body-manifest.md)：构建模块 80 passed，专项
manifest 34 passed，Ruff、模块类型检查、compileall、diff 通过。消费者未提前
启用橱窗 L3；真实 release、动态 offer fallback 和完整请求键覆盖仍是完成门。
无新增数据库表、素材仓库或下载步骤。总体 4/8，不将生产者单仓库验证算成阶段完成。

同日只读真实产物核验：发布库 quick_check 通过，固定素材 revision
`1b53a16cfe32d36d921a04fbd8423116c5b1e2e1` 的 42,196 个 blob 中，268 条已解析
皮肤 body 全部存在；但完整皮肤表为 868 条，不能据此声明所有动态橱窗素材完整。
发布库尚无新 manifest，未替换生产库。消费端删除橱窗手写哈希，复用通用请求键，
纳入实际有序 offers 的名称、资源 ID、关注状态；来源缓存标志不改变图片键。
6 项定向渲染/缓存测试及 Ruff、定向类型检查通过；未重跑全量测试，未启用橱窗 L3。
动态 offer fallback、完整发布和消费者验收仍待完成，总体保持 4/8。

随后补全生产者的全部皮肤回退清单：优先解析 body，否则使用目录 resource_id，
与消费端一致，覆盖解析表之外的皮肤并去重。相同真实库和素材 revision 下，868 个
有效请求中 867 个存在，缺资源 `1400840`（皮肤 840、精灵 4911）；因此完整范围
正确保持未就绪。构建模块 83 passed，Ruff、定向类型检查、compileall、diff 通过。
未为缺图造替代数据，未启用橱窗 L3、未发布或更改生产配置；阶段仍为 4/8。

同日补齐缺图缓存策略：橱窗复用 `fetch_optional_image`，按立绘资源去重请求；
精灵信息的可选道具/效果图标和橱窗图片加载不完整时，仍返回降级图片但不写最终缓存。
恢复后重新加载并缓存，之后的早期命中跳过数据与渲染。15 项定向测试、Ruff、定向
类型检查及 diff 检查通过；生产代码净减少，无新依赖/模块。其他强制素材的 fallback
语义尚未在本批验收，不扩大完成范围，整体仍为 4/8。

强制素材后续核验：精灵详情、共用巅峰图片加载器和属性克制加载器显式使用
`fallback=False`，不再把远程占位图当成完整素材写入最终缓存；复用现有图片端口，
无新包装器。真实 HTTP 适配器/素材缓存配合 MockTransport 验证旧占位缓存隔离、
失败恢复及缓存命中；26 项相关测试通过，新增必需素材失败测试后的精灵适配器
4 passed，Ruff/定向类型检查通过。未做线上发布，整体仍为 4/8。

素材缓存任务所有权完成定向收口：`SeerAssetStore` 持有共享下载任务，所有调用者
只持有 shield 等待；首个调用者取消不再连带取消其他请求。磁盘读取也进入共享任务，
删除手工 Future 转发与多余锁，生产代码净减少。见
[共享素材 Spec](specs/2026-09-12-asset-singleflight.md)。素材/HTTP 联合 13 passed，
增加无人等待后重新加入案例后的素材模块 9 passed，相关静态检查通过。
未做完整阶段验收、未发布或修改生产 TOML，整体仍为 4/8。

素材请求的版本边界进一步收口：上游图片源同步准备 `PreparedImageRequest`，一次
捕获缓存身份与不可变下载地址；缓存排队后只执行该请求，不再从两个 getter 各读
一次版本。删除独立 source identity getter 和数据库旧身份方法，以新键命名空间
隔离可能混用的旧记录。HTTP/素材测试 15 passed，数据库版本测试 7 passed（2 个
已有 ORM 警告），定向静态检查通过。整张渲染图跨多个素材的一致快照仍待验收，
不将单素材一致性视作整个阶段完成；整体 4/8，未发布或更改生产配置。

最终图片缓存改为一次渲染持有一个 `RenderCacheEntry`，读写共享固定版本与范围。
检测到换版或撤销范围时不写入晚到结果；未知范围的旧条目不会因后来启用而取得权限。
七个公共渲染器与私有阵容全部迁移，删除分离 get/put 与 cached_image/cache_image
旧入口。公共渲染/缓存 49、架构/扩展边界 20、私有全库 26 passed，公共全范围类型检查
与 Ruff 通过。公共与私有须配套部署，未 push 或改生产。返回图像的完整一致快照
和 ABA 版本切换仍是后续验收项，整体维持 4/8，不将缓存条目契约当作阶段完成。

渲染快照前置生命周期检查发现数据库暂存引擎在源文件打开/复制失败时没有释放。
已将读取、复制与校验纳入同一清理边界，并复用只读 SQLite 连接，缺失源不会变成
空库。真实缺失/损坏文件与校验拒绝均验证旧库保持可读、临时引擎释放、不通知换版。
数据库相关 14 passed（2 个既有 ORM 警告），定向静态检查通过。此项只完成更新失败
资源所有权，不宣称渲染完整快照已完成，整体仍为 4/8。

数据库引擎生命周期进一步统一到 `DatabaseManager.snapshot(names)`：换版、重新注册
和关闭只退休仍被使用的引擎，最后一个快照释放后才 dispose；`session` 与
`all_sessions` 共用该路径。锁只保护注册表和引用计数，不持有到查询结束。
真实 SQLite 测试覆盖跨线程发布、旧/新查询分别读取对应版本、嵌套引用及异常退出；
数据库/版本回归 19 passed（2 条已有 ORM 警告），Ruff、定向类型检查、compileall
和 diff 检查通过。没有新增依赖、配置或数据库。整张图片的元数据/素材/缓存快照
绑定及 ABA 换版检测尚未完成，不据此提升阶段数；整体仍为 4/8。

发布元数据从独立回调字段改为按引擎缓存的不可变记录：版本、完整素材范围和素材
revision 在候选引擎验证期间一起准备，读端选择实际活跃引擎的记录，不再依赖
load listener 顺序。旧引擎记录使用弱引用键，不维护永久发布历史；重复元数据读取
无 SQL。数据库/版本/刻印/精灵渲染/同步回归 42 passed（2 条已有 ORM 警告），
Ruff、定向类型检查、compileall、diff 通过。生产代码净减少 9 行，无新增模块、
依赖或配置。完整渲染事务与 ABA 验收仍未完成，总进度仍为 4/8。

显式 `SeerReadSnapshot` 将查询入口和同引擎 `SeerPublication` 放在一起，通用
`SeerDatabase.query()` 已复用该路径；单次 SQL 会话仍及时关闭，快照退出后拒绝
再次查询并丢弃引擎引用。等待期间跨线程换版的回归确认新旧快照分别匹配对应
数据/元数据；相关回归 43 passed，最终异常类型调整后定向测试 1 passed，Ruff、
定向类型、compileall、diff 通过。没有 ContextVar 或全局渲染状态。素材/缓存装配
仍待绑定此快照，本项不是完整渲染验收；总计仍为 4/8。

精灵资料生产回调已使用 `SeerRenderSessions`：在缓存查找和 repository 查询之前
打开快照，固定对应 HTTP 素材源与最终缓存版本。绑定视图共用原有素材缓存、
singleflight、并发限制和最终缓存存储，不创建额外缓存实例。新缓存命名空间拒绝
旧的未绑定渲染结果，已绑定的旧渲染可以安全写回原版本。SQLite/MockTransport
验证跨 await 换版与回到旧版、不同版本隔离及相同来源请求合并；相关测试 37 passed，
架构/大小/目录/素材回归 30 passed，全仓 Ruff 通过；全仓类型检查仅发现已修正的
测试替身参数名问题，定向复查通过，compileall/diff 通过。无依赖、TOML 或私有契约
变更。其他入口的数据可能早于渲染准备，仍需把快照边界前移；真实像素/平台与其余
入口验收未完成，不提升阶段进度，总计仍为 4/8。

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
  入口完成。私有包现已导入 `core.command_catalog` / `core.player_reference_commands`，
  其渲染、查询、持久化及可见性经 `ironsbot.extensions` 的窄 context 提供；生产代码
  不再导入公共 service/integration/plugin 内部实现。真实 manifest 和公开端口验收
  证据归入 Phase 2；不得恢复旧 runtime 路径。2026-09-05 的进一步审计发现别名
  认领遗漏 actor 权限，见 [认领一致性 Spec](specs/2026-09-05-player-reference-ownership.md)。
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
- 新增内容的成就、技能和群星牌圣域详情文本由
  `services.seer.new_content_details` 统一格式化；OneBot 菜单仅负责将该纯文本投递到
  当前会话，不得重新内联同一批领域展示规则。
- 新增内容分类比较、自动展开、聚焦与选项规划由
  `services.seer.new_content_menu` 持有；`commands.new_content` 把结果适配为既有
  OneBot Prompt。领域规划不导入 NoneBot；原 `commands.data_queries` 不再参与菜单。

**命令来源迁移台账：** 每次把命令迁出插件时，必须在同一提交更新这里；未列出的
新命令不得在 matcher 内自建第二份示例、权限或帮助说明。
下表“已迁移”指声明的语义 owner 已迁出插件，不代表该领域全部参数化输入已通过
认领验收。参数化覆盖是 Phase 5 独立完成条件，不能用声明迁移替代。

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
| 私有阵容扩展 | `core.command_catalog`、`core.player_reference_commands` | 动作注册和公开 extension context 适配 | 已迁移，真实 manifest 和查询/渲染/缓存端口验收归入 Phase 2 |

**参数化认领收口（2026-09-05）：** 原 `专家榜15名` 解析成功但目录不认领的问题，
在 [榜单认领 Spec](specs/2026-09-05-rank-command-ownership.md) 中让四类榜单直接
复用 list/score/player parser 修复。管理命令同时复用领域常量与 parser；目录不再
全局去除 `/`，活动可选前缀和 B站必需前缀由各自领域规则确定。

**订阅类认领收口（2026-09-05）：** B站推送参数和战队管理直接复用领域 parser；
橱窗解析从 OneBot 移到领域服务。通用 parser 适配器也供榜单复用，None 才表示
未识别，0 等合法结果不丢失。橱窗每条帮助示例与实际 rule 验证一致；战队 query
commands 由配置提供，空/禁用配置同步控制目录和 matcher，详见订阅命令 Spec。

**实体查询认领收口（2026-09-05）：** 全部现有前后缀查询入口共用 core
`AffixCommand`，领域服务拥有语法，OneBot 只写入参数 state；精灵、图片、刻印、
宝石、装备、属性、异常、战队、群星牌及精灵配置目录调用相同 parser。删除原
OneBot 解析实现和插件 `query_rules`，固定图片/榜单排除也统一到领域判断。
目录存在 parser 时以其结果为准，不再让帮助示例绕过拒绝；保留榜单总览的实际
别名。见 [前后缀 Spec](specs/2026-09-05-affix-query-ownership.md)：16 项失败已复现，
公开全量 2493 passed、私有 26 passed、类型检查 0 errors，Ruff/compileall/diff 通过。
该批尚未覆盖的巅峰池/投票别名和刻印数值榜，已由下述独立工作项验证；不能把
前后缀批次本身视为全领域验收。无新依赖或配置，未测量镜像，进度保持 4/8。

**巅峰/刻印/数据认领收口（2026-09-05）：** 巅峰别名迁入现有领域模块，由实际
fullmatch 入口和目录共用；刻印数值榜两端直接使用同一 parser，删除 service
转发包装和六条重复排除词，改用真实榜单 parser 排除其他榜单。数据口令目录
覆盖全部赛季别名，新增内容只由自身 contract 认领。见
[命令认领 Spec](specs/2026-09-05-peak-stat-command-ownership.md)：专项 212 passed，
最终公共全量 2645 passed（319 条依赖告警）、私有 26 passed；Ruff、BasedPyright
0 errors/warnings、compileall、diff 检查通过。先前全量中的启动子进程 30 秒超时
保留为未解释的间歇失败，未放宽超时，最终全量已通过该测试。生产代码净增 46 行，
没有新生产模块、配置或依赖，不宣称镜像减重。该批尚未覆盖的图片编号命令见
下一项独立验收，Phase 5 未完成，总进度仍为 4/8。

**图片输入认领收口（2026-09-05）：** 图片 service 接收配置前缀，复用
`AffixCommand` 解析全部图库中的最长别名，目录与实际 rule 共用结果。处理器
消费已保存的类型化编号，不再重新解析文本；随机选择、越界提示保留。单图仍为
精确匹配；空前缀列表只关闭编号图库，帮助与图片保留词使用真实前缀。无效数字
在 I/O 前拒绝，不再走未捕获的整数转换错误。见
[图片输入 Spec](specs/2026-09-05-image-command-ownership.md)：专项 95 passed，
公共全量 2671 passed（319 条已有依赖告警）、私有 26 passed；Ruff、类型检查
0 errors/warnings、compileall 与 diff 检查通过。生产代码净增 60 行，未增加
生产模块、依赖或 TOML 字段，未测量镜像。只读复现了通用目录的剩余精确匹配
差异：`帮 助` 被目录认领而真实 fullmatch 拒绝；需从共同契约处理，不能继续
逐个插件复制空格/大小写特判。该差异已由下面的共同契约工作项解决；图片批次本身
不代表全领域认领已完成，进度保持 4/8。

**精确命令契约收口（2026-09-12）：** 目录默认按原始文本匹配精确示例/别名，
显式参数解析器仍为语法权威。允许规范化的文本、订阅、会议、B站和战队入口统一
显式复用 `command_text_matches`；删除单图的重复精确 parser 包装。私聊 AI 在
判断目录认领前不再 strip，避免改变真实语法。见
[精确命令 Spec](specs/2026-09-05-exact-command-contract.md)：公共全量 2697 passed
（319 条依赖告警，203.24 秒），专项 37 passed，私有 26 passed；Ruff、类型检查
0 errors/warnings、compileall、diff 检查通过。旧测试句柄已失效，本轮重新运行完整
测试，没有把中断前的输出当作通过证据。生产代码净增 29 行，无新增运行模块、依赖、
配置或数据库字段，未测量镜像。玩家详情缓存仍只按写入时刻计算 TTL，原始观察时间
尚未成为缓存准入依据；此项和全领域/真实平台验收独立，Phase 5 未完成，总计 4/8。

**详情缓存来源时间准入（2026-09-12）：** 上项指出的内存详情缓存问题已收口。
`QueryReply` 保存与展示一致的最早获取时间；收集、巅峰、群星牌统一按来源年龄和
单调时钟截止时间判断复用。未知、未来、非有限时间及部分失败不进入新鲜完整缓存，
结果投递与额度实时优先策略保持。见
[缓存 Spec](specs/2026-09-12-player-detail-cache-freshness.md)：相关 90 passed，私有
26 passed，Ruff、类型检查、compileall 和 diff 检查通过。按用户要求减少重复检查，
本项不再跑公共全量，留到阶段门验证。无新运行模块、依赖、TOML 或 schema 变更；
持久化 fallback、动态榜单一致性及真实发布尚未完成，进度保持 4/8。

**基础资料回退缓存（2026-09-12）：** 来源 TTL 计算提至现有 `core.time`，基础
资料与详情共用。基础缓存要求匹配米米号的原始快照时间，缺失或过期不进入缓存；
联网失败/额度回退在返回时重新读取缓存，不再保留请求前取出的过期结果。额度内
实时优先和缓存不重复计费保持。相关测试 79 passed，私有 26 passed，类型检查
0 errors/warnings，Ruff/compileall/diff 通过；未重复跑公共全量。见
[回退缓存 Spec](specs/2026-09-12-player-fallback-cache.md)。无新运行模块、依赖或
数据库变更，仍未覆盖持久化 fallback 与真实发布验收，总计 4/8。

**推送菜单入口收口（2026-09-05）：** “推送管理 / TD / 恢复订阅 / 推送时间”
已改为 direct 并登记真实 matcher command/help ID；共享领域命令文本。私聊时间
管理与群管理权限均与实际 rule 对照验收，数字/时间回复继续由 PromptFlow 隔离，
没有把所有 conversation 视为 direct，见推送菜单 Spec。

**配置回复收口（2026-09-05）：** direct / automatic 各自依据已启用配置注册，
仅关键词配置能独立响应。两类复用领域精确优先与 feature 检查，共用发送 handler；
自动回复不结束旧会话且不参与 AI 直接认领。同名动作冷却键独立，未保留泛化 ID
回退，见配置回复 Spec 的安装矩阵和回归证据。

**多榜部分结果收口（2026-09-05）：** 收集、巅峰在汇总超时后改用逐项完成记录，
不再丢弃已完成的名次、分数、缓存时间和查询成本。正常与部分返回共用模型构造；
删除按最后一个中文榜名标错的 `mark_failure`。真实汇总/页调度器加受控协议页的
回归先复现两项失败，修复后针对性 25 项、公共全量 2306 项、私有 26 项通过，
Ruff、类型检查、编译与 diff 检查通过，见
[部分结果 Spec](specs/2026-09-05-player-rank-partial-results.md)。

**Phase 5 仍未完成：** 其余领域参数化输入与完整玩家多榜失败/渐进返回验收仍需
完成。已将 foreground/background 详情预算统一为一个单调时钟截止时间，基础、
榜单和样本只使用剩余预算；巅峰三个基础模式共享阶段预算，不再各复制一份。
删除整份详情的同期限取消包装和反射配置回退；真实服务链路的六项旧失败已修复，
加上取消/零预算边界共 58 项针对性测试、公共全量 2322 项、私有 26 项通过，静态
检查通过。保留原后台清理宽限看门狗，不把它当作普通数据预算。

**详情发布与缓存归属（2026-09-05）：** 已验收真实详情服务的独立分项回发、
完整性标记、部分回复不复用，以及过期生产任务不能发布到新一轮等待者。公共
OneBot 会话入口在修改版本之前检查取消，修复旧任务虽不发消息却使新菜单失效
的问题；真实详情 handler/会话/Prompt 路径验证数字选择和用户/群隔离。见
[详情发布 Spec](specs/2026-09-05-player-detail-publication.md)。专项 97 passed，
公开全量 2348 passed、私有 26 passed，静态检查通过。无新运行模块、依赖或配置。
这不是生产 QQ/官方服务联调；参数化输入覆盖、缓存数据新鲜度及发布消费者验收
仍未全部完成。总进度仍为 4/8。

**数据观察时间，第 1 步（2026-09-05）：** 玩家榜单查询统一读取带时间的
`RankPageResult`，删除位置查询重新生成当前时间的包装。锚点、线性、二分、
缓存命中、未上榜证明和超时回退保留最早必要证据时间；排除账号换算也纳入时间，
不改轻量配额规则。删除两处缓存反射/转发函数，生产净减 38 行。见
[观察时间 Spec](specs/2026-09-05-player-data-observation-time.md)：专项 90 passed、
公开全量 2354 passed、私有 26 passed，静态检查通过。该步只完成榜单证据传递，
详情与阵容标题在下述第 2 步完成；多页窗口/同分段仍需审计。

**数据观察时间，第 2 步（2026-09-05）：** 收集、巅峰、群星牌和阵容标题接入
显式来源时间，格式化函数不再读取当前时钟。基础快照保留原时间；组合结果复用
`core.time.ObservationTime`，取必要证据最早时间，未知不补成当前时间。巅峰只纳入
完整成功模式的封包时间，失败榜的目标分数不充当已获取数据。阵容缓存重新打开及
详情结果重用均保留标题。见同一 [观察时间 Spec](specs/2026-09-05-player-data-observation-time.md)。
专项 72 passed、公开全量 2378 passed、私有 26 passed；类型、Ruff、编译、diff 通过。
生产净增 95 行，没有新运行模块、依赖、数据库或 TOML 字段，未测量镜像大小。
本地 main 仍为 f19c7089，没有 fetch/pull/merge/push；总进度仍为 4/8。跨页范围和
同分段时间合并已在下述第 3 步完成；实际发布消费者验收仍未完成。

**数据观察时间，第 3 步（2026-09-05）：** 跨页窗口、同分段及排除账号的公开名次
共用观察时间聚合，保留必要页中最早的时间。二分探针和未显示的边界页也提供时间
依据；空请求没有时间，缓存定位只作提示，在线确认后采用确认页时间。删除丢弃
元数据的 `fetch_item`，全服榜格式化必须接收显式时间，不再使用当前时钟兜底。
见 [跨页时间 Spec](specs/2026-09-05-rank-window-observation-time.md)：专项 120 passed、
公开全量 2395 passed（274 条依赖告警）、私有 26 passed；类型、Ruff、编译、diff
检查通过。生产净减 3 行，无新运行模块、依赖、数据库或 TOML 字段，未测量镜像。
未修改 main、私有未跟踪 uv.lock 或生产数据。总进度保持 4/8；探针耗尽语义在下述
Phase 6 切片完成，缓存准入/新鲜度策略和真实发布验收仍是未完成门。

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

**分数探针耗尽语义（2026-09-05）：** 算法已有的 `budget_exhausted` 现在传到领域
结果与格式化，不再把未查完说成“没有这个分数的用户”。终点未确认时保留实际
找到的用户，只展示已确认样本，不将安全扫描终点当成真实同分人数或连续范围。
见 [探针耗尽 Spec](specs/2026-09-05-score-probe-exhaustion.md)：三类错误文案已复现，
五个新增服务链路用例修复后通过；专项 114 passed、公开全量 2400 passed、私有
26 passed，类型、Ruff、编译、diff 检查通过。生产净增 14 行，没有新运行模块、
依赖或配置；不改阶段探针预算和重试策略。缓存候选的边界证明在下述切片完成，
动态榜单一致性仍需独立验收，Phase 6 保持 in_progress；总进度保持 4/8。

**缓存候选完整性（2026-09-05）：** 在线候选确认和纯缓存同分查询共用
`score_segment_coverage`，只有连续匹配区间和两侧边界都有依据才返回完整人数。
预算用尽不会跳过检查，离散候选必须补齐中间页；查询首尾和非整页范围不再误当缺页。
重复玩家、分数倒序异常及矛盾的结束页不能证明完整区间。现有 SQLite 无法区分短页
与缺失条目，继续明确拒绝不完整缓存，不为测试放宽数据契约。
见 [缓存覆盖 Spec](specs/2026-09-05-score-cache-coverage.md)：专项 71 passed、公开
全量 2415 passed、私有 26 passed；类型、Ruff、编译、diff 通过。另以 2205 组
静态窗口/页面子集枚举校验完整性。删除重复边界循环，生产净增 5 行，无新运行模块、
依赖、配置或 schema；未修改 main 或生产环境。新鲜度策略、动态快照与发布验收
不在本次完成范围内，总进度仍为 4/8。

**否定缓存新鲜度（2026-09-05，Phase 6 切片）：** 在线玩家榜单查询不再继承
允许旧缓存的全局开关来复用过期“未上榜”；显式纯缓存查询仍保留历史时间。
同榜同玩家在覆盖范围内已有相同或更新的正向观察时，旧否定证据不可使用；
延迟完成的否定写入不覆盖更新的证据，也不删除更新的旧坐标。两处既有模块
生产净增 10 行，无新增运行模块、配置或 schema。见
[否定缓存 Spec](specs/2026-09-05-rank-miss-freshness.md)：修复前复现 7 项失败，
专项 93 passed，私有 26 passed，Ruff/类型/编译/diff 通过。公共全量 2433 passed、
1 failed：唯一失败是启动子进程超过既有 30 秒限制；未改代码或放宽超时的独立
复跑 1 passed（19.20 秒）。这不是一次全绿的全量运行，启动时延仍留给 Phase 7
验证。组合详情缓存准入、动态快照和真实发布验收未完成；总进度仍为 4/8。

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

**首批验收范围（2026-09-05）：**

- 测试模拟器只实现现有 `OutboundMessenger`，不进入生产包、不增加运行依赖。
  回复序号/截止时间沿已有入站/出站值传递，失败日志保留 trace ID。
- 复用真实 help/about contracts、FeatureService、PlayerIdResolver、绑定仓储、
  退订仓储与 ProactiveMessageDelivery。图片测试验证二进制出站部件传递及模拟上传，
  不代表精灵渲染已在真实官方平台验收。
- 合成的 `fake_*` 错误码及可配置限制只用于验证错误传播，不声称复刻官方协议。
  真实官方码值/规则、完整 AI/Seer 工作流与真实 OneBot smoke 仍需后续验证。
- 具体证据见 [首批 capability Spec](specs/2026-09-05-platform-capability-acceptance.md)。
  本阶段仍为 `in_progress`，不增加已完成阶段数。
- AI 服务级验收已覆盖结构化会话身份、SQLite 重启记忆与隔离、回复过期以及受限
  管理员通知，见 [AI 会话隔离 Spec](specs/2026-09-05-ai-platform-session-isolation.md)。
  模型网络使用测试客户端；这不等于 AI 插件会话或所有意图动作已在另一平台完整验收。

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

## 主线同步记录

- **2026-09-12 / 玩家配置边界：** 删除 `PlayerQueryCache.from_config(object)` 的
  反射/default 路径，服务直接传入已验证的 TTL；删除没有调用方的旧
  `shortcut_timeout_seconds`，活动调度超时逻辑不变。相关 84 项、私有 26 项通过，
  Ruff/类型/compileall/diff 通过。见
  [配置 Spec](specs/2026-09-12-player-config-boundary.md)。无新运行模块或字段，
  只删除旧路径；阶段仍为 4/8，未重复全量或部署验收。

- **2026-09-12 / 镜像内容边界：** 保留已有多阶段构建、临时 wheel 挂载和 no-dev
  依赖安装；恢复被裁剪的根许可证/授权说明，内置图片与必需依赖未删除。既有发布
  digest 体积证据增加网络隔离容器的运行目录 KiB 清单，覆盖代码、依赖与字体。
  见 [镜像 Spec](specs/2026-09-12-runtime-image-inventory.md)，相关 16 项通过，
  Ruff/diff 通过。测试模拟 Docker，仅证明工作流命令和归档契约；实际镜像构建、
  目录占用和体积对比仍未验证，不据此增加阶段计数或宣称减重。

- **2026-08-15 / `origin/main` `af2e8810`：** 已抓取，尚未直接合并到 V5。该批次
  包含活动周快照、竞技池变动展示、幸运橱窗卡片、Docker 维护菜单、更新确认和绑定
  限制等功能。它依赖已退役的 command-directory / plugin / runtime 路径，与 V5 的
  NoneBot 插件装载及 command contract 发生结构冲突。后续必须按
  `docs/specs/` 中的上游同步 Spec 逐项迁入并验证，不得把自动 merge 误报为完成。
- **2026-08-15 / 活动周快照：** 已在 V5 的 `ActivityService`、活动命令 contract 与
  `runtime_state.sqlite` 中迁入。`新增活动` 对比当前周和上周已观察到的活动 ID；首周
  没有上周快照时明确提示，后续只显示差集。未恢复旧活动插件或 command-directory。

- **2026-08-13 / `origin/main` `7757a48f`：** 已合并到 V5 工作分支。该主线修复的
  行为是：B站公开昵称刷新失败时，“TD / 推送管理”仍可打开，选项退化为 UID 并显示
  警告，而不是拒绝整个菜单。V5 保持 `ConversationRef` 作为消息服务的唯一会话
  标识，未恢复已删除的旧 `plugins/messaging` 路径；适配位于
  `services.bilibili.targets.prepare_subscription_labels()` 和
  `services.messaging.service.prepared_subscription_menu()`。
- **验证证据：** `tests/test_bilibili_monitor_state.py`、
  `tests/test_messaging_runtime_setup.py` 共 46 项通过；全量测试 `1505 passed`，
  `ruff check ironsbot tests`、`python -m compileall -q ironsbot` 与
  `git diff --check` 均通过。
- **2026-08-14 / `origin/main` `24d54d82`、`cc86b1d6`：** 已以 V5 的服务常量和
  Seer repository 边界吸收开服别名及新增内容竞技池变动入口。后续主线
  `857d27d8` 将新增内容菜单重做为旧 renderer 的预览矩阵；它不能直接覆盖 V5
  的快照/Presenter 链路，须在准备好同等的不可变 render document 后再选择性迁移。
- **2026-08-14 / `origin/main` `32461c12`：** 已迁入 B站缺正文与 Opus 正文截断
  的详情补全；只有详情正文更完整时才替换。V5 保留自己的 task owner 与 delivery
  边界，未复制旧 runtime 调度路径。

## 数据读取边界记录

- **2026-08-13：** 刻印角数、皮肤资源解析与每周预告元数据读取已迁入
  `integrations.seer_data`；赛尔 service 仅保留命令编排与业务格式化。
  跨领域的正整数转换同时迁入 `core.value_coercion`，避免 repository 反向依赖
  `services.seer`。相关查询、皮肤、预告、榜单和本地排行测试共 32 项通过。
- **2026-08-14：** 新增内容发布索引、赛季时间和 Flash 座驾素材读取分别迁入
  `new_content_repository`、`season_repository`、`flash_mount_repository`。
  相关聚焦测试共 65 项通过；Ruff、compileall 与 diff 检查通过。
- **2026-08-14：** 巅峰池、投票、赛季周期及精灵快照读取迁入
  `peak_repository`。巅峰 service、私有阵容条目解析和 renderer 只消费已脱离
  ORM Session 的快照；巅峰查询、投票、渲染和架构边界测试共 36 项通过。
- **2026-08-14：** 皮肤资料与商店价格读取迁入 `skin_price_repository`；价格显示
  仍是 service 层的纯格式化规则，精灵查询只接收 `SkinDetails`。
- **2026-08-14：** 幸运橱窗按资源 ID 补全皮肤资料的 ORM 查询迁入
  `skin_reference_repository`；协议请求、缓存和关注偏好不变。
