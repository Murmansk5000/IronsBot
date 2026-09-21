# IronsBot 多平台架构重构工作分解

本文把长期架构目标拆成可独立验证的阶段工作项。它的职责是记录迁移顺序、依赖、
完成证据和回滚边界；长期所有权、目标契约和 transition 准入规则以
[ARCHITECTURE.md](../ARCHITECTURE.md) 为准，工作方式以
[engineering-workflow.md](engineering-workflow.md) 为准。

本轮生产基线保持 NoneBot2、OneBot v11、NapCat 和 Docker/Unraid；Python 运行基线现已
统一为 3.11+。QQ Official 已进入真实 MVP：腾讯 `qqbot-agent-sdk` 作为独立应用资源
运行，NoneBot 只托管 OneBot；被动群/C2C 查询按共享命令目录逐步开放。平台不能可靠
表达的数字 QQ 继续按能力延期，不做伪映射；主动推送只使用明确配置的 OpenID 目标。

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
Program  [████████]  verified phases: 8/8
Phase 7  [████████]  live acceptance milestones: 8/8
Task     [██████████] completed only after code, tests, and evidence are committed
```

进度条只表达已验证的阶段或当前任务完成状态。除非 Spec 已定义可审计的加权验收项，禁止报出整体百分比或总体 ETA。

## 当前权威状态（2026-09-21）

Phase 0 至 Phase 7 已关闭。唯一公开开发与发布源是
`Murmansk5000/IronsBot` 的 `main`。当前生产运行时修订为 `ae186314`，Docker Hub 清单
digest 为 `sha256:a629bb7be846c32db312f632e4e0a1d6a337897bb47572cc80db656df42be87a`，
Unraid 展开大小为 `260096148` bytes；发布流水线 `35583061598` 的构建、离线 smoke、
依赖审计、目录与增长门禁均通过。生产 `config_check` 确认 QQ Official 是唯一出站平台、
OneBot outbound 关闭且 observer 身份验证保持启用；五个独立官方账号均取得 AccessToken
并进入 READY，OneBot observer、三无头 worker 和共享 Docker 网络健康。

该候选同时包含已验收的成员提及修复：TEXT 不解析 OpenID 提及，而 Markdown 与 source
`message_reference` 组合会导致部分 QQ 客户端重复正文。正式路径将首条群回复收口为一条
Markdown：同时包含发令成员提及、换行和正文，并携带被动 `msg_id`/`msg_seq`。该路径不另发单独
`at` 或 TEXT 正文，不占用第二次回复额度；字面 OpenID 标签为零。新精确 digest 已完成
启动、三账号隔离和一条公众账号 C2C 被动回复。权限、故障和主动投递的当前可控范围已经
闭环；AI 独立备用文本 provider 已完成真实 HTTP 401 到备用 HTTP 200 的跨 provider 切换。
腾讯自然产生的拒收/额度事件作为非阻塞 External TODO 保留，不能把未发生的平台事件描述为真实通过。

`docs/` 不进入 Docker 构建上下文。后续纯文档提交可能因 OCI revision 标签生成不同
manifest digest，但不会改变运行时文件；Phase 7 可继续使用上述行为候选，除非实际生产
部署选择了另一个精确 digest，届时必须在验收记录中固定所部署的值。

最新公开代码镜像来自 `ae186314`，workflow `35583061598` 已将 Docker Hub/GHCR 的
`0.5.1.1970` 与 `sha-ae18631` 固定到上述共同 digest。该候选已经写入生产 Unraid。多账号
群主动推送按 `group_routes` 或唯一静态端点选择一个账号，非归属账号仍可完成被用户直接
寻址的被动回复；AppID 作用域内的 C2C 主动端点不受群选主规则影响。

主要查询矩阵已在此前生产 runtime tree 上完成 A1-A12：最后缺失的幸运橱窗使用受控
OneBot 身份完成账号绑定、登录确认、隔离查询、四皮肤持久缓存和最终图片送达。生产专用
密码只存在于 Unraid 掩码环境变量，不进入 TOML 或仓库。当前精确 digest 已复用相同业务
树并完成启动验证。2026-09-21 用户在手机 QQ 确认最终视觉正确：成员提及与正文位于同一条
消息、提及后正确换行、正文只出现一次；服务器同时记录到对应命令仅产生一次官方被动文本
投递。因此 B10 与 Phase 7 最后一个里程碑均已关闭。

同一 `667177ea` 生产镜像重新生成幸运橱窗 v2 卡片，客户端收到一张 1040×559 PNG；四个
皮肤、风尚券图标、钻石图标和中文均正常。字体稳定的 `★` 关注标记另由本地真实 HTML
渲染检查覆盖。v2 缓存键隔离旧版无图标卡片，资源加载仍在 integration 层，纯
Presenter/Renderer 边界未回退。

已发布提交 `9aa4ee79` 将命令执行授权与帮助/戳一戳可见性分开：超级管理员可按
`superuser_bypass` 执行未对群开启的 Feature，普通成员仍受群策略限制，黑名单和命令
audience 不被绕过。真实客户端已经覆盖超级管理员绕过、普通成员隔离和黑名单优先级；
管理异常已验证超级管理员私聊通知链及普通群零泄露的真实负向观察。

公开 `main` 已包含运行时修订 `1a4b8230` 及其后续验收文档；每轮仍须以实际
`git rev-list --left-right --count origin/main...HEAD` 结果核对同步状态。完整私有重构
历史已作为第一父线并入公开主线，公开后续完善历史作为第二父线保留，合并时代码 tree 为
`e548fa049c2bbf4c4d93e0ef424c024cd5e162e0`。私有 Preview 的全部 refs 均可由公开仓库
到达，Release 资产哈希一致，仓库已设置为 Archived；活动工作树已移除 `preview` remote。
后续不得再把私有 Preview 当作开发、同步或发布源。

五个真实 AppID 已在同一生产实例中完成独立 READY、群路由和选主隔离。其余外部门槛包括
腾讯主动消息拒绝/额度、拒收事件、自定义键盘权限和腾讯实际重复重投。它们不得被基础
查询成功替代，也不阻塞继续完成可独立验证的生产项目。

### 2026-09-20 三仓联合审计

- IronsBot 公开 `main` `64058429`：全量 `3826 passed, 7 skipped`；Ruff、生产与测试
  BasedPyright、compileall、静态仓库检查和 diff check 通过。
- SeerAPI 发布源为 `Murmansk-Seer/seerapi`，远端 main `0c7c9d5`。本地 `main` 已纯快进
  到同一远端提交；全量 `351 passed`、Ruff 通过。远端同一 main 的数据构建 workflow
  `35459548628` 成功。
- 当前远端 `seerapi-data-latest` 为 133,435,392 bytes，下载 SHA-256 与发布校验文件
  一致，并由 IronsBot 消费端重新严格验证 schema contract v2 与 DDL 指纹。正常运行
  路径没有旧字段 fallback。
- `ironsbot-private` main `9c3d61e` 与远端一致，发布 workflow `35439115557` 成功；
  使用当前 IronsBot 公共扩展契约执行 `27 passed`，Ruff 与 BasedPyright 通过。仓库原有
  未跟踪 `uv.lock` 保持未提交。
- 另一份公开 IronsBot 旧 checkout 仍停在 legacy 历史，和发布 main 已双向分叉，并含
  未跟踪 `cache/`、`runtime/`；它不是当前发布源，也未被清理、覆盖或合入。
- SeerAPI 仓库尚未把全仓 BasedPyright 设为绿门禁；用当前检查器审计 scripts/tests
  得到 68 个既有类型问题。测试、发布构建与 consumer contract 均通过，但不得把这一
  结果写成“三仓全量类型检查通过”。该类型债独立记录，不在 Phase 7 中用降低规则或
  大规模无关重构掩盖。

## 历史验证记录（始于 2026-09-14）

总任务 `[███████□]`：Phase 0 至 Phase 6 已验收，当前为 7/8；各阶段关闭依据见
对应整体审计记录。Phase 7 继续进行，不按阶段数推算整体百分比。
下方早期记录保留当时的测试与状态；跨仓库发布与真实平台仍未完成，暂无可靠总体 ETA。

阅读规则：下方在提交 `c66eec1b` 之前提到 `nonebot-adapter-qq` 的段落只是当时的历史
快照，不描述当前受支持的运行路径。当前 QQ Official 传输只使用
`qqbot-agent-sdk==1.2.2`；不得从历史记录恢复旧适配器、静态 token 或双轨发送路径。

- QQ Official 传输已由提交 `c66eec1b` 切换到腾讯官方
  `qqbot-agent-sdk 1.2.2`。NoneBot 只继续托管 OneBot；腾讯 SDK 作为应用资源独立维护
  每 AppID 的 Token、WebSocket、Resume session 和发送客户端，入站仍只进入共享
  portable router。SDK 当前覆盖 C2C 与 `GROUP_AT_MESSAGE_CREATE`，普通群消息事件不在
  该版本解析范围内；真实 AppID 登录、图片发送、主动额度和平台权限仍是 Phase 7 外部门。

- QQ Official 的有限选项交互已收口到共享 `PromptSession`：数字回复和按钮 action 使用
  同一份用户、会话、账号及消息绑定，并由同一个 portable router 消费，不存在独立的
  callback 业务路径。只有腾讯后台已开通内邀自定义按钮权限、且对应账号显式设置
  `custom_keyboards = true` 时才发送 type-2 指令按钮；默认配置及不支持按钮的客户端始终
  保留数字文字选择。真实 AppID 的按钮权限和客户端呈现仍须在 Phase 7 外部验收。

- QQ Official 账号生命周期现区分 `starting`、`ready`、`reconnecting`、`degraded`、
  `failed` 与 `stopped`。启动线程不再冒充健康；只有 SDK 收到 `READY` 或成功恢复会话后
  才解除账号启动等待。TOML 可逐账号声明 `required`，必需账号失败通过资源生命周期阻止
  应用启动，可选账号则保留为 degraded 并继续恢复；关闭会等待所有已启动 SDK WebSocket。

- QQ Official 入站可靠性不再只依赖 SDK 的 5 分钟内存集合。IronsBot 在业务分发前通过
  共享 SQLite 边界持久化占用 `AppID + event type + message ID`，跨 Resume、并发重投和
  进程重启均只允许一个调用进入 portable router；记录按 24 小时窗口清理，不新增配置。

- QQ Official 图片发送已改用 SDK 1.2.2 的正式 `MediaUploader`。URL 由腾讯服务端拉取，
  二进制渲染结果通过短生命周期临时文件进入 SDK 分片上传，不再整体 Base64 编码；群聊
  与 C2C scope 原样传给 SDK。高层 SDK 不返回 TTL，因此 `file_info` 只立即使用一次而不
  猜测缓存；图片超限和每日额度耗尽会降级为文字，其他异常仍进入结构化投递失败路径。

- QQ Official 多账号运行面由提交 `4de228dd` 完成：TOML 以账号别名声明多个
  AppID，每个账号从独立环境变量读取 AppSecret；bootstrap 为每个启用账号注册连接，
  feature 默认值、超级管理员、OpenID policy、主动消息资格和回复序号均按 AppID
  隔离。出站目标缺少或携带未知 AppID 时明确拒绝，不保留默认账号回退。审计安装的
  `nonebot-adapter-qq 1.7.2` 后确认 AccessToken、过期时间、会话和事件序号均为 Bot
  实例状态。公共全量 `3340 passed, 7 skipped`，Ruff、BasedPyright、compileall 和
  diff 检查通过；私有预览 workflow `34777514033` 完成构建、smoke、体积门禁和发布。
  见 [多账号隔离 Spec](specs/2026-09-14-qq-official-multi-account.md)。真实 AppID
  登录与平台主动消息权限仍是 Phase 7 外部验收门，整体保持 7/8。

- QQ Official 的低风险运维查询由提交 `fce42217` 接入公共 portable router：
  `server_status.query`、`server_status.admin_query`、
  `server_status.headless_instances` 和配置型 `meeting` 直接复用既有领域服务。
  命令目录继续负责按账号 feature、会话范围和 superuser 身份筛选；OneBot 处理器
  没有复制进官方适配器。数据同步、Docker 生命周期和榜单缓存维护仍未开放，因为
  它们还需要平台中立的进度投递及更强的运维授权。专项 12 passed，公共全量
  `3346 passed, 7 skipped`，Ruff、BasedPyright、compileall 和 diff 检查通过；无
  新运行依赖，portable 主路由为 712 行。见
  [运维查询 Spec](specs/2026-09-14-portable-operational-queries.md)。真实平台验收门
  未变化，整体保持 7/8。

- QQ Official 的精灵配置图查询由提交 `dedb2799` 接入：目录、精灵/别名解析、
  重名数字菜单、缺图提示和二进制图片发送分别复用现有 command contract、
  `PetConfigQueryService`、portable query session 与 outbound message，不复制 OneBot
  会话实现；固定图片口令仍由同一保留词集合消歧。专项 9 passed，公共全量
  `3350 passed, 7 skipped`，Ruff、BasedPyright、compileall 和 diff 检查通过；无
  新运行依赖，portable 主路由为 730 行。见
  [精灵配置查询 Spec](specs/2026-09-14-portable-pet-config.md)。B站账户与推送模式
  尚依赖 OneBot 配置目标，未向 OpenID 平台暴露不完整入口；整体保持 7/8。

- QQ Official 的只读榜单诊断由提交 `c5dae5d0` 接入：`/样本情况`、
  `/榜单情况` 和 `/榜单情况 <榜名>` 复用 `RankAdminService` 与既有榜名 parser，
  catalog 按 AppID 隔离的 superuser 权限拦截普通成员。刷新、批量缓存和群显示条数
  未混入该只读切片。专项 13 passed，公共全量 `3352 passed, 7 skipped`，Ruff、
  BasedPyright、compileall 和 diff 检查通过；无新依赖、配置或数据库迁移，portable
  主路由为 739 行。见
  [榜单状态 Spec](specs/2026-09-14-portable-rank-status.md)。整体保持 7/8。

- 本轮用户明确要求 pull 后，干净的主检出目录执行 `git pull --ff-only origin main`，
  从 `ba08f749` 快进到 `55a39fd1`，未合并入 V5。新增 10 项提交涉及战队查询与
  玩家菜单、私聊战队概览、群星牌觉醒变体合并、推送队列加固、Docker 交接失败
  恢复、B站抽奖/中奖订阅拆分、技能预览筛选和模块拆分。已检查日志、变更文件和
  部分配置差异，尚未完成逐项行为审计或移植，不能视为 V5 已获得这些能力。
- QQ Official 首个真实 MVP 已由提交 `d5b50c36` 接入：配置凭据从环境变量注入，
  默认 driver 在启用时增加 WebSocket 客户端，事件转换保留 group/member OpenID，
  平台渲染支持文本、远程图片和二进制图片，引用回复按全局规则忽略。平台中立路由
  复用 About 与 Seer 数据服务，首批开放帮助、关于、数据版本、赛季倒计时和下周预告。
  QQ 官方 bootstrap、事件身份、权限过滤和图片消息段有专项测试；公共全量回归为
  3259 passed、7 skipped，Ruff、BasedPyright、compileall 与 diff 检查通过。
  代码已推送到独立私有预览仓库；尚未使用真实 AppID 建立线上连接，因此 Phase 7
  保持 `in_progress`，不得把适配器注册等同于平台实机验收或全部功能可用。
- QQ Official 依赖升级到 `nonebot-adapter-qq 1.7.2`。该发布的元数据仍保留过旧的
  `yarl` 下限和 `cryptography <49` 上限；项目显式要求 `yarl 1.23+`，并使用 uv
  override 固定到已修复已知漏洞的 `cryptography 50.x`。适配器导入、Ed25519
  签名验证、启动和依赖审计都必须通过后才允许发布预览镜像。
- 私有预览流水线 `34759853590` 已完成冻结依赖审计、Linux 候选构建、无网络启动
  smoke、分目录体积门禁、基线增长检查和 GHCR 发布。镜像 digest 为
  `sha256:5b71257be5c4116ee7e0f61c8e1f85a2515fd445166bd3ca97c1dca1c20a561a`，
  Docker 报告大小为 246.19 MiB；其中 `/app` 4.16 MiB、site-packages 102.47 MiB、
  字体 19.00 MiB。真实 AppID 连接仍未验收。
- QQ Official 适配器现为 `qq-official` 可选运行组件。标准 OneBot 安装不再携带
  适配器及其约 14.55 MiB 的 `cryptography` 目录；官方预览仓库通过
  `IRONSBOT_RUNTIME_EXTRA=qq-official` 构建同一 Dockerfile。基础环境已在移除该
  extra 后验证应用组合模块可导入；准确的标准 Linux 镜像差额仍以后续标准发布
  产物为准，不把目录差额冒充压缩镜像差额。
- 前次只读观察的本地 `main` 为 `ba08f749`。从 `4b82881b` 起新增 11 个提交：
  B站 Opus/专栏正文补全、图片合并与历史摘要持久化，巅峰池有效期/投票展示，
  当前 fork 的页脚链接，自发指令超级管理员权限，以及橱窗别名候选昵称。
  当前 fork 页脚链接现已通过构建元数据迁入；其余项目仍按各自边界处理。
  迁入时分别归属 HTTP integration、内容/投递 service、历史 repository、渲染
  view model、平台身份权限边界和玩家引用服务，不能复制旧插件内部依赖。
  `4b82881b` 的消息数组配置同样仍待独立迁入，不能误认为已在 V5 生效。
  Docker 差异仅新增项目链接构建参数与环境变量；本机 Linux 引擎不可连接，
  尚无实际镜像尺寸证据。
- 先前只读观察的本地 `main` 为 `d8c5c7ee`（下列早期拉取记录保留其当时状态）。
  `d15c02f8` 撤销背包徽标变更，与 `963a83c3` 的净差异为空；随后 `dbcfb241`
  修正大师池测试注解，`d8c5c7ee` 增加固定口令分条回复。仅查看，未 fetch、pull、
  合并或移植；分条回复需单独验证配置互斥、顺序和平台中立投递。
  大师池与每周竞技点变化现已按目标边界迁入：seerapi 直接复用既有
  `peak_cost_pool` / `pet.peak_cost_pool_id` 事实发布周变化，IronsBot repository
  提供脱离会话的池快照，命令接入当前 catalog；新增内容统一走 immutable render
  document。没有恢复 main 中的 renderer 数据访问、旧分类推断或额外二进制解析。
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
这证明消费者不会用不完整 manifest 缓存图片。该次审计曾把补齐这些资源作为
Phase 4 完成门；按 2026-09-12 用户确认的职责边界，此要求已被下方消费者验收门
替代。缺图补齐归 SeerAPI 发布侧；不得放宽缓存准入或恢复 `main` fallback。

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
| Phase 4 | `completed` | repository/snapshot/presenter/renderer 边界、请求级 L3、素材范围与版本、缺图/失败恢复/不完整禁缓存、七类真实候选库消费，以及最终 schema 清单与 DDL 指纹的生产和消费校验均已验收 | 后续渲染器复用同一发布事实、素材和缓存契约；新增表先扩展 SeerAPI 最终发布契约 | 官方全部缺失素材已补齐或线上 release 已发布 |
| Phase 5 | `completed` | 统一解析、目录/安装规则交叉矩阵、私有 manifest 联合装配，以及真实详情服务到会话的成功/部分失败/取消/缓存时间均已验收；整体审计与全量回归见本阶段记录 | 后续入口沿用唯一 resolver/catalog/outbound；真实平台投递留在 Phase 7 | 所有平台 API 已支持 QQ 身份操作或生产发布已完成 |
| Phase 6 | `completed` | 配置严格拒绝旧字段；发布 schema、表清单、DDL 指纹、各领域事实和错误语义均已收口；宽异常审计与架构守卫防止数据库故障退化为空结果 | 后续发布字段沿用严格标量和 `PublishedDataIncompleteError` 契约 | 所有外部网络和业务部分结果都必须禁止 |
| Phase 7 | `completed` | 公开 `ae186314` 已部署；主要查询、权限、AI 主/备切换、群主动推送唯一归属、五账号路由、官方优先与 NapCat 静默均有真实证据；用户已在手机 QQ 确认合并提及、换行和正文不重复，里程碑为 8/8 | C8 腾讯自然拒收/额度事件保留为非阻塞 External TODO；发生后补录真实证据 | 把未发生的腾讯拒绝事件写成已通过，或以模拟结果冒充腾讯真实拒绝事件 |

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
load validator。SeerAPI 在内存替换前必须证明存在 `api_metadata`、`seerapi_metadata`，且
`seerapi_schema_contract_version` 等于消费者支持的版本；失败时保留旧内存库和旧本地文件，
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

**发布元数据投影边界（2026-08-15）：** SeerAPI `9d197bd` 将 `seerapi_metadata` 的
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

**B站历史详情渲染收口（2026-09-13）：** 历史动态选择与主动推送共用
`services.bilibili.outbound_delivery` 的平台无关文本、图片和完整内容渲染；OneBot
插件只把 `OutboundMessage` 编码为协议消息。删除 OneBot 专用 B站渲染模块以及穿过
`ApplicationResources` 的渲染回调。B站源图片属于动态内容 URL，继续使用
`RemoteImagePart`，不混入版本化的 SeerAPI 素材清单。

**Seer 图片源封口（2026-09-13）：** 通用 `SeerImageSource` 删除无人调用的可变
`preview` 分支，现在所有合法 kind 都必须由当前 SeerAPI 发布素材清单解析到固定仓库
revision。每周预告仍由独立的短 TTL、条件请求和陈旧缓存源处理，不与版本化渲染素材
共用身份或缓存。

**Seer 小型数据查询端口（2026-09-13）：** 周预告链接、数据生成时间和巅峰赛季时间
由 `PublishedDataQueryRepository` 从发布库读取，再以 `SeerDataQueryFacts` 领域值交给
service；`SeerDataQueryService` 不再导入 SQL/ORM repository 函数。服务层允许引用
`integrations.seer_data` 的规则同时从整包前缀收紧为现存模块精确过渡清单，新增反向依赖
会被架构测试拒绝。

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

**七类消费矩阵与远端发布门（2026-09-12）：** 在同一 opt-in 验收测试中补齐
巅峰投票、巅峰精灵榜和私有阵容，连同属性、竞技池、专家池、精灵资料共七类。
使用 SeerAPI 当前分支实际构建的候选库、固定素材 revision 和真实 HTTP/原生渲染，
七项均完成 SQL、PNG 像素、素材复用、OneBot 编码及受限平台图片投递验证：
`7 passed`（72.36 秒）。公共全量 `3110 passed, 7 skipped`，其中七项只因默认不提供
发布库环境变量而跳过；私有全量 `43 passed`，生产端全量 `308 passed`，生产端
manifest 契约专项 `2 passed`。运行时 SWF 转换、renderer 数据库访问和文本关联猜测
的架构守卫无豁免并随全量测试通过。

随后只读下载实际远端 `seerapi-data-latest`（123744256 bytes），SHA-256 与发布指纹
一致。消费端在加载阶段明确拒绝：期望 schema 契约版本 `1`，远端实际未发布该元数据。
这证明旧远端文件不会被误当成 V5 数据，同时也说明远端发布门尚未完成。不得加入旧
schema 兼容或降低校验来绕过；待 SeerAPI 发布新契约库后，用同一七类测试复验即可。
因此 Phase 4 仍为 `in_progress`，总进度保持 5/8。

**真实发布消费与批量读库（2026-09-12）：** 扩展已有 opt-in 发布测试为属性图、
竞技池、专家池和萨尔蒙（3549）资料图，共享同一初始化/HTTP/缓存/出站验收流程，
不另建测试模块或素材副本。使用未修改的 SeerAPI 本地产物
`tmp/v5-release-acceptance-fixed/seerapi-data.sqlite`（seerapi 仓库，58413056 bytes），
manifest `3bcee795c7d4e7ffb10f32d11478212b984bd705785e0fddced6c1c67bfae13a`、
素材 revision `1b53a16cfe32d36d921a04fbd8423116c5b1e2e1`。四项真实 SQL、HTTP PNG、
原生渲染及 OneBot 编码/fake official 上传验证通过（45.11 秒）；不是线上 QQ 投递。

实测初次 SQL/HTTP/原生调用：属性 `(3,138,1)`，竞技池 `(37,71,1)`，专家池
`(33,65,1)`，萨尔蒙 `(108,9,1)`。产物只授予 type_matchup 完整缓存资格，所以
属性二次查询三个计数均不增长；其余三项二次查询复用素材但重新读库/渲染，未篡改
完整性声明。不能将“该样例能出图”推导为全类别完整。萨尔蒙已出图并核对官方
533/534/535 三条效果事实；运行时未补造关联。

由上述 SQL 计数定位 peak repository 的关系逐项加载：三种池统一使用 selectinload
批量取成员，精灵快照直接使用自身 type_id。真实竞技池从 37 次、专家池从 33 次降为
各 2 次 SQL；下载与原生次数不变。5 池 fixture 先复现 11 次查询，修复后均为 2 次，
按 ID 读取精灵从 2 次降为 1 次。未引入额外缓存、schema 或运行模块。
优化前后竞技池 1228x1022、专家池 1228x702 的 RGB 像素差为零。

最终公共相关回归 112 passed、4 skipped（四项 opt-in 已单独验证，优化后的两个池
再次 2 passed），私有全量 43 passed；Ruff、BasedPyright、compileall/diff 通过。
调用命令为 `pytest tests/test_seer_type_query_service.py -k native_published`，需设置
`IRONSBOT_RENDER_RELEASE`；Windows 本轮还设置 `IRONSBOT_RENDER_FONTCONFIG`。
本批没有全量 pytest、远程发布、Docker 构建或真实账号联调，不将它们标为已验证。
剩余渲染类别与发布边界继续按本阶段原始条件验收，总进度保持 5/8。

**巅峰图片消费与恢复（2026-09-12）：** 竞技池、投票、精灵榜统一使用
`_render_peak_result` 处理预期素材失败/渲染超时；删除投票独有的 45 秒计时器和
`except Exception`，原生时限复用现有 `RenderCoordinator`。代码错误和取消继续
向上传播；无数据库会话跨越渲染 await。Python 3.10 的 asyncio 超时类型也覆盖，
未改变网络请求时限。先复现 6 个错误分支，再验证三入口失败后可重新查询。

同一测试矩阵覆盖 pool/vote/rank、HTTP 404/503/ReadTimeout、发布类别完整/不完整，
共 18 组；真实 `HttpSeerImageSource`、`SeerAssetStore`、`FileRenderCache` 与协调器
组合验证失败不写最终缓存、恢复重新获取、完整结果第二次不再 HTTP/原生渲染，
不完整类别只复用素材、不写完整图缓存。负缓存 TTL 在测试中置零以验证恢复。
HTTP 用固定 revision URL 和合成 PNG，默认 HTML 为替身；显式设置
`IRONSBOT_NATIVE_RENDER_TESTS=1` 后本轮已通过真实 HTML/PIL 像素检查，并目视确认
三种模板的标题、精灵名称、票数/场次与时间布局。不是实际官方图标或真实 release
全链路验收。首次原生测试的 NoneBot 初始化顺序错误已修正测试装配。

原生矩阵及相关测试 87 passed；最终相关回归含导入检查 90 passed，隔离 Python 3.10
环境 60 passed。全量 Ruff、BasedPyright、compileall/diff 通过；本批未重复全量 pytest。
生产文件净减 4 行，不新增模块、依赖、配置或素材文件。真实发布物消费和其他渲染
类别的整体验收继续开放，总进度仍为 5/8；未 pull/merge/push 或改生产环境。

**目标契约：** `repository -> immutable snapshot -> presenter -> RenderDocument -> renderer`
以及统一 `AssetStore` / `RenderCoordinator`。

**唯一目标路径：** `seerapi` 在构建期发布确定性事实、关系和 PNG 资产；IronsBot
repository 准备快照，renderer 不读 SQL/HTTP/文件系统、不猜关联、不做 SWF 转换。

**完成条件：**

- 资产 cache、最终图片 cache、singleflight、并发、完整性和超时策略集中实现；
- renderer 在首次 `await` 前已不持有 DB session；
- 宠物、属性、竞技池、排行、投票和阵容逐项迁移并有快照/像素/缓存测试；
- release schema、所需表、素材范围和版本绑定在构建端与消费端均验证；
- 消费者验证正常 PNG、缺图降级、下载失败与恢复，以及不完整结果不写完整缓存。
  不要求官方全部素材齐全；上游素材缺口单独由 SeerAPI 处理。

**职责边界确认（2026-09-12）：** 官方图标采集、SWF 转 PNG 和素材发布属于
SeerAPI。机器人通过发布事实取得 PNG 对应关系，复用素材下载缓存并排版最终回复图。
不得为了收尾在机器人新增资源采集或转换。以上调整替代历史记录中“补齐全部缺图
才能关闭 Phase 4”的要求，不追溯改写测试结果，也不自动将阶段标为完成。
仍需逐类证明消费路径和缓存行为；新产物只需满足明确的 schema 与素材可用状态契约，
不能把缺图伪报为完整。Phase 5 已并行进行，4/8 表示四个已验收阶段，不是它尚未开始。

**删除条件：** 运行时 SWF 转换、renderer 数据库读取和文本关联猜测全部删除。

**Phase 4 关闭审计（2026-09-12）：** SeerAPI `95cd80b` 在新内容索引和 Flash 坐骑
后处理完成后运行最终发布验收：当前 SQLModel 表与构建期生成表共同定义唯一生产端
必需集合，先执行 `PRAGMA integrity_check`，再写入有序物理表清单以及表、索引、触发器
DDL 指纹。IronsBot 在内存原子换版前验证契约版本、稳定最小表、全部声明表和复算指纹；
清单损坏、指纹损坏、声明表被删除或列定义变化均不会替换当前有效快照。消费端不复制
完整 151 表名单，避免生产 schema 演进形成第二权威。

完整后处理候选库验收为 151 表、`integrity_check=ok`，schema 指纹
`f0bbb8302368b62c6dbac946bec2d0c0f3e9a49d086b33ad612b59ad03b2444b`；此前同一候选库
七类真实消费 `7 passed`，覆盖属性、竞技池、专家池、精灵资料、投票、精灵榜和私有
阵容。本次最终契约专项生产端 `3 passed`、消费端 `21 passed`；SeerAPI 全量首轮
`310 passed`，唯一 GitHub 下载连接中断项单独重跑通过。更新指纹后的真实属性消费已
通过数据库装载并进入素材下载，随后因 GitHub 连接断开停止；这不属于 schema 契约失败，
正常 PNG 和恢复行为由此前七类矩阵覆盖。Ruff、BasedPyright、compileall 和 diff 检查
通过。36 个官方 Flash 坐骑 URL 返回 404 继续保留为生产端 pending，不伪报完整，也不
作为消费阶段门。Phase 4 据此标为 `completed`；没有 push、线上 release 或真实 QQ 投递。

**消费端素材失败回复（2026-09-12）：** 精灵资料查询将 `ImageSourceError` 转为
明确的素材获取失败回复，保留精灵名称/ID 并标记 `complete=False`。头像/立绘缺失
仍不调用原生渲染、不写完整缓存；不在机器人补造素材。按名称查询与菜单选中均覆盖
404 和下载超时后的回复、恢复再次出图；非素材渲染异常仍向上传播，避免隐藏代码错误。
查询/适配器测试 18 passed，定向类型检查通过。此证据只覆盖精灵路径，不替代其他
渲染类别验收，不将 Phase 4 自动标为完成。

**对照 main 图片获取（2026-09-12）：** 只读本地 main `55a39fd1`，没有拉取或
合并。已复用其本地缺图占位实现，删除重构分支的第三方 dummyimage 请求；仅显式
允许 fallback 的调用可使用占位图，严格渲染仍失败、不缓存占位并允许恢复重试。
图片源/素材缓存 17 passed。另一个尚未解决的差异是 main 的官方 HTTP PNG 优先、
资源仓库备用，与当前固定 revision 图片缓存契约不同；不得声称二者已完全等价，
也不得把可变来源内容直接写进固定发布版本的完整缓存。未增加内置素材或新依赖。

**占位与素材缓存分离（2026-09-12）：** 现有 `PreparedImageRequest` 将正式下载与
展示 fallback 分开；共享素材库只保存正式下载结果。严格/允许占位的调用共用同一
正式素材键，失败后分别抛错或返回本地占位。键版本更新，避免复用旧占位条目；不新增
数据库或缓存目录。404/410 仍使用短期负缓存，临时失败不负缓存；恢复测试将负缓存
TTL 设为零以验证再次下载。三类 HTTP 失败、恢复、严格精灵适配器共 23 passed，
定向 Ruff/类型检查及 diff 检查通过。该修复不改变上游资源地址优先级。

**共享图片改动回归（2026-09-12，44837390）：** 公共全量 2931 passed、1 skipped
（真实发布测试需环境变量启用）、319 条既有警告；全量 Ruff/BasedPyright 通过。
私有扩展使用该公共工作树运行，43 passed。单独启用真实发布测试：第一次在素材
下载阶段失败；不改代码、使用新空缓存目录重试后 1 passed（13.93 秒）。实际
属性图为 848x3453 PNG，已目视检查；测试同时验证二次命中不新增 SQL、HTTP 或原生
渲染。两次结果均保留，不能把重试成功解释为网络稳定性已解决。未更改 main、未
发布、未测量 Docker 镜像；其他类别真实发布验收和官方源优先策略仍待处理。

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
- 新增内容发布索引和赛季时间分别由
  `integrations.seer_data.new_content_repository` 与 `season_repository` 提供。
  Flash 座驾 PNG 已由 SeerAPI 构建期发布，运行时统一通过 `SeerImageSource` 的
  `mount` 类型获取；不得恢复 SQLite Blob repository、运行时 SWF 或专用图片缓存。
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

属性克制表已将快照边界前移到数据集读取之前：服务收到绑定 reader/renderer
会话，查询、纯计算、素材与缓存由同一发布记录驱动。直接查询、候选选择、自定义
双属性以及成功/错误/取消的组合均验证 SQL 查询已关闭而渲染快照仍有效，退出后
释放；全局空数据集与绑定有效数据集用于发现误读全局数据。相关回归 28 passed，
Ruff、定向类型、compileall/diff 通过，属性服务净减少 9 行，无新增模块、依赖或
配置。巅峰、新内容和私有阵容等入口仍待迁移；整体仍为 4/8。

巅峰池、投票、精灵榜已复用 `SeerRenderSessions`：读取赛季/候选资料、联网、
进度提示到渲染都持有同一快照，每次 SQL 查询仍独立结束。精灵榜联网后的资料
读取改走同一个 reader 下的 repository，不再回到全局 `get_many`。删除原有三个
独立 render 构造参数和无绑定的精灵映射辅助函数。相关功能与架构回归 54 passed
（2 条已有 ORM 警告），包含成功/错误/取消、原投票渲染超时释放和真实 SQLite
筛选/脱离会话读取验证；Ruff、定向类型、compileall/diff 通过。线上榜单数值仍为
实时观测，不宣称它属于静态发布快照。无新增模块、依赖或 TOML；新内容、橱窗、
私有阵容仍待迁移，总计仍为 4/8。

橱窗渲染已复用同一发布快照装配，固定报价/名称/顺序/关注状态作为请求输入，
图片映射与下载使用绑定 reader/source。适配器只接收 `SeerDataReader` 和通用
HTML callable，不再要求完整查询接口与具体 coordinator 对象。相关回归
42 passed（44 条已有 NoneBot 弃用警告、2 条 ORM 警告），Ruff、定向类型、
compileall/diff 通过。完整皮肤素材范围仍未验收，未启用橱窗最终缓存；未改 TOML、
依赖或私有扩展。新内容菜单多轮交互与私有阵容快照仍待处理，总计仍为 4/8。

新增内容单次渲染已接入共享发布快照，资料准备、群星牌和座驾读取收窄为
`SeerDataReader`，不再通过全局 getter 查询。渲染前比对保留菜单的完整索引，
同版本号的条目修正也能被识别；不一致时保留文本菜单，不拼接新旧资料图片。
菜单本身一直持有实体 ID，问题不是序号漂移。相关回归 46 passed（2 条已有 ORM
警告），Ruff、定向类型、compileall/diff 通过。无新增模块、依赖或 TOML。
多轮选择后的详情查询仍使用当前领域服务，缺失资料的最终缓存准入仍待完善；
不宣称整段会话已完成快照化，整体仍为 4/8。

新增内容详情分类分发移入平台无关 `NewContentDetailService`，复用直接命令的
精灵/刻印/装备/群星牌服务实例；插件只处理选择和发送，移除五个 `Any` 字段。
已验证十二类内容的参数/结果、缺失消息、取消与异常传播，相关回归 62 passed，
Ruff、定向类型、compileall/diff 通过。插件净减 64 行、生产代码总计净减 7 行，
未新增文件/依赖/TOML。详情版本绑定仍待下一步接入，不能将业务迁移当作快照验收；
整体保持 4/8。

新增内容详情已采用统一失效策略：先验证条目属于旧菜单，再核对完整索引；
查询前后通过实际引擎身份判断是否换版。换版时丢弃本次详情并结束旧菜单，明确提示
重新发送指令，不持有跨用户等待的数据库租约，也不按分类增加补丁。72 项菜单、
数据库与架构回归通过（2 条已有 ORM 警告），包括同版本重载、回滚、关闭快照及
失效后禁止发送结果；Ruff、定向类型、compileall/diff 通过。此为数据库代际失效
策略，不宣称所有领域服务和远端卡牌图片均已不可变绑定。无新增文件/依赖/TOML。
私有阵容、资料缺失缓存准入和真实素材/平台验收仍待完成，整体保持 4/8。

新增内容缓存准入现已区分占位资料与完整资料，缺失数据库行、查询失败、未解析的
必要资源或属性图标均不写最终缓存；合法空效果和索引自带说明仍可正常使用。
菜单键改用完整索引的现有规范化哈希，同版本内容修正不再复用旧图。相关回归
114 passed，补充读取失败恢复后渲染测试 39 passed，Ruff、定向类型、compileall/
diff 通过；真实 FileRenderCache 验证临时图、恢复重绘、后续命中的过程。未增加
模块/依赖/TOML，移除未使用的资源辅助参数。此项不替代真实素材和像素验收，
私有阵容绑定与平台验收仍未完成，整体保持 4/8。

**私有阵容发布会话（2026-09-12）：** 公共扩展改为提供单一渲染会话工厂，
条目读取、素材和最终图片缓存绑定同一发布代次；私有服务在封包完成后打开会话，
跨渲染等待持有租约，异常和取消均释放。删除旧全局条目/渲染字段及不再使用的
composition 导出，不加兼容包装。另修复超时参数的位置调用与私有关键字签名不匹配。
公共 35 项发布/时间测试、41 项扩展/架构测试、私有 29 项通过；两仓库 Ruff、
compileall、diff 和目标类型检查通过。详见资产 singleflight Spec。
两仓库需配套发布；缺失事实的缓存准入、真实图片及部署验收未完成，仍为 4/8。

**阵容完整性准入（2026-09-12）：** 发布快照携带资料完整性，缺失精灵不再用
精灵 ID 猜头像资源。私有渲染结果携带完整性，缺资料/头像/属性图标时允许展示并
提示，但不读写不完整最终缓存，也不覆盖玩家历史完整回复。合法空阵容仍可缓存。
公共 34 项、私有 41 项通过，目标类型检查、Ruff、compileall 通过；没有新增模块、
依赖、数据库或 TOML。旧历史回复不追溯认证，真实图片与部署验收仍未完成，仍为 4/8。

**阵容原生图片验收（2026-09-12）：** 使用真实发布数据的六只精灵及固定官方素材
revision 做离线原生渲染，修复空位/缺图造成行高变化，三种结果统一为 490×704。
目视确认头像、属性、等级及限用标记；加入独立进程的原生尺寸回归，私有 42 项通过。
但该下载 release 缺少 V5 schema 契约标记，生产加载器正确拒绝它；离线检查未修改
数据库或绕过生产校验，不能充当部署验收。后续先构建带契约和素材清单的 producer
产物，再验收正常发布入口。Windows 默认字体发现及 Linux 渲染也仍待验证，仍为 4/8。

**真实 producer 到运行时验收（2026-09-12）：** V5 seerapi 从真实网络来源完成本地
构建，55.71 MiB 产物带 schema=1/asset=2 契约，通过未修改的公共加载器。
同一真实产物经 SeerRenderSessions 完成三种阵容原生图片，均为 490×704。
仅 type_matchup 素材范围完整；缺失头像等导致阵容/精灵/新增内容最终缓存仍禁用。
本机缺 FFDec 触发整批 Unity 回退，2108 张可用、4 张缺失，不代表原 Flash 保真验收。
后续优先修复单个未缓存图标导致整批 Flash 缓存被丢弃的路径，再补资源/全渲染器
及部署验收。产物 hash、命令与资源缺口见资产 Spec；未发布、未合并 main，仍为 4/8。

**Flash 回退隔离（2026-09-12）：** seerapi 删除整批工具预检及重复缓存扫描，
缺 Java/FFDec 只使该未缓存图标失败，保留有效 Flash PNG；Unity 只接收缺失项。
合并来源后才执行严格完整性检查，独立缓存构建仍保留原校验；复用来源模块的
准确回调类型。88 项构建/元数据测试及目标类型、Ruff、compileall 通过。
修复后的真实网络构建尚未重跑，上一条产物 hash 仍指修复前产物，阶段仍为 4/8。

**2026-09-12 / 渲染阶段回归检查点：** 属性查询缓存前移到服务入口，真实 SQLite
探针确认首次 6 条 SQL、命中 0 条；去掉适配器重复缓存和计算模型旧键。素材
singleflight 接入已有 TaskSpawner，停机由应用统一取消，保留单个等待者取消
不影响共享下载。公共全量 2833 passed（319 条已有警告）、私有 43 passed
（含原生渲染），全量类型、Ruff、编译与 diff 通过。私有镜像修复被忽略的
pyproject.toml 并保留许可证，但本机 Docker daemon 未运行，未宣称构建或
镜像体积验收通过。详见资产 singleflight 和 runtime image inventory 两份 Spec。
总阶段数仍为 4/8；剩余真实渲染覆盖、Flash 保真及平台部署验收继续开放。

**2026-09-12 / 同名效果与真实图片：** 生产者保留全部同名候选，使用官方已有关系
消歧，不再按首次命中取错词条；技能描述中的普通“恢复/免疫/吸取”不再被当成
技能引用。离线重算五张事实表、六只精灵原生图已完成，二郎神只保留自己的
法天象地。南霜的“不破诛罚”只有魂印正文，无独立官方词条，不造卡片或图标。
同一构建内复用技能引用扫描，99 项回归通过，完整事实重算 13.791 秒且优化前后
语义行完全一致。详细证据与限制见资产 Spec；未发布、未完成完整视觉及平台验收，
总进度仍为 4/8。

**2026-09-12 / 巅峰图片验收：** 真实池配置生成竞技/专家池图片，真实精灵素材配合
明确标注的离线票数和场次生成投票/精灵榜图片。发现并修复精灵榜时间字段遗漏：
响应完成即捕获获取时间，经纯模型进入模板和缓存键，标题与时间分行避免原生渲染
重叠。39 项定向回归、类型、Ruff、编译通过。未查询真实游戏账号，不能把离线
动态样例算成游戏接口验收；阶段维持 4/8。

**2026-09-12 / 运行依赖收口检查点：** 删除未使用的 `seerapi` HTTP 客户端依赖，
保留 `seerapi-models` 与发布数据库 repository；锁文件仅移除该包。实际离线同步
后确认该包不可导入，公共全量 2834 passed（319 条已有警告）、私有原生渲染测试
43 passed、独立架构测试 19 passed，全量类型、Ruff、编译通过。移除包仅约 14 KB
压缩 wheel，不宣称镜像大幅缩小；真实 Docker 体积与部署验收仍未完成。总进度 4/8。

### Phase 5 — 业务服务和通用解析

**整体关闭审计（2026-09-12）：** `completed`。逐项复核上述阶段原始范围，未以
接口声明或单项测试代替组合验收；本次只关闭 Phase 5，不关闭整个重构。

| 原始完成条件 | 当前实现与验证证据 |
| --- | --- |
| AI 目录认领，无第二份保护词 | AI `_capture_ai_prompt` 调用 `CommandCatalog.claims_direct_input`；player/rank/exact/affix/subscription/sendpic ownership 测试覆盖实际 AI rule 与目录/安装入口。旧 `RESERVED_PRIVATE_COMMANDS`、`DEFAULT_POKE_HINTS`、`_RANK_HINTS` 全生产目录检索无结果 |
| 统一米米号参数 | `app/seer_composition.py` 是生产中唯一 `PlayerIdResolver` 构造位置；基础、绑定、快捷和榜单玩家入口复用 `resolve_player_target`。96 组实际 Rule 矩阵与 24 组真实工厂/目录准入、既有绑定处理器和引用隔离测试通过；私有 `8c9c8f2` 验证真实 manifest 注册的阵容动作进入同一公开入口 |
| 多分区独立失败、渐进回发 | scheduler 验证一个榜耗尽不影响另一个榜、同页重试；真实 `PlayerDetailService` 到菜单发送覆盖收集/巅峰成功、部分超时和取消，完成项仍回发、取消不向旧菜单发送、失败不误报未上榜 |
| 来源与缓存时间 | observation/freshness 测试覆盖旧源、未知时间、超时缓存；详情到发送组合保留原观测时间，成功复用不再请求，部分结果不进入完整缓存。源时间不是组装回复时的当前时间 |
| 删除重复解析和出站规则 | 入口只做 OneBot 输入适配；玩家/榜单/私有动作共用 resolver 与命令契约，实体存储通过 `AliasIndex` 或 `DatabaseAliasLookup` 共享结果协议。玩家普通和扩展回复统一 `QueryReply.to_outbound()`，不恢复专用数字正则或消息包装器 |

最终公共全量 **3077 passed、1 skipped**（127.03 秒），私有全量 **43 passed**；
公共 Ruff、BasedPyright（0 errors）、compileall 和 diff 检查通过。首次全量发现
私有详情旧测试仍断言字符串，已改为严格比较统一出站后的 `Message("private reply")`，
没有放宽为任意文本或修改生产行为。3568 个警告来自 NoneBot ForwardRef 弃用和
模型关系声明，不宣称无警告；跳过项是需显式发布物的原生渲染测试，属于 Phase 4。

此前收尾表中的两个安装组合门已由公开工厂矩阵和私有 manifest 联合验收补齐。
QQ API 不支持的身份操作按用户要求留到最终平台适配；真实 QQ 投递、素材消费验收、
错误语义清理与发布分别仍在 Phase 7、4、6 及发布流程中，不因本阶段关闭而略过。
本地 main 为 `55a39fd1`，producer 为 `8a38945`，本轮没有 pull/merge/push，未改
生产配置、数据库、依赖或镜像资源；私有未跟踪 `uv.lock` 保留。

**玩家图文出口复用（2026-09-12）：** target 收口。快捷查询、数字菜单及详情扩展
统一调用现有 `QueryReply.to_outbound()` 和 OneBot message renderer；删除
`_build_shortcut_reply_message`、`_query_reply_message`、`_reply_text`，不新增包装器。
快捷查询不再丢弃只有 image_error 的失败说明，正文与图片错误共存时均按统一契约
交付。真实快捷处理器覆盖文本、仅错误、部分正文与错误、图文，并验证图片编码；
详情会话的真实服务/取消测试继续通过。公共相关 36 passed，私有 43 passed，
全量 Ruff、basedpyright、compileall 通过；生产两文件合计净减 18 行，无依赖或
配置变化。安装入口交叉验收尚未整体完成，不提前关闭 Phase 5；总进度 4/8。

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

**玩家事件适配复用（2026-09-12）：** 基础米米号与绑定入口改用已有
`resolve_player_target()`，与快捷查询、榜单玩家查询共用事件转换和缺少 resolver
时的错误处理，删除基础入口独有的 `_require_player_id_resolver`。普通查询仍允许
默认绑定，绑定命令仍要求显式目标；不改变领域 `PlayerIdResolver`、权限或存储。
目标解析、绑定和命令认领相关 84 passed，定向 Ruff/类型检查通过；没有新模块、
依赖或 TOML，不据此声明整个 Phase 5 完成。

**别名与成员混用的入口错误（2026-09-12）：** 先复现了“米米号示例玩家 + @成员”
解析器返回冲突、基础入口却返回未匹配的问题。入口现在复用 resolver 的当前用户/
会话别名可见性判断保留此错误，交由既有验证处理器发送；未知别名和普通自然语言
仍不认领。测试覆盖真实入口到错误发送，不只测试 resolver；相关 76 passed，
定向类型检查通过。不新增命令、别名名单、配置或模块。

**玩家命令前缀语法一致性（2026-09-12）：** 四项先失败测试确认目录删除内部
空格后会认领实际入口拒绝的“米 米号123456”“绑定 米米号123456”等输入。
通用玩家引用 matcher 改为只 trim/casefold 前后文本，不拼接命令或参数内部空白；
参数仍交给同一别名可见性接口。测试对照实际基础/绑定入口结果，公共相关 71 passed、
私有 43 passed，定向 Ruff/类型检查通过。未新增配置、语法别名或生产模块。

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

**Phase 5 收尾范围（2026-09-12 核对）：** 不再将已完成的命令目录、resolver 或
处理器测试笼统记作“参数解析未实现”。当前证据与剩余门分别如下：

| 要求 | 已存在的证据 | 尚需补齐的证据 |
| --- | --- | --- |
| AI 只按目录认领 | `test_player_reference_ownership`、各领域 ownership 测试实际调用目录/AI rule | 玩家完整安装入口与目录判断的交叉矩阵；不能只调用处理器 |
| 数字、别名、直接 @ | `test_seer_player_targets`、`test_seer_rank_player_input`、`test_seer_player_shortcut_input`；entry conversation 已测试绑定别名与 @，断言绑定对象是发起人 | 实际安装 matcher 的基础/绑定/快捷/榜单玩家入口，覆盖合法输入、混用、多 @、未绑定和引用排除；私有阵容复用公开入口也需纳入 |
| 多分区独立失败与回发 | scheduler 测试覆盖重试和单项耗尽不阻塞其他任务；真实 PlayerDetailService 到会话发送的组合覆盖收集/巅峰成功、部分超时和取消 | 本组合门已通过；真实 QQ 发送留到平台验收 |
| 缓存来源时间 | observation time、detail freshness、fallback cache 测试，以及上述组合测试验证实际发送正文保留最早来源时间、成功结果复用且部分结果拒绝入完整缓存 | 本组合门已通过；不将聚合获取时间误称为逐行独立时间 |

这两组剩余验证（安装入口矩阵、详情服务到会话的组合）是当前具体收尾任务；新发现
的问题必须附复现证据，不能仅用“其余领域”无限扩大范围。上游素材齐全和真实 QQ
发送不是本阶段参数解析门，分别归数据生产侧与平台部署验收。阶段仍未标为完成。

**平台能力延期（2026-09-12，用户确认）：** QQ 号、成员 @、绑定等操作若目标
平台 API 暂不支持，先跳过该平台的实现/联调，登记为最终平台适配待办，不阻塞
通用业务重构。不伪造身份、不通过跨平台 QQ 号猜测绑定，也不把跳过项标为已支持。
已支持的 OneBot 行为保留；不再为填满 QQ 专项矩阵反复扩展当前阶段范围。

**现有 OneBot 安装规则矩阵（2026-09-12）：** 将既有安装测试扩展到米米号、绑定、
收集、巅峰、群星牌和成就榜玩家入口，共 96 种功能开关与参数组合。通过各插件
`install()` 捕获实际 Rule，注册容器仍为替身；验证数字、别名、成员 @、机器人 @、
混合参数、多 @、未绑定成员和引用中的新命令。引用体另含未绑定成员 @，不会改变
新命令解析目标。现行 ARCHITECTURE 允许引用中的新指令，并非历史全局忽略规则，
最初 6 项失败源于测试预期错误，未修改生产行为。其余入口解析专项合计 152 passed，
追加引用体隔离后安装矩阵 96 passed；Ruff、类型检查通过。该证据不代表真正的
MatcherFactory/目录/私有扩展全链路已一次性安装验收，也不代表 QQ 官方 API 支持。
未新增生产代码、配置或依赖，总阶段计数保持 4/8。

**真实工厂与目录联合验收（2026-09-12）：** 在同一测试中使用实际
`MatcherFactory`、`SeerMatcherGroup` 和玩家/榜单领域目录，安装基础资料、绑定、
快捷查询与榜单模块。24 组数字/别名和功能开关输入验证目录认领与实际 Rule
一致，允许输入进一步执行工厂安装的准入 handler，确认 actor 传递；冷却服务和
业务资源为替身，不执行真实玩家查询。目录只收录本次安装的玩家和榜单命令，
并通过双向 matcher/帮助注册校验；未把未安装的精灵/活动命令伪装成已验收。
全部注册 matcher 在 finally 中销毁。首次失败为测试包含未安装命令、误取解绑
matcher，修正测试装配后 185 passed；Ruff、basedpyright 通过。该测试补齐公开
数字/别名路径的工厂交叉证据，私有扩展联合装载与平台联调仍独立，不据此关闭
整个 Phase 5 或新增生产兼容代码。总进度保持 4/8。

**私有 manifest 与公共入口联合验收（2026-09-12）：** 私有仓库 `8c9c8f2`
扩展既有独立进程 manifest 测试：实际 NoneBot 加载私有插件后，使用共享 resolver、
CommandCatalog、MatcherFactory 与 SeerMatcherGroup 安装公共玩家/快捷入口。
验证阵容数字/别名在功能启用与禁用时目录认领和规则一致；解析动作必须就是
manifest 注册进 PlayerDetailExtensionRegistry 的同一个对象，不伪造另一个阵容
入口。目录与 matcher 双向校验通过，注册 matcher 全部销毁。私有全量 43 passed，
定向 Ruff/diff 通过；无真实游戏查询/QQ 投递声明。运行代码、依赖、配置未变，
既有未跟踪 uv.lock 保留。至此上述公开数字/别名工厂和私有联合装载的具体证据
已补齐；仍须按 Phase 5 原始完成条件整体核对，不能自动推导全项目完成。

**已完成的绑定入口修复（2026-09-12）：** 通过 `player.install()` 收集真实 Rule
组合（注册容器使用替身）复现：绑定处理器支持成员 @，注册时却使用禁止成员 @ 的
策略。改为复用 `member_target_command()`。16 种基础/绑定、数字/别名/成员/机器人
及功能开关组合通过；连同已有处理器/目标测试共 87 passed，定向 Ruff/类型检查通过。
这不是目标平台 API 联调，也不是所有 QQ 入口矩阵完成；后续按上述延期边界推进。

**详情到会话组合验收（2026-09-12）：** target 验证，不新增生产接口。替换
`test_seer_player_detail_conversation_runtime` 中固定的 partial reply：调用真实
`PlayerDetailService`、分项进度恢复、格式化与缓存，再交到既有菜单会话发送边界。
游戏查询和榜单获取使用可控替身；榜单先记录第 4 名，再抛出 TimeoutError，证明
已完成结果不会丢失，未完成项不会伪报未上榜。收集/巅峰 × 成功/超时 × 保留/取消
共 8 种组合覆盖一次发送、取消不发送、来源时间保留、成功缓存复用与部分缓存拒绝。
这不是官方封包或真实 QQ 投递测试，调度器行为由原有专项测试独立覆盖。
组合、时间、调度和缓存专项共 45 passed；全量 Ruff、basedpyright、compileall
通过。本次未重复全量 pytest，无新增依赖、TOML 或运行镜像文件。只读确认本地
main 仍为 `55a39fd1`，未 pull/merge；总阶段计数保持 4/8。

**已有详情预算实现：** 已将 foreground/background 详情预算统一为一个单调时钟截止时间，基础、
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

**群星牌发布字段严格读取（2026-09-12）：** 群星牌卡牌、角色、属性和赛季场地
repository 不再把损坏的 JSON 对象或数字字段静默改成空记录/`0`。缺表、空发布和字段
格式损坏分别返回明确错误；合法的官方 `0` 保持原值。真实候选库的 580 张卡牌和
10 条属性记录已核对所需数字字段均为整数。群星牌、场地和新内容组合回归
`93 passed`，Ruff、BasedPyright 通过；无命令、TOML、schema、QQ 身份或展示变化。

**发布数字与载荷通用契约（2026-09-12）：** 将群星牌局部整数校验收口为
`core.value_coercion.require_int`，并复用于群星牌、圣域和新增内容快照。布尔值、
非整数浮点数、损坏字符串及错误结构不再被转换成 `0`、`未知` 或完整预览；合法的
整数、整数字符串和整数浮点表示保持原值。新增内容在准备不可变渲染输入时统一转换为
`PublishedDataIncompleteError`，不会进入 renderer 或写入完整图片缓存。该边界只校验
发布事实，不涉及 QQ 号、@、绑定或平台身份能力；相关平台项按最终平台阶段延期。

**属性关系缺失语义（2026-09-12）：** 删除属性克制计算中缺少官方关系时静默采用
`1.0` 的默认值。发布数据关系表不完整时现在抛出带攻击/防御属性 ID 的领域错误，
查询服务记录诊断并返回“属性克制数据不完整”；不调用 renderer，也不写最终图片
缓存。测试 fixture 改为显式完整关系，不再以空表暗中依赖旧默认。属性专项
`29 passed, 7 skipped`；真实候选发布库包含 26×26 共 676 条关系，七类矩阵首次
运行属性通过、专家池素材连接失败，恢复运行专家池通过、属性素材连接失败，互补
证明两条业务路径均可成功且外部下载失败保持可观察。本项无 schema、配置、依赖或
镜像内容变化。Phase 6 仍需审计其余数据库异常 fallback，进度保持 5/8。

**未知配置严格拒绝（2026-09-12）：** 删除加载器“先用严格模型收集未知字段、再以
`extra="ignore"` 重新加载并继续启动”的双重校验。TOML 现在只执行一次严格
`Settings.model_validate`；顶层、嵌套表和数组表中的未知字段均以原始配置路径报错，
已删除的 `change_cooldown_hours`、`query_worker` 等字段不再形成运行时兼容层。
同步修正文档中“模型禁止额外字段但加载器忽略它们”的矛盾描述。配置专项
`62 passed`，公共全量 `3110 passed, 7 skipped`，私有扩展 `42 passed, 1 skipped`；
跳过项均需显式真实发布素材。Ruff、BasedPyright、compileall 和 diff 检查通过。
生产代码净删除 39 行，无新模块、依赖、配置或镜像内容。仍需整体审计其他隐式
成功 fallback，Phase 6 保持 `in_progress`，总进度保持 5/8。

**精灵发布事实严格读取（2026-09-12）：** 删除精灵资料仓库对专属效果、来源、
魂印顺序、魂印 PNG、展示校正、道具价格和伙伴表读取失败时返回空集合的兼容路径；
也删除旧价格列探测、旧伙伴字段倒置及机器人侧“微光秘境/共振晶体”名称修正。
SeerAPI 候选产物已经直接发布规范名称和强化前后描述，消费者只接受当前 schema。
发布表 SQL 失败统一转换为带精灵 ID 的 `PublishedDataIncompleteError`，查询明确回复“精灵资料
数据不完整”，标记 `complete=False`，不调用 renderer、不写完整图片缓存；真正的
空查询结果仍保持为空。

精灵、魂印、专属效果和价格相关回归 `47 passed`；公共全量
`3112 passed, 7 skipped`，私有扩展 `42 passed, 1 skipped`。使用本地候选发布库的
萨尔蒙（3549）真实消费链路 `1 passed`，覆盖 SQL、官方 PNG、原生渲染、缓存复用、
OneBot 编码和受限平台模拟上传。Ruff、BasedPyright、compileall 和 diff 检查通过；
生产代码净减少，无新模块、依赖、配置或素材。发布加载器目前仍只前置验证 schema
版本与元数据表，按类别声明必需业务表的契约仍需在 Phase 4/6 后续统一设计，不能
通过恢复运行时空结果来掩盖。Phase 6 保持 `in_progress`，总进度保持 5/8。

**刻印角数事实错误语义（2026-09-12）：** `mintmark_quality` 查询失败不再返回空
映射。仓库将 SQL 故障转换为 `PublishedDataIncompleteError`，服务记录完整异常并向
用户明确回复“刻印角数数据不完整”；普通属性榜也不会再带着缺失角数继续生成结果。
真正存在但没有匹配记录的空映射仍保留原有业务语义。专项 `18 passed`，Ruff、
BasedPyright 和 diff 检查通过；无新配置、依赖、数据库或 QQ 身份改动。

**发布数据错误接口收口（2026-09-12）：** 精灵资料、刻印角数和构建期 Flash 座驾
PNG 统一使用 `PublishedDataIncompleteError(component, entity_id)`，删除两个领域专用
异常及 Flash 旧数据库缺表时只记录一次 warning、随后返回 `None` 的进程级兼容状态。
座驾 PNG 表缺失现在与“表存在但该座驾没有 PNG”严格区分：前者记录异常并返回不完整
结果，后者仍可显示“官方图片暂未上线”。新内容渲染也不再把缺表伪装成无图片。
相关精灵、刻印、装备、新内容专项 `89 passed`；Ruff、BasedPyright、compileall 和
diff 检查通过。该接口只表达发布事实完整性，不涉及平台或 QQ 身份。

皮肤详情价格读取随后接入同一接口：`pet_skin` 确实不存在仍表示未找到皮肤，
`skin_shop_price` / `skin_store_price` 或关联 schema 故障则返回保留已取得立绘的
`complete=False` 回复，并明确标注价格数据不完整，不再静默显示成“没有售价”。
皮肤仓库与查询专项 `19 passed`，Ruff、BasedPyright 和 diff 检查通过。

**发布元数据严格验证（2026-09-12）：** schema 版本通过后，`api_metadata`
行、素材 manifest 范围 JSON、仓库、revision 或 manifest revision 损坏时，
加载器不再静默返回“未知版本/无可用素材”，而是拒绝候选发布并保留
上一份有效快照。`DatabaseManager.register()` 创建的全空内存占位库仍明确表示
“尚未加载”，不与损坏发布混淆。数据库生命周期专项 `18 passed`，Ruff、
BasedPyright、compileall 和 diff 检查通过；无 QQ 身份、配置、依赖或数据表变更。

**纯缓存榜单时间语义（2026-09-12）：** 额度耗尽后的榜单玩家查询现在与
其他玩家详情一样输出严格“获取时间”。过期名次与缓存的未上榜证明
不再看起来像当前实时结论；旧名次作为在线定位坐标的行为保持不变。
榜单玩家与缓存策略专项 `30 passed`，Ruff、BasedPyright 和 diff 检查通过。

**新增内容详情完整性（2026-09-12）：** 同一不可变发布中，新增内容索引
引用的精灵、技能、皮肤、刻印、套装、部件、座驾、称号或群星牌详情
缺失时，不再生成带“暂无官方简介”的伪完整图片。数据异常统一转为
`PublishedDataIncompleteError`，图片菜单停止并由现有上层返回可信的索引文本；
仅素材文件缺失时仍显示“官方图片暂未上线”并且不写最终缓存。新内容、
数据版本和发布生命周期相关专项 `119 passed`，Ruff、BasedPyright 和 diff 检查通过。

**赛季读取失败隔离（2026-09-12）：** target 错误语义。移除
`SeerDatabase.peak_season_start()` 的全异常转 None：未加载数据库显式报不可用，
SQLAlchemy 读取故障保留 cause 和日志；仅实际无赛季记录仍返回 None。巅峰详情将
赛季标识读取纳入现有 `fetch_partial_rank_summary`，读取失败时保留在线基础数据、
逐榜标注失败、拒绝完整缓存和未限定赛季的样本写入。榜单列表/分数入口返回
数据不可用原因，本地赛季榜不继续读全部赛季。真实 SQLite 删除赛季表验证故障
与空表区别；详情/会话/榜单/时间专项 80 passed，数据库与详情专项 46 passed
（两组有重叠，不相加）。全量 Ruff、basedpyright、compileall、diff 通过，未重复
全量 pytest。无新模块、配置或依赖，总进度仍为 4/8。

**配置模型旧导入收口（2026-09-12）：** target 清理。幸运橱窗调用方直接从
`config.models.seer_lucky` 引用配置模型，删除 `seer` 中标注 compatibility 的
重导出；聚合配置以模块限定名引用实际模型。配置格式及默认值不变，无新包装器。
私有仓库无旧入口调用，原有未跟踪 `uv.lock` 保留。公共全量 2966 passed、1 skipped、
440 warnings（126.68 秒），私有 43 passed；Ruff、basedpyright、compileall、diff
通过。原生发布素材 smoke 未在本次提供产物，因此仍为 skip；不宣称部署验收。
本地 main 仍为 `55a39fd1`，未 pull/merge。总进度 4/8，无新增镜像依赖或配置。

**镜像元数据来源（2026-09-12）：** target 收口。删除 Docker 检查/更新路径中
写死的 `Murmansk5000/IronsBot` 源码仓库回退及 `fallback_repo` 参数。提交说明
只读取镜像 OCI source/revision 标签；没有可识别来源时不发 HTTP 查询，保持说明
为空，摘要比较、拉取和更新行为不变。两条真实 DockerClient 用例在修改前均复现
两次错误仓库请求，修改后无请求且仍判定镜像无更新；另验证自定义来源仓库及
元数据超时日志。Docker 专项 55 passed，全量 Ruff、basedpyright、compileall 通过。
测试隔离 daemon/registry，不声称真实 Docker 更新已验收；无新增配置、依赖或
运行文件，也未测量镜像体积。总阶段计数保持 4/8。

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

**正向榜单写入时序（2026-09-12）：** 真实 SQLite 复现旧页晚到覆盖新页、玩家被
移回旧排名和旧空页删除新数据三项失败。页面保存现在同一写事务中检查较新重叠页、
玩家旧坐标及覆盖当前名次的否定证据，冲突时整页拒绝，不拼接新旧观察；全局昵称
也不再被其他榜的旧数据回写。127 项榜单/缓存/SQLite 回归及私有 43 项通过，
定向类型、Ruff、编译和 diff 通过。未新增表、库、迁移或配置；来源时间异常和
完整动态多页一致性仍待验收，整体 4/8。见否定缓存 Spec 的正向写入补充。

**榜单异常时间（2026-09-12）：** 复现未来/无穷大时间覆盖有效页，以及异常持久化
时间被接受为历史证据。复用 core 的观察时间校验，拒绝异常页/否定记录写入，
过滤历史坐标、分数提示和页面统计中的异常时间；有效页面头不能掩盖异常条目。
有效刷新可替换异常时间的否定记录与昵称，不让未来记录阻塞正常更新。
234 项相关测试及私有 43 项通过，定向类型、Ruff、编译和 diff 通过。
未新增表、模块、配置或文件路径；未做全量套件/生产部署验收。
完整动态多页一致性仍未证明，整体保持 4/8。见否定缓存 Spec 的异常时间补充。

**榜单页读取快照（2026-09-12）：** 真实 WAL 双连接交错复现新条目配旧时间。
页面元数据和条目现在放在同一延迟只读事务中读取；期间写入可完成，下一次读取
才看到新提交。生产代码增加两行，无新表、配置或模块。166 项相关测试通过，
定向 Ruff、类型与编译通过；未重复全量或部署验收。官方多页请求的动态一致性
仍未完成，整体 4/8。见否定缓存 Spec 的读取快照补充。

**有序榜单页冲突（2026-09-12）：** 原分数区间的重复玩家/分数倒序校验收为既有
分页模块中的通用能力，普通榜、排除名单榜、缓存窗口和线性玩家查找共同使用。
发现冲突时不删重重排名、不保存未上榜记录，也不新增自动重翻请求。
全公共测试 2886 passed（319 条已有依赖警告，126.71 秒），私有 43 passed；
全仓类型、Ruff、编译和 diff 通过。未新增模块、库、配置或依赖。
这只证明可观察冲突会被拒绝，不能证明官方多页是同一快照；非顺序探针和命中后
可见名次换算等仍待验收，整体 4/8。见否定缓存 Spec 的有序页冲突补充。

**可见名次身份确认（2026-09-12）：** 命中后的排除名单换算显式传入玩家 ID，
复用页序列校验；读到旧位置时核对 ID 和分数，提前结束的前缀不再当成完整排名。
三项先失败的回归复现换人仍报第 20、空页报第 0、重复玩家仍报第 20。
冲突后保留已观察分数、清除排名并给出明确失败；稳定结果和请求次数不变。
161 项相关测试及定向类型、Ruff、编译、diff 通过；未重复全量回归。
保留已找到全部排除账号后的提前结束优化，不声称能够识别所有未观察到的移动。
无新模块、表、配置或请求，整体 4/8。见否定缓存 Spec 的身份确认补充。

**二分探针一致性与完成状态（2026-09-12）：** 共享分数二分引擎检查探针倒序和
前位缺失、后位存在的矛盾，两项先失败测试复现。玩家查询保留探针/同分段预算
耗尽的未确认状态，不再当成缺席；限定扫描内确实命中后可正常返回排名。
现有每个边界分别计预算的规则不变，示例补充说明，未增加请求或配置字段。
143 项相关测试及定向类型、Ruff、编译、diff 通过；未重复全量回归。
尚未证明未观察位置或后续采样页面共享快照，整体 4/8。见否定缓存 Spec 补充。

**二分后采样（2026-09-12）：** 玩家查找和分数人数展示复用采样校验，验证实际
条目与已证明的同分边界，避免跳过变分/缺失条目后仍报旧人数；重复玩家沿用
公共页序列检查。预算耗尽后的试探上界不视为已确认边界，正常下降仍允许。
145 项相关测试及定向类型、Ruff、编译、diff 通过；未重复全量回归。
无新文件、依赖、配置、数据库或请求；不宣称可识别未观察到的移动，整体 4/8。
见否定缓存 Spec 的采样补充。

**排除名单分数查询上限（2026-09-12）：** 接入通用页序列校验；三项先失败回归
复现一页上限读两页、五名上限返回十人、接受重复玩家。现按页数和页内可见名次
双重停止，明确区分未完同分段与已观察到的短页/低分边界。
153 项相关测试及定向类型、Ruff、编译、diff 通过；未重复全量回归。
未增加模块、库、配置或请求。局部证据不替代整体阶段验收，进度保持 4/8。

**Phase 6 整体验收（2026-09-12）：** 逐项复核配置模型、Seer 发布集成、缓存降级、
后台任务边界和用户可见部分结果。配置只接受目标字段；发布数据库由 SeerAPI 在最终
后处理后写入完整表清单和 DDL 指纹，机器人在原子替换前重算验证。发布字段统一使用
无损整数和严格布尔标志，损坏 JSON、错误结构、未知新增内容分类/变更类型、缺表及
查询故障均明确失败，不再转换成 `0`、空集合、`未知` 或完整图片缓存。

Seer 发布集成层的宽异常捕获只保留协议错误码的人类说明查询；该辅助查询失败会记录
日志并保留调用方已有的原始错误码。AST 架构测试固定这一个许可点，防止 repository
重新加入“异常即空数据”。外部图片缺失、官方预告链接、网络发送失败、后台任务隔离和
已标注获取时间的缓存结果属于明确的可观察降级，不是发布事实 fallback。QQ 号、直接
@、绑定等目标平台可能无法表达的能力按平台延期规则留到 Phase 7 末尾，不阻塞本阶段。

最终公共全量回归 `3138 passed, 7 skipped`；跳过项均要求显式真实发布素材。Ruff、
BasedPyright、compileall、差异检查及发布数据架构守卫通过。Phase 6 关闭，总进度 7/8。

### Phase 7 — QQ Official 平台验收

**目标契约：** `FakeOfficialPlatform` 继续验证能力边界；生产适配由
`integrations.qq_official` 实现，二者必须遵守同一核心身份和出站消息契约。

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

2026-09-12：Seer 查询图文内容收口到现有 `QueryReply.to_outbound()`，普通查询与
新增内容菜单共用 OneBot 发送入口，删除插件中的 SAA 图文组装函数。真实属性查询
服务与计算器已纳入受限平台的文字、图片拒绝和回复过期测试；数据仓储和渲染器仍为
测试替身，不计为真实渲染或官方端到端验收。详见上面的 capability Spec。
本项不增加依赖、配置、数据库或生产适配器，Phase 7 保持 `in_progress`。

2026-09-12：完成一次真实生产 Python 依赖审计，修复锁文件中的 h2 安全公告，
现有 Docker 发布工作流增加冻结依赖审计与失败报告，在登录仓库和发布镜像之前
执行。审计工具不进入运行镜像；Linux 镜像、系统包和真实 OneBot smoke 尚未验证。
详见 [运行镜像 Spec](specs/2026-09-12-runtime-image-inventory.md)，不提前关闭 Phase 7。

2026-09-12：真实属性图查询已收录为可重复的原生 smoke test，用实际 SeerAPI
产物、固定版本 HTTP 素材、统一渲染协调器及缓存完成 PNG 验收；再次查询零新增
SQL/HTTP/渲染，OneBot 编码与受限平台测试传递同一图片字节。未提供发布库时明确
skip，不用模拟素材替代。见 capability Spec 的 Native Published Type Query Smoke；
其余素材范围、Linux 镜像和真实 QQ 发送仍待验收，不增加阶段完成数。

2026-09-13：使用完成最终 schema 封口的真实 SeerAPI 产物执行七类原生查询矩阵。
属性、竞技池、专家池、精灵资料和私有阵容 5 类通过；巅峰投票与竞技精灵榜仅因
GitHub Raw 官方素材连接失败而明确失败，未生成图片或缓存伪成功。整套耗时 14 分钟，
不因外部站点波动重复全矩阵。Docker 29.5.2 客户端可用，但本机 Linux daemon 未运行，
因此仍不声明真实镜像启动验收。

同日后续将不可变素材下载扩展为 GitHub Raw 与 jsDelivr 双入口；两者都由同一个
SeerAPI 发布的仓库名和 commit revision 生成，不复制素材，也不回退到可变 main。
此前失败的巅峰投票与竞技精灵榜真实原生用例定向复测 `2 passed`，至此七类真实发布
渲染均已有通过证据。相关素材、数据库和渲染专项 `57 passed`，最终公共全量回归
`3141 passed, 7 skipped`，Ruff、BasedPyright、compileall 和差异检查通过；Linux
镜像与真实平台发送仍未验收。

共享 service 的命令说明、AI 分类提示和 B站失败通知不再写死 QQ/OneBot 名称，改用
当前账号/平台语义；AST 守卫禁止 service 用户文案重新出现适配器名称。OneBot 插件
自身的 QQ 文案保留。需要 QQ 号、直接 @ 或绑定且目标平台 API 无法表达的操作继续按
平台能力延期规则留到最后，不以虚构映射阻塞其他 Phase 7 验收。

2026-09-13：Docker 发布增加候选镜像门。工作流先本地构建并加载候选镜像，在无网络、
只读示例配置下通过真实 entrypoint 执行配置解析和核心依赖导入；成功后才登录仓库并
从同一上下文、标签和 BuildKit 缓存发布。该门不向最终镜像增加文件或依赖。工作流与
启动预检专项 `21 passed`；本机仍无 Linux daemon，因此只证明 CI 契约，不能提前把
真实镜像运行标为完成。

2026-09-13：冻结生产依赖复核为 59 个包；隔离 Python 3.10 Windows 环境展开约
64.49 MiB。逐项导入与所有权审计未发现可安全删除的直接运行依赖，开发用 Node、
BasedPyright、pytest、Ruff 和审计工具均未进入生产导出。五张约 13.65 MiB 的固定图片
属于部署者内容而非 SeerAPI 官方发布素材，已连同硬编码默认命令和专用 `builtin`
后端移出程序包；通用图片命令只接受 TOML 显式配置的 `local/cnb` 后端。Linux 层大小
仍以候选镜像 CI 产物为准，本地源码差额不冒充镜像测量结果。收口后公共全量回归
`3142 passed, 7 skipped`，Ruff、BasedPyright、compileall 与差异检查通过。

同轮将 Docker 字体从 Source Han Sans SC 泛 CJK Regular/Bold 改为官方同版本 CN 子集
Regular/Bold，未压缩载荷由约 31.94 MiB 降至 16.21 MiB；候选 smoke 新增 fontconfig
双字重及不同文件校验，并把上游 `LICENSE.txt` 保留到镜像文档目录。连同固定图片收口，
预计应用与字体载荷共减少约 29.38 MiB；实际 Linux 镜像差额仍等待 CI 产物，不提前
记为 Phase 7 完成。

基础镜像审计确认浮动 `python:3.10-slim` 已从历史发行版迁到 Debian Trixie。构建与
运行阶段现显式统一为 Bookworm，避免无代码提交时发生发行版、ABI 和体积漂移；标签
继续接收补丁更新，每次发布仍以解析后的最终 digest 和层清单留证。审计时 amd64
Bookworm/Trixie 压缩基础层约为 45.05/45.75 MiB，差异约 0.70 MiB。

候选镜像现于仓库登录和发布前执行分目录硬预算：`/app` 8 MiB、Python 运行依赖
128 MiB、字体 24 MiB。任一项超限即失败，并通过 `always()` 上传候选清单；四组 shell
测试覆盖边界值及三个独立超限分支。该门防止后续把部署者素材、依赖增长或字体增长
混成一个总数，也不把未运行的 CI 契约冒充实际镜像证据。

候选镜像另在正式 push 前与当前 fork 的 GHCR `latest` Docker 报告尺寸比较，默认单次
增长上限为 8192 KiB。仓库名由 `github.repository` 推导，比较使用拉取后的基线
digest，并始终上传候选、基线和差值；基线读取
失败或超限都会阻止发布，避免绝对分目录预算较宽时出现未被发现的大步增长。Docker
发布、启动预检与结构边界测试 `39 passed`；该批验证时尚无真实 Linux 候选差值。

随后在 Docker Desktop Linux/amd64 Engine 29.5.2 上真实构建 commit `93bd3aac21e8`。
首次构建发现嵌套 `__pycache__` 未被根级 `.dockerignore` 规则排除，`/app` 达 9384 KiB；
改为递归规则后重建为 4220 KiB，容器内无 `.pyc`，其余 site-packages 104644 KiB、字体
19452 KiB，三个预算均通过。离线 entrypoint、双字重字体、配置和核心依赖导入 smoke
通过。候选 Docker 报告 94.28 MiB；同一引擎拉取的线上 `latest` digest
`sha256:4677ca61...` 为 405.53 MiB，候选少 311.24 MiB。该证据尚未由发布工作流上传，
也不代表真实 QQ 平台验收；整体仍为 7/8。

2026-09-13：QQ Official 被动入口接入现有 `AiService`，没有复制模型客户端、记忆库
或命令白名单。已注册命令先由 `CommandCatalog` 认领；仅私聊未注册文本及群内直接
@ 机器人的未注册文本进入 AI。AI 未配置或当前上下文未开放 `ai_chat` 时，群内直接
@ 返回统一指令提示，私聊保持静默；引用回复继续由适配器全局忽略。portable router
同时补齐 `FeatureService.is_message_blocked()`，防止受限平台绕过已有黑名单策略。
OpenID 与群作用域直接进入现有 AI 会话键和 SQLite 记忆，不推导数字 QQ 号，也没有
引入 NapCat、跨平台消息对时或新的数据库/TOML 字段。专项 AI/目录回归 `105 passed`，
官方平台/能力/架构回归 `66 passed`，Ruff、BasedPyright、compileall 与差异检查通过。
最终公共全量回归 `3284 passed, 7 skipped`。BasedPyright 的输入范围同时显式收口到
`ironsbot` 与 `tests`，不再枚举历史测试临时目录；这只缩短验证时间，不改变检查等级。
真实 AppID 联机发送、主动订阅能力和模型网络 smoke 仍是 Phase 7 完成门，整体保持 7/8。

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

## Docker 维护动作收口（2026-09-13）

`/重启机器人` 与 `/更新镜像` 不再维护“配置决定是否检查”和“另一路 yes/no
确认”两套语义。operations service 统一暴露`仅重启`、`检查并更新后重启`两个动作，
OneBot 仅承载数字菜单；旧 `check_on_restart` 配置和无调用的确认适配器删除。

目标平台的管理员身份映射仍遵循 QQ 身份能力延期规则，最后统一验收，不在本阶段
增加 QQ 号专用补丁。

## 主动推送通用加固（2026-09-13）

主动推送的有限并发、缩批重试、结果不确定时防重发和传输断线止损迁入
`services.messaging.proactive_delivery`。平台适配器通过 `DeliveryFailureKind` 提交失败
语义；OneBot 错误码不进入 core 或业务 service。现有 TOML 可继续使用默认策略，
需要调参时才增加 `[messaging.proactive_delivery]`。

B站正文与图片此前仍有一层固定三次重试，叠加统一策略后可能放大发送次数。该私有
循环现已删除：B站 service 每种内容只提交一次，重试、缩批与失败分类全部由通用
投递服务负责；策略耗尽后的管理员通知保持在 B站业务层。

本阶段不实现 QQ 号路由或目标平台主动消息资格映射；这些依赖平台 API 的内容仍在
最后验收阶段处理。

## 巅峰投票展示增强（2026-09-13）

本地只读 `main` 的投票周期、总票数与占比展示已按 V5 边界迁入。巅峰 service
只提供投票级别、时间范围和脱离 Session 的投票快照；纯 presenter 计算非负总票数
及整数占比并生成不可变 document；HTML renderer 不读取数据库或下载额外资源。
展示改为 900px 紧凑卡片布局，图片仍由现有 SeerAPI 图片源按需获取，机器人仓库
没有新增静态图片或运行时资源包。

## 渲染项目元数据（2026-09-13）

Docker 候选与发布镜像统一注入当前构建仓库的 `IRONSBOT_PROJECT_URL`。HTMLKit
适配器为所有模板提供该值，五个 Seer 图片页脚不再硬编码某个上游仓库；源码运行
未注入时只显示通用 IronsBot 标识。项目地址同时进入最终图片缓存作用域，切换 fork
不会复用带旧页脚的图片。该改动没有增加图片、字体或运行时依赖。

## B站长文本收口（2026-09-13）

B站推送与历史详情不再分别维护摘要规则。平台无关的
`DynamicContentCompactor` 统一执行长度判断、AI 摘要、有限重试和确定性截断；摘要
保存在既有动态历史库中，后续打开详情直接复用。历史摘要只按需生成，启动时不批量
调用 AI。OneBot 适配器不拥有压缩或持久化规则，主动投递重试仍只有通用投递服务
一层。该切片不增加 TOML、图片资源或运行依赖。

## Seer 专用结果出站收口（2026-09-13）

每周预告图片、巅峰查询结果与群星牌条目补齐统一 `to_outbound()` 契约，图片、文字
顺序和 MIME 类型由平台无关结果对象持有，OneBot 适配器只负责最终编码。群星牌普通
查询与新增内容详情复用同一图文结果，并保留各自的附加图片策略。每周预告中没有生产者
的裸 `bytes` 分支已删除；受限平台测试直接复用这些结果并验证图片上传。QQ 号、@ 用户
和绑定关系没有进入本批，继续按目标 API 能力延期规则留到最后。

配置型图片命令的 `{image}` 模板也从 NoneBot `MessageTemplate` 收入 core 的结构化
出站模板。普通字段继续使用 Python 格式说明，图片等结构部件不会被转成字符串；
`SendpicResult` 统一填充命令、随机/自选、序号、总数和图片。各平台只需编码统一结果，
无需复制模板解析规则，现有 TOML 无需修改。

## AI 意图动作执行收口（2026-09-13）

AI 意图分类后的消息、推广、二次 AI 回复、战队推荐和战队资源查询统一由平台无关的
`AiIntentActionExecutor` 生成有序 `OutboundMessage`。OneBot 插件只提供来源上下文、
编码并发送结果；旧 `plugins.onebot.ai.team_actions` 和仅用于插件分支的
`AiService.is_team_action()` 已删除。受限平台测试复用真实多消息动作，不引入 QQ 与
OpenID 映射；无法由目标 API 表达的身份操作继续留到最后。

## 关于页出站收口（2026-09-13）

项目版本读取、关于页内容和结构化出站消息迁入平台无关的 `AboutService`。OneBot 插件
只注册入口并编码服务结果；受限平台测试复用同一消息，验证版本内容和回复投递。共享
文案不再声明特定传输适配器；没有新增配置、运行依赖或静态资源。QQ 号、直接 @ 和
绑定能力仍按平台延期规则留到最后。

## 幸运橱窗交互结果收口（2026-09-13）

幸运橱窗 service 现在直接生成图片或文字 `OutboundMessage`，并统一拥有关注皮肤的双
ID 标签、列表以及增删、清空、重置结果文案。OneBot 插件删除原生图片消息组装和重复
关注格式化，只保留事件适配、登录确认与候选数字菜单，文件由 642 行降至 595 行。
账号绑定和平台成员身份未改，仍按平台能力延期规则最后处理；没有新增配置、依赖或
图片资源。

## 运行服务器依赖收口（2026-09-13）

启动入口已明确固定为 Uvicorn 的 `asyncio`、`h11` 与 `websockets-sansio` 实现，
因此运行依赖改为直接声明 FastAPI、Uvicorn 和 WebSockets，不再通过 NoneBot 的
FastAPI extra 间接安装 Uvicorn standard extras。冻结锁文件删除运行时未使用的
`httptools`、`uvloop` 与 `watchfiles`，并新增依赖与入口组合的防回退测试。

完整宿主进程已启动到监听状态并正常关闭；全量测试 3231 项通过、7 项跳过，Ruff、
BasedPyright、compileall 与 diff 检查通过。精确的变更后 Linux 镜像尺寸留给发布候选
任务补证，不以宿主环境推算。QQ 号、绑定和直接 @ 等目标 API 可能无法表达的操作不在
本批处理，继续延期到最终平台适配。

## OneBot 内容组装清零（2026-09-13）

每周预告的可选参考链接与配置单图命令改由各自 service 结果生成结构化出站消息，
OneBot 插件内已不存在 `OutboundMessage`、文字、图片或提及 part 的直接构造。新增 AST
架构门约束该边界，受限平台验收复用真实结果类型验证图片上传与内容顺序。该变化不涉及
QQ 号、绑定或直接 @ 解析，这些能力仍按平台 API 能力延期到最后。

精简后的冻结生产依赖随后使用发布工作流相同的固定版 `pip-audit`、哈希校验和严格失败
参数复核：53 个运行时发行包均被审计，未发现已知漏洞。临时报告不进入仓库或镜像；
每次真实发布仍由 CI 留存与该候选对应的审计附件。

## OneBot 进程冒烟与日程时间收口（2026-09-13）

新增完整宿主进程测试：从临时配置启动 `python -m ironsbot`，连接实际
`/onebot/v11/ws` 反向 WebSocket，发送标准 OneBot 私聊事件，并响应机器人发出的
`send_msg` API 动作。测试确认“关于”命令经过真实 adapter、matcher、service 和
OneBot 编码后返回正确目标用户及版本正文；这不是线上 QQ 登录或 QQ Official 验收。

该测试同时发现秒级配置合并不完整：榜单页面刷新、战队资源、定时重启、无头重连和
幸运橱窗仍有手动拆分时间或写死 `second=0` 的路径。五类任务现统一使用
`ScheduledClockTime` 与 `JobRegistry.add_daily()`；配置统一规范为 `HH:MM:SS`，榜单
活动窗口也按秒判断。131 项定向测试及包含进程冒烟的全量回归均通过（3236 passed、
7 skipped），Ruff 与 BasedPyright 通过。QQ 号、绑定和直接 @ 等目标 API 无法表达的
能力继续留到最终平台阶段，不阻塞当前工作。

## 运行时伪通用桥接清理（2026-09-13）

删除无人引用的 `runtime/bindings.py` 与 `runtime/onebot_reply.py`；二者的现行职责早已
分别由 OneBot matcher 支持和消息输入适配器承担。仅由 OneBot 提示会话使用的异常也从
`runtime/prompt_errors.py` 迁入 `integrations/onebot/prompt_errors.py`。`runtime` 只
保留真正跨适配器的在途请求和缓存路径能力，并新增架构门禁止恢复这些伪通用桥接模块。

该收口不改变消息行为、配置或数据库。QQ 号、绑定和直接 @ 等依赖目标平台 API 的能力
仍按既定规则延期到最终平台阶段，不阻塞其他通用接口和发布验收工作。

## 幸运橱窗价格与详情菜单（2026-09-13）

幸运橱窗的四个皮肤价格由 Seer 数据 repository 一次批量读取发布 SQLite，并由 service
统一格式化当前价、原价与风尚券信息。缺表、缺行或无有效价格时仅将该项降级为“价格
暂未获取”，不会丢弃已经取得的四张皮肤卡片。机器人没有新增货币图片、SVG 或外部
资源 URL；后续若需要官方货币图标，仍应由 seerapi 发布并通过既有资源接口消费。

查询结果同时产出平台无关的四个皮肤选择项；OneBot 只把它们接入现有数字 prompt，
用户发送 `1-4` 后复用统一 `PetQueryService.select_image()` 获取皮肤详情，`0` 仍由通用
会话退出逻辑处理。本批没有新增 TOML、数据库 schema 或 QQ 身份能力。QQ 号、直接 @、
绑定关系等目标 API 不能可靠表达的操作继续统一延期到最终平台验收，不为单个平台补写
业务分支。

## SeerAPI 构建输出与 800 行门禁收口（2026-09-13）

SeerAPI 的效果图标构建和新内容索引已经分别由专用模块承担；本轮继续把 950 行的
`solaris.analyze.output.outputter` 按 Schema 输出、JSON/数据库输出和共享辅助函数拆分，
各模块分别保持在 541、237 和 62 行。包级公共导出不变，调用方无需改导入路径。

新增源码架构测试扫描 `scripts`、Solaris、SeerAPI models 和 Python client 的维护型
Python 模块，超过 800 行即失败。自动生成的 `openapi_comments.py` 是唯一显式豁免，
不得借豁免名单容纳手写业务模块。SeerAPI commit `69f2af4` 通过全量 `318 passed`、
Ruff、compileall、公开导入和差异检查。

后续切片已将座驾 PNG 切换到 SeerAPI 的 `generated-render-assets` 分支：工作流增量生成并
提交素材，manifest v3 为 `mount` 声明仓库和精确 commit，IronsBot 统一通过
`SeerImageSource` 获取。座驾使用有序不可变候选，先取 Unity `equip` PNG，再取构建生成
PNG；真实发布库 36 个座驾中已有 25 个命中前者。运行时 SQLite Blob repository 与
fallback 已删除。SeerAPI 全量
`327 passed`，IronsBot 全量 `3239 passed, 7 skipped`；当前只剩真实 Actions release 与消费者
smoke。QQ 身份能力仍按平台延期规则排在最后。

同日使用现有 62 MB 真实发布库执行跨仓库本地 smoke：生产 finalizer 重建 manifest v3，
36 条座驾中 25 条由固定 Unity revision 满足；IronsBot 随后通过 `DatabaseManager` 加载，
识别 `default/mount` 两个仓库，并由生产 HTTP 图片源取得 `1300067` 的 26,603 字节、
193×184 PNG。该测试证明本地生产者/消费者契约接通，但生成分支尚未远端发布，剩余
11 个 Flash 缺图和真实 Actions release 仍不标为完成。

同日另以临时 bare remote 原样执行 Actions 中的生成素材分支命令，验证了
`generated-render-assets` 不存在时创建 orphan branch，以及后续 worktree 增量提交并推送
新 revision。两轮提交不同，远端最终文件集符合预期。该 smoke 只关闭本地 Git 分支生命
周期风险；真实 Actions 权限、资源生成耗时和发布后消费者验证仍是外部门禁。

生成器随后进一步以 manifest v3 的 `default` 仓库事实裁剪 FFDec 输入，不再为已有 Unity
PNG 的座驾重复生成图片，并从生成分支移除这类冗余副本。真实发布数据复核为 36 个座驾、
25 个 Unity 命中、11 个 Flash 缺口，首次生成候选减少约 69%；SeerAPI 全量 `329 passed`。
该优化缩短构建并减少生成分支体积，不改变机器人候选顺序或运行镜像内容。

生成入口进一步要求当前 manifest v3 与 typed repository 元数据；输入旧 schema 或流水线
顺序错误时立即失败，不再退回全部座驾 FFDec。专项 11 passed、SeerAPI 全量
`331 passed`，确保“构建突然变慢”不会掩盖发布契约错误。

效果图标并发 renderer 的公共出口也固定按 icon ID 排序，不再把 worker 完成顺序泄露给
SQLite、manifest 或错误摘要。逆序完成测试、15 项效果图标专项和 SeerAPI 全量
`330 passed` 通过；效果图标 Spec 的前六项本地 acceptance 已据此关闭，真实 FFDec
Actions release 仍保持未完成。

SeerAPI 的 16 个效果图标分片与最终 build 现在共用本地 `setup-ffdec` composite action。
固定版本、SHA-256、网络重试和安装逻辑只保留一份，经校验的 FFDec archive 使用 Actions
cache 跨构建复用；主工作流删除 32 行重复 shell。YAML 解析、CI 结构测试、SeerAPI 全量
`332 passed`、Ruff、compileall 与差异检查通过。真实 cache hit 节省时间需由首次线上运行
记录，不提前估算为完成证据。

效果图标分片随后增加只读预检：先恢复发布缓存，再以禁用 PNG 渲染的同一资源适配器区分
缓存命中、官方确认 404、瞬时失败和可修复缺图。前两类不再安装 FFDec，后两类才进入
渲染；预检输出整片与修复 ID 快照，渲染命令不再重复读取 ConfigPackage 或 Unity
manifest，只处理缺口并仍导出整片缓存。最终 build 仍为座驾 Flash 缺口保留 FFDec。SeerAPI
全量 `333 passed`，Ruff、compileall、YAML 与差异检查通过；真实 Actions 耗时仍是外部验收项。
资源读取、Unity 缺口和缓存导出装配只有预检持有，渲染消费其快照；总构建器由 771 行
降到 760 行，避免两条内部命令重复网络发现或逐渐产生不同的分片语义。

最终 SQLite build 随后改为效果图标缓存的严格消费者：禁止现场 PNG 渲染，缓存缺口直接
使发布失败，不再保留第二套 FFDec backstop。座驾生成先复用现有生成分支并计算候选，
只有确实缺 PNG 时才安装 FFDec；冷构建和新增座驾仍走原渲染及 pending 记录。座驾/CI
专项 14 passed、SeerAPI 全量 `335 passed`，Ruff、CLI、compileall、YAML 与差异检查通过。
真实 Actions 热构建耗时仍待发布环境记录。

同日按当前提交执行三仓本地完成度审计：IronsBot 全量 `3239 passed, 7 skipped`，Ruff、
BasedPyright（0 errors/warnings）、compileall 与差异检查通过；SeerAPI 全量 `335 passed`；
私有扩展通过 `IRONSBOT_PUBLIC_ROOT` 联合 V5 宿主运行 `42 passed, 1 skipped`，Ruff 与
BasedPyright 通过。审计修正了幸运橱窗测试替身的 3 个类型声明错误，没有放宽检查或改变
生产行为。Docker Desktop Linux Engine 仍在 12 秒只读探测中超时，系统权限也不允许
启动其服务，因此最新镜像和真实 Actions 仍保留为外部门禁。

效果图标分片预检另以 118 MB 的真实历史发布库运行：成功恢复 `2108` 个 PNG，首个
`1/16` 分片包含 `132` 个图标且全部缓存命中，输出 `repair_count=0`、
`needs_render=false`，导出的 `132` 组 PNG/metadata 与分片 ID 快照一致。该证据确认热
分片会跳过 FFDec。另复制同一真实缓存并仅移除 `icon_id=1` 的 PNG/metadata，预检精确
输出 `cached_count=131`、`repair_count=1`、`repair_icon_ids=1`，没有把整个分片送去
重建。真实 Actions 权限、缓存命中率、总耗时和发布后消费者 smoke 仍须在线上关闭。
涉及 QQ 号、直接 @、绑定或成员身份而目标 API 无法忠实表达的能力继续留到最终平台
适配，不阻塞这些平台无关的发布验收。

真实预检还暴露了纯缓存命中时仍打印 `Rendering` 的误导性总进度。SeerAPI
`42b9c34` 将该层统一改为 `Resolving` / `resolution progress` / `Resolved`：缓存读取、
资源缺失判定和必要时的实际渲染共用同一准确术语，下层 FFDec 失败日志保持不变。
定向 `4 passed`、SeerAPI 全量 `335 passed`，Ruff、compileall 与差异检查通过；数据库、
PNG、配置和依赖均未改变。

## 本地 Main 差异复核（2026-09-13）

本地 `main` 仍为 `55a39fd1`，本轮只读比较，没有 fetch、pull、merge 或 push。最新十个
主线提交中的平台无关行为均已有目标态实现：已有精灵技能预览过滤由
`services.seer.new_content` 负责；群星牌觉醒变体合并由 V5 `d0344dac` 覆盖；排队推送
的优先级、失败保留和清理语义由 V5 `703842e1` 的统一 OneBot outbound queue 覆盖；
Docker 交接失败继续启动由 V5 `69539177` 覆盖；战队详情由 V5 `20316904` 覆盖；B站
抽奖与中奖已作为两项配置化 category 存在。主线的大文件拆分目标也由三仓 800 行架构
门持续验证，不搬回主线的旧模块边界。

主线 `b14df7a5` 和 `6844980e` 的玩家战队能力已在显式身份关联完成后迁入共享服务：
玩家详情菜单可查询所属战队，“战队”概览会将当前玩家所属战队置顶并去重，两个平台
共用同一交互操作。`ba08f749` 的实时 QQ 昵称依赖旧版按 QQ 账号选择他人橱窗的流程，
当前按操作者身份查询的目标流程没有对应选择入口，因此不复制为 service 特判。

## 发布前分支拓扑审计（2026-09-13）

三个重构分支当前都没有配置 upstream，不能把本地全绿误报为已发布。相对各自本地
`main`，SeerAPI 为 ahead 110 / behind 0；IronsBot 为 ahead 538 / behind 93；private
为 ahead 34 / behind 7。`git merge-tree --write-tree --messages HEAD main` 的只读三方
分析显示：SeerAPI 可零冲突连接主线；IronsBot 有 179 个冲突文件；private 有 6 个冲突
文件。分析只写入不可达 Git tree 对象，没有改变分支、索引或工作树。

IronsBot 的大部分冲突来自目标态删除旧插件目录、迁移 OneBot adapter 和重写 service
边界，不应通过普通 merge 将旧路径恢复。最终发布顺序固定为：先发布 SeerAPI 数据与
`generated-render-assets`，验证 release；再发布 IronsBot 消费端并运行真实 consumer /
候选镜像 smoke；最后发布 private 扩展。连接主线历史前必须先完成逐提交语义清单，随后
使用经明确批准的历史收口策略，而不是逐个文本冲突盲选。QQ 号、绑定、直接 @ 和实时
昵称仍排在最终平台批次。本轮未执行 fetch、pull、merge 或 push。

## 私有阵容差异收口（2026-09-13）

私有主线中仍有两项平台无关行为未被目标态覆盖：阵容精灵的大师池费用展示，以及阵容
封包异常的有限重试和结构诊断。公共仓库以 `ae9145e2` 暴露发布数据库中的
`master_pool_cost`，并以 `60f0d3b2` 在底层请求自行完成超时排空后最多重试一次；不使用
外层取消，不会把迟到响应错配给后续请求。私有仓库以 `65e626e` 使用运行时生成的费用
徽标完成展示，没有复制主线静态字体或图片；以 `6c74437` 保存有界封包诊断并向用户返回
明确失败信息。

公共仓库全量 `3241 passed, 7 skipped`，私有扩展联合 V5 宿主 `45 passed, 1 skipped`；
两仓 Ruff、BasedPyright、compileall 和差异检查通过。该收口不增加 TOML、数据库、静态
资源或 QQ 身份能力。依赖 QQ 号、直接 @、绑定关系或群成员身份且目标 API 无法忠实表达
的入口继续留到最终平台阶段，不阻塞平台无关验收。

随后尝试用本机保留的真实发布产物复跑 `player_lineup` 原生验收，但现存
`v5-release-acceptance*` 与 `v5-full-publication/seerapi-data.sqlite` 均发布 manifest
contract v2，当前消费者严格要求 v3，因而在数据库装载阶段按设计失败，尚未进入阵容
查询。历史 118 MiB 数据库没有发布 manifest，仅可作为生成器缓存输入。此失败不能用
单元测试替代为通过，也不应恢复 v2 兼容；下一次有效证据必须来自当前 SeerAPI 分支
生成的完整 v3 release，再执行同一原生测试。现有公共/私有全量回归结果不受影响。

同日随后使用线上 `api-data` latest 基础库、本机历史库恢复的 `2108` 个效果图标 PNG，
以及当前 SeerAPI 分支重新构建发布主体。构建没有启动 FFDec，产出 121.09 MiB、149 张表
的 manifest v3 数据库；补写新内容索引后发布契约通过，当前周期为 `2026-09-11`，收录
360 项新内容。该数据库仍诚实声明 `complete_scopes=["type_matchup"]`，因为 11 个 Flash
座驾 PNG 和真实 generated mount revision 尚未封口。

以该 v3 数据库和当前私有扩展执行 `player_lineup` 原生消费测试，真实 SQL、公共阵容
事实解析、私有 HTML/Pillow 渲染、OneBot 编码及受限平台图片上传链路 `1 passed`
（12.32 秒）。由于 `player_lineup` 尚非完整素材 scope，本次不宣称最终图片缓存命中或
完整 release 发布；下一门仍是生成并发布 11 个 mount 缺口、封口不可变 manifest 后
复跑缓存一致性。

真实 mount 计划进一步确认上述 11 个官方 SWF URL 全部返回 404。此前计划只按“PNG
缺失”决定安装 FFDec，导致任何其他数据变化触发构建时都先准备 Java/FFDec，再发现没有
可渲染源。SeerAPI `09d66dc` 将源可用性探测提前到 renderer 门：全部为明确 404 或无效
SWF 时输出 `renderer_required=False`；存在可下载 SWF、HTTP 非 404 或瞬时网络错误时仍
保守启用 FFDec。当前真实计划为 `mounts=11 candidates=11 renderer_required=False`，
SeerAPI 全量 `338 passed`，Ruff、compileall 与差异检查通过。生产代码净增 34 行，无新
依赖、缓存协议或镜像内容；11 项仍保留为 pending，不伪造图片或完整 scope。

随后按现有统一图片获取方式复核这 11 项：当前素材 revision 中有 9 项虽然缺少
`cloth/prev/{id}.png`，但存在有效的官方 `cloth/icon/{id}.png`。SeerAPI manifest 与
IronsBot `SeerImageSource` 同步采用“完整预览、官方图标、生成 PNG”的有序候选，不使用
编号名单，也不把素材复制进机器人。真实清单解析后 36 个座驾中 34 个可用，仅
`1301150`、`1301170` 仍无任何 Unity PNG 且 Flash URL 为 404。SeerAPI 全量
`339 passed`，IronsBot 全量 `3241 passed, 7 skipped`；机器人依赖和镜像载荷不变。
同一真实 v3 数据库重建座驾 manifest 后，Flash 计划由
`mounts=11 candidates=11` 收缩为 `mounts=2 candidates=2`，且两个 SWF 均确认缺失，
因此仍输出 `renderer_required=false`，不会安装 Java/FFDec。

随后完成 Python 3.11 运行基线收口：项目最低版本、Docker 构建/运行阶段、发布 CI 和
BasedPyright 使用同一版本；Dockerfile 通过一个 `PYTHON_VERSION` 参数维持两阶段一致，
并继续固定 Debian Bookworm。Python 3.10 的 `tomli` 兼容分支和锁文件中的
`backports-asyncio-runner` 已删除；Ruff 暂时保留 `py310` 语法风格目标，避免把运行时升级
混同为 198 项无关机械改写。隔离 CPython 3.11.15 环境全量结果为
`3241 passed, 7 skipped, 2 warnings`，专项 `90 passed`，BasedPyright 零错误；冻结运行
导出不再包含上述兼容包。该证据不替代新候选镜像的 Linux 体积和 digest 验收。期间仅
只读核对本地 `main` `55a39fd1`，没有 fetch、pull、merge 或 push。QQ 号、直接 @、绑定
及群身份等目标 API 无法忠实表达的工作继续延期到最终平台阶段。

发布工作流随后将 Python 小版本收成单一环境值，并同时传给 setup-python、冻结依赖审计、
候选/正式 Docker 构建及候选容器。离线 smoke 在镜像内部读取 `sys.version_info`，版本不符
会在仓库登录前失败。工作流 YAML、shell 引号、25 项专项、Ruff 和 BasedPyright 通过。
本机 Docker daemon 在有界探测内没有响应，因此该项只增强可执行发布门，不冒充新镜像
体积或启动证据。

异常状态图片也完成发布链路收口。SeerAPI 从 `battle_effect` 事实表生成
`battle_effect/<id>` 素材 manifest 条目，使用与其他 Unity 图片相同的不可变仓库 revision；
这类查询插图不参与精灵渲染 scope 完整性，单个缺图不会误伤其他渲染。IronsBot 删除
`seer-unity-assets/main/.../abnormal` 可变直连，统一经 `SeerImageSource` 使用发布 revision、
双源下载、校验磁盘缓存和并发控制。没有复制 PNG、增加 SQLite 表或运行依赖。SeerAPI
全量 `340 passed`，IronsBot 全量 `3243 passed, 7 skipped`；两仓 Ruff、BasedPyright（适用
仓库）、compileall 和差异检查通过。新 manifest 需随下一次数据 release 发布后才进入生产。

群星牌卡面随后也复用同一发布链路。业务服务不再拼接
`seer-unity-assets/main` URL，只保存由官方 `picID`/卡牌 ID 推导出的
`autocard_card` 或 `autocard_role` 资源 key；应用侧通过 `SeerImageSource` 按当前
SeerAPI release 声明的不可变 revision 下载，继续共享双源回退、校验磁盘缓存、内存缓存
和并发限制。新增内容菜单也改读同一资源 key，因此其最终渲染缓存重新具备确定性。图片仍
留在 Unity 资源仓库，没有复制进机器人代码或 SQLite。依赖 QQ 号的入口没有纳入本批次。

QQ 官方预览运行时随后移除自身的命令元数据副本。适配器只把 OpenID 事件转换为统一
`ActorRef` / `ConversationRef`；冻结后的 `CommandCatalog` 负责输入认领、feature 与权限，
便携执行注册表只按命令 ID 提供平台无关业务函数。安装时机从应用组合阶段移到插件贡献
完成并冻结目录之后，因此帮助、关于和赛尔数据命令不再在两个目录中分别维护示例与说明。
后续扩展精灵、刻印和榜单时必须沿用同一执行注册机制，不能向 QQ 适配器添加专用命令表。

QQ 官方查询随后扩展到精灵/立绘、刻印/宝石、套装/部件/称号以及属性/异常状态。
这些入口继续由 `CommandCatalog` 认领文本，并直接复用现有 Seer 查询 service；新增的
平台无关候选会话只负责把 `QueryResult` 转成数字菜单。会话以
`(ActorRef, ConversationRef)` 隔离、在内存中限时保存，支持 `1..N` 选择和 `0` 退出，
不新增 SQLite，也不复制 OneBot matcher 的业务逻辑。

QQ 官方平台只提供不透明 OpenID。群聊成员、C2C 用户和群会话分别使用带作用域的
`ActorRef` / `ConversationRef`，不得还原、猜测或互相等同为普通 QQ 号。额度、绑定、
订阅等后续身份状态必须以该平台身份键保存；如果需要关联 OneBot QQ 号，必须由用户
显式完成跨平台身份链接。

便携路由随后改为直接接收 `MessageInputContext`，不再由适配器分别传入文本、用户、
群和角色。QQ 官方群事件的 `member_role` 进入同一个 `CommandContext` 权限判断；领域
参数保留原始内部空格并由各自解析器处理，修复多战队 ID 被路由层拼接的问题。战队
详情及巅峰池、投票、套装/称号/精灵榜均复用现有 service 和 `OutboundMessage`，没有
添加官方平台专用业务实现。战队资源订阅仍不在官方平台开放，因为该流程需要尚未
验收的主动消息能力；直接战队查询不会展示一个无法完成的订阅入口。

QQ 官方米米号入口进一步复用既有 `PlayerIdResolver`、`PlayerService`、绑定仓储、
额度和详情查询服务。群事件的非机器人 `mentions[].member_openid` 转换为当前群作用域
的 `ActorRef`，因此数字、已开放别名、默认绑定和直接 @ 一名已绑定成员均沿同一解析
路径；不读取或猜测普通 QQ 号。显式“绑定米米号…”在既有更改冷却校验通过后直接完成
绑定或替换，避免为某个平台复制绑定状态机。玩家详情继续使用平台无关数字菜单，发送
成功后才记录查询额度并启动后台预热；传输失败不会把未送达结果记为成功。群成员
`member_openid` 与 C2C `openid` 仍是两个独立身份，只有未来显式账号关联流程才能合并。

QQ 官方公开榜单入口随后接入同一便携执行注册表。全服榜、样本榜、指定名次/范围、
分数反查和玩家排名直接复用 `RankQueryService`；榜单帮助继续由冻结后的命令目录生成。
`CommandContext` 现携带平台无关的直接成员提及，因此“成就榜”和“成就榜 + @成员”
可在目录认领阶段可靠区分，执行阶段仍交给同一个 `PlayerIdResolver`，没有按消息文本
或时间猜测身份。榜单玩家查询新增延迟投递提交：官方适配器发送成功后才记录实时查询
额度，发送失败不计入；OneBot 的既有调用行为保持不变。缓存管理和批量刷新暂不向官方
平台开放，避免在首个被动消息版本中暴露尚未验收的长任务与主动进度推送。

QQ 官方活动查询随后接入同一便携执行注册表。`快结束活动`、`新增活动` 和超级管理员
`/当前活动` 直接复用 `ActivityService` 与冻结后的 `CommandCatalog` 权限规则；适配器
没有复制活动筛选、格式化或权限判断。便携路由在目录认领阶段保留原始 `/`，执行阶段
再使用规范化文本，因此能够区分必须带斜杠的管理命令和普通聊天。活动定时提醒尚未
宣称完成：虽然统一出站端口已具备 QQ 官方主动发送能力，但真实应用权限、额度以及官方
平台订阅目标仍需验证。`core` 插件清单不拥有活动功能，因此代码默认 feature 保持最小；
使用 `full` 清单的部署可在账号级 `features` 显式启用
`seer_activity_query`。

配置型被动消息随后复用同一便携执行注册表。无 OneBot `at_user_ids` 的
`messaging.commands` 直接返回配置文本；`messaging.sendpic.configs` 继续通过共享
`SendpicService` 读取 local/CNB 后端并产生 `BinaryImagePart`，QQ 适配器只负责上传。
命令目录与执行表按同一命令 ID 求交，所以未启用 feature、未配置以及依赖数字 QQ 提及
的动作不会出现在官方帮助或被官方路由认领。图片未复制进代码或镜像，也没有新增依赖、
SQLite 或平台专用业务实现。推送订阅菜单、定时目标和主动发送策略仍作为后续跨平台
订阅接口处理，不与本次被动命令混合。

QQ 官方鉴权随后对齐 `tencent-connect` 官方 SDK：部署配置仅接收 AppID 与
AppSecret，由适配器调用 `getAppAccessToken` 获取短期 AccessToken、缓存在内存并在
到期前刷新。`nonebot-adapter-qq 1.7.2` 的配置模型仍声明已弃用的静态 `token` 字段，
bootstrap 只为满足该内部模型传入空字符串，不再把它暴露为 IronsBot 配置或环境变量。

B站被动历史查询随后接入同一便携执行注册表。`动态` 复用现有账号权限、Cookie、
历史库、详情补全和 `OutboundMessage` 渲染，并通过通用 `PortableQuerySessions` 提供
可重复选择的数字菜单；远程图片不进入机器人仓库或镜像。主动动态推送、账号订阅和
推送模式修改仍等待跨平台主动目标模型完成，不因被动查询可用而宣称完成。

本周新增内容整组被动查询随后接入便携执行注册表。命令 ID、自然语言别名、内容分类、
依赖 feature 和帮助说明收口为 `NewContentCommandSpec`，由命令目录、OneBot matcher
与 QQ Official 执行共同读取，不再维护三份分类表。根分类、聚焦分类和条目详情复用
同一个短会话；QQ Official 使用数字菜单，详情继续调用现有精灵、皮肤、技能、刻印、
装备、成就和群星牌服务。该项未新增数据库、素材或镜像依赖。

群星牌公开配置、圣域/祝印和刻印数值榜随后接入同一便携执行注册表。群星牌候选与
圣域到效果的两级选择复用 `PortableQuerySessions`；刻印数值榜直接复用领域解析器与
查询服务。组合根只在冻结后的命令目录包含对应命令族时才构造这些操作，精简清单不会
被迫初始化无关服务。该项同样没有新增运行依赖、SQLite、图片或镜像资源。

QQ 官方被动回复序号随后按 `tencent-connect/qqbot-nodejs` 的传输约束收口。每个入站
消息 ID 在进程内原子分配 `msg_seq=1..4`，并使用有界 LRU 与一小时窗口避免状态无界
增长；并发回复不会复用序号。额度或窗口耗尽时，只有部署者显式启用主动消息才移除
入站消息 ID 降级发送，否则返回明确的永久失败。该状态纯属短期传输幂等信息，不写入
SQLite，也没有引入 Node.js 运行时或复制腾讯 SDK。

QQ 官方主动目标随后接入共享 feature policy。部署者先在唯一的 `[identities.groups]` /
`[identities.users]` 目录声明带账号作用域的 OpenID，再在
`bot.qq_official.accounts.<alias>.group_policy` / `user_policy` 中以逻辑别名声明目标及附加
feature；裸 OpenID 不再作为策略 key；
定时消息、活动/B站推送、重试、退订和时间偏好继续复用平台中立服务与同一个状态库。
`TD`、`退订`、`订阅` 和 `推送时间` 已进入便携命令路由，普通群成员只读，群管理者
与超级管理员沿用命令目录权限。该项不新增依赖、SQLite 或图片资源。真实主动消息权限、
发送额度和时间窗口仍须以腾讯应用实机验收，不能由单元测试代替。

对 `tencent-connect/openclaw-qqbot` 多账号实现的审计确认：OpenID 属于具体 AppID，
多账号不能只扩展凭据列表。目标 `ActorRef` / `ConversationRef` 必须增加账户命名空间，
并同步覆盖持久化主键、会话键、feature policy、Token/网关、回复序号和出站路由。
账号别名只用于配置引用，Secret 环境变量直接以 AppID 为后缀；运行时以 AppID 作为账户命名空间，避免用字符串
拼接或默认账号回退制造不可逆的身份串号。

账户感知的基础已经实现：核心 `ActorRef` / `ConversationRef` 可携带 `account_id`，
QQ Official 入站使用实际连接的 AppID 建立身份，逻辑身份策略解析到同一账户的 OpenID
命名空间，出站器会拒绝属于其他 AppID 的目标。共享状态库的 actor、conversation、
操作人和提醒对象均已把独立账户列纳入主键，并提供停机、原子、可校验的 v2 迁移；
检测到旧 QQ Official OpenID 时必须由部署者提供其原 AppID。TOML 现以
`[bot.qq_official.accounts.<alias>]` 声明多个账号；每个账号独立注册 WebSocket、
凭据、逻辑身份 policy、默认 feature、超级管理员、主动消息权限和回复序号。出站目标
必须明确携带原 AppID，不允许默认账号回退。当前 Python 适配器的 sandbox 仍是进程级
配置，因此同一进程中的账号必须连接相同的正式或沙箱环境。

跨平台配置目标最终收口到唯一的 `[identities.groups]` / `[identities.users]` 目录。
每个逻辑目标同时声明可选 QQ ID 与按官方账号别名区分的 OpenID；官方账号配置不再
重复保存目标别名。统一解析器只产出带 platform、AppID 和目标 ID 的类型化引用，裸官方
OpenID 不得进入无法表达所属 AppID 的全局推送目标。B站配置目标因此删除 OneBot 专用编译器，
同一份 `bilibili.push` 可安全包含 OneBot 与官方 QQ 目标；`动态`、`B站账号` 和群/私聊
`B站推送模式` 也共用便携执行注册表。该提交未增加依赖、SQLite、图片或镜像内容；
Ruff、BasedPyright、compileall、差异检查通过，全量 `3362 passed, 7 skipped`。腾讯官方
多账号实现明确要求每个账号独立连接和 Token 缓存，Bot A 收到的 OpenID 不能由 Bot B
发送，本次结构遵守该限制；真实主动消息权限与平台额度仍留作最终实机验收。

同一条全局 Feature policy 会展开到逻辑目标的所有已声明端点。静默 NapCat 观察使用
同群、可信官方机器人 QQ、唯一 @ 对象、规范化回复和短时间窗口匹配；一次完整匹配后
把 `member_openid` 与 QQ 号写入状态库。同一官方账号下相同 `member_openid` 跨群共用
一个身份主体，群只保留为验证证据。普通用户不写入 TOML，静态 owner 等启动前必须
已知的身份才在 `[identities.users]` 声明。

可移植命令路由随后按领域拆分：`PortableCommandRouter` 仅保留权限筛选、会话选择、
AI fallback 和结果归一化；数据、战队、榜单帮助、精灵、刻印、装备、属性、异常与巅峰
操作统一由 `portable_seer_commands` 使用现有 parser/service/session 装配。主路由由 739
行降至 468 行，新模块 320 行，没有改变命令、feature、回复或缓存行为，也没有增加运行
依赖、配置、数据库、素材或镜像层。专项 `142 passed, 7 skipped`，全量
`3363 passed, 7 skipped`；Ruff、BasedPyright、compileall、结构和差异检查通过。真实
QQ Official AppID 联机与平台权限仍是 Phase 7 的最终验收门，总进度保持 7/8。

B站超级管理员手动刷新随后进入 portable router。OneBot 与 QQ Official 现在共同调用
`BilibiliMonitorService.manual_refresh()`，并统一区分“完成、已有任务执行中、远端响应
无效”三种结果；旧 OneBot 路径不再把已执行但 HTTP/Cookie 响应无效的检查误报为完成。
完整示例目录 75 条命令中已有 60 条具备 portable executor；剩余项明确属于数字 QQ
幸运橱窗账户、长任务进度投递或群榜单设置，不以伪映射接入。专项 `75 passed`，全量
`3368 passed, 7 skipped`；Ruff、BasedPyright、compileall、结构和差异检查通过。没有
新增运行依赖、配置、数据库、素材或镜像层，真实平台验收门不变。

群级榜单默认显示条数随后接入 portable rank service。`/榜单显示 N` 继续由同一 command
contract 解析和授权，QQ Official 普通成员不可认领，群主、管理员及精确配置的群超级
管理员才可执行；写入时保留 `(platform, AppID, group OpenID)` 会话主键和完整操作者
ActorRef，不使用数字 QQ 映射或默认账号。专项 `55 passed`，全量
`3370 passed, 7 skipped`；Ruff、BasedPyright、compileall、结构和差异检查通过。完整
示例目录的 portable 覆盖提升到 61/75，没有新增运行依赖、配置、迁移、数据库、素材或
镜像层，真实平台验收门不变。

长任务回复随后收口为通用的 portable 延迟回复契约。服务沿用既有 progress callback，
适配器把第一条进度消息作为发送门：平台确认送达后才释放实际任务，发送失败则取消挂起
任务；任务完成后使用同一入站事件的下一条回复序号发送最终结果。`/刷新样本` 首先接入
该契约，空缓存仍直接返回单条错误，QQ Official 普通用户仍不能认领超级管理员命令。
示例目录的 portable 覆盖提升到 62/75；没有新增运行依赖、配置、数据库、素材或镜像层。
专项 `695 passed`，全量 `3373 passed, 7 skipped`；Ruff、BasedPyright、compileall、
架构和差异检查通过。

对 `tencent-connect/qqbot-agent-sdk`、`qqbot-nodejs` 和 `openclaw-qqbot` 的历史审计最终由
提交 `c66eec1b` 落地：QQ Official 传输已从旧 NoneBot 适配器替换为腾讯纯 Python SDK，
portable command、身份、feature policy 和业务服务契约未改变。每个 AppID 独立维护
AccessToken、连接、Session 与 OpenID 命名空间；SDK 负责心跳、Resume 和进程内消息 ID
去重。`GROUP_MESSAGE_CREATE` 是否实际下发仍由腾讯应用权限和当前 SDK 支持决定，代码
存在不能代替真实平台授权。尚未关闭的回复时限、连续 `msg_seq`、结构化错误、READY
健康状态和媒体上传验收记录在协议基线 Spec 中。

跨平台身份最初实现为显式令牌协议，随后收口为同一身份仓库的三种精确来源：部署配置
别名、显式短时单次令牌，以及可信官方机器人 source `message_reference` 的静默群观察。
静默观察由 NapCat 读取被引用原消息的数字发送者，并要求同一逻辑群内一次唯一且
一致的匹配；歧义、超时、来源不可信和既有冲突均失败关闭。C2C `user_openid` 与群
`member_openid` 仍是不同身份作用域，一个精确官方身份不能静默改绑。实现不使用昵称、
头像、模糊内容、裸时间、未引用发言记录或 `union_openid` 猜测。详见
[跨平台身份关联 Spec](specs/2026-09-15-cross-platform-identity-linking.md)。

全服榜单维护命令随后复用同一 portable 延迟回复契约。`/刷新榜单` 与
`/缓存榜单 …` 会先发送进度回执，平台确认送达后才开始无头客户端请求，完成后再发送
最终统计；区间缓存的进度文案改为请求前可知的策略上限，实际写入数量只在最终结果中
报告。OneBot 与 QQ Official 共用 `RankAdminService` 的相同时序，不存在官方平台专用
分支。完整示例目录的 portable 覆盖提升到 64/75；没有新增依赖、配置、数据库、素材
或镜像层。专项 `110 passed`，全量 `3376 passed, 7 skipped`；Ruff、BasedPyright、
compileall 和差异检查通过，真实平台验收门不变。

数据与镜像只读维护随后接入 portable router。`/更新数据`、`/强制更新数据` 的远端检查
和菜单选择后的实际同步各自使用一次送达门，避免平台尚未确认进度回执时就触发构建或
下载；通用数字菜单因此可以返回 `PortableReply`，不是数据更新专用分支。
`/检查更新镜像` 同样先回执再访问镜像仓库，并保持只读。OneBot 也改用相同的
progress-aware service API。覆盖提升到 67/75，剩余 8 条是两条需要“最终消息送达后
执行重启”的维护命令及 6 条依赖数字 QQ 账户配置的幸运橱窗命令。该增量没有新增依赖、
数据库、配置字段、二进制素材或镜像层。专项 `119 passed`，全量
`3381 passed, 7 skipped`；Ruff、BasedPyright、compileall 和差异检查通过。

其余 8 条 portable 命令随后完成。`/重启机器人` 与 `/更新镜像` 只有在准备回复
确认送达后才执行副作用；幸运橱窗的查询、关注列表、新增、取消、清空和重置通过
显式跨平台身份关联解析到原有 OneBot QQ 账号配置。缓存缺失时先使用共享按钮确认，
皮肤详情与重名皮肤也使用同一会话和具名按钮。没有昵称、头像、发言记录或 OpenID
相似度猜测，也没有复制登录、缓存、关注或皮肤查询实现。原 75 条示例目录命令均已有
portable 执行路径；新增的平台专属身份命令按各自 `platforms` 归属单独计算。现有 TOML、
env、Docker 和 Unraid 配置无需迁移，真实 AppID 的联机验收仍留在最终外部验收门。

命令覆盖不只依赖人工维护的数字。完整 QQ-enabled bootstrap 会构造 portable router，
并校验目录中的每条 QQ Official `direct` 契约都有执行器或明确的内建处理；缺失项会在
构造时列出命令 ID 并失败。当前目录为 75 条官方直达命令，即 72 条共享业务命令加上
3 条官方身份命令；同一业务命令的文本别名不重复计数，OneBot 专属的令牌签发命令
不计入。平台专属归属和自动/被动行为
由 `CommandContract` 自身声明，不用另一份容易漂移的手写矩阵。

竞技池、专家池和大师池的直接查询随后恢复主线完整渲染语义。基础命令与“变化”别名
共用同一个 `PeakPoolRenderSnapshot`：业务服务把当前池和发布库中的周变化组合为不可变
快照，集成层一次加载并灰化历史头像，纯渲染层负责旧位置、当前位置和方向箭头布局。
因此 QQ Official 与 OneBot 收到相同图片，不再由“变化”命令返回另一套文本结果。
周变化索引不可用时仍展示当前池，并明确标注变化数据暂不可用；没有恢复旧文本 renderer
或平台分支。本项不增加配置、数据库、素材或依赖。

帮助菜单随后改为共享的二级交互目录。OneBot 与 QQ Official 都从冻结后的插件贡献目录、
命令目录和同一 `PortableQuerySessions` 生成可见功能；首屏按领域列出功能，选择序号或
官方按钮后进入该功能的命令详情，并可继续选择或退出。旧的 QQ Official 扁平
“机器人调试功能”输出及平台专属帮助可见性判断已删除。组合根显式传入帮助目录和
会话资源，不存在空目录回退；本项不增加配置、数据库、素材或依赖。

此前因 QQ 身份语义延期的玩家所属战队入口也已收口。玩家详情目录注册一个共享
`player_team` action；OneBot 和 QQ Official 都将当前 actor、conversation 与管理权限
传给同一个 `SeerTeamQueryService`，由它先读取玩家所属战队，再复用完整战队详情查询。
没有复制旧 OneBot matcher、按昵称猜测身份或平台专用格式化；未加入战队、超时及
无头连接异常都有明确结果。本项不增加配置、数据库、素材或依赖。

B站登录二维码通知随后移出 OneBot 集成目录。登录服务不再通过
`BotRouter.default_bot()` 猜测通知是否可送达；二维码和文字统一构造成
`OutboundMessage`，交给 `AdminNoticeService` 与共享主动投递路径处理。组合函数同步
去掉误导性的 `onebot` 命名，旧 `integrations.onebot.bilibili_auth` 文件直接删除，
不保留兼容导入。这样只连接 QQ 官方 SDK 的进程不会再被错误判定为“没有机器人”，
而没有管理员目标或主动发送权限时仍由统一投递层返回明确失败。官方单账号开发进程
随后重新进入 `READY`；登录失效检查只报告“没有管理通知目标”，未再查找 OneBot
实例，也没有向普通会话发送二维码。
