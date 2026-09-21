# V5 上游 Main 功能同步

Status: `implementing`

Contract: `transition`

Owner: `各领域 service、repository、render presenter 与 OneBot adapter`

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#change-design-gate)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

本地只读 `main` 当前为 `af2e8810`，其中包含活动周快照、竞技池变动、幸运橱窗展示、
Docker 维护菜单、更新确认和玩家绑定限制等行为。V5 已将插件、命令目录和运行时
装配迁至新的目标边界；直接合并会恢复已退役目录，或将新功能的一半代码留在旧路径。

## Goal

### Binding Confirmation And Command Inventory (2026-09-15)

重新比较原版 81 项与目标版 78 项目录声明，完整清单和非目录功能范围见
[命令迁移核对表](2026-09-15-command-parity.md)。同名 ID 不代表参数和交互已验收。
本轮发现并修复共享绑定操作自动确认已有绑定替换的回归：现在显示“确认换绑 /
保留原绑定”，确认前不写入；退出也保留原绑定。两平台复用现有 PortableMenuSpec，
详情展示及查询额度回调仍在实际发送成功后执行。管理员代绑定行为不变。
后续继续补部分账号别名候选选择和固定图片部署配置，配置 schema 无变化。

### Shared Lucky Window Watch Management (2026-09-15)

查看、添加、删除、清空及重置关注全部使用共享 portable operations。OneBot 仅保留
命令匹配、Feature 检查和通用会话适配；删除独立 watch handler、专用候选菜单、
重复绑定错误回复及不再消费的 matcher 参数状态。查询与关注操作在插件安装时
统一构建，同名皮肤选择使用两平台共用的会话和数字/按钮入口。

关注始终属于当前已确认关联的用户，不随管理员查询目标改变。测试覆盖两平台的
五种操作、同名选择、未关联身份不读取或改写偏好、绑定不匹配提示，以及原有
SQLite 持久化与命令唯一归属。没有新增配置或依赖。橱窗查询和关注流程现已收口；
全量口令参数矩阵与真实平台验收仍未完成。

### Explicit Lucky Window Targets (2026-09-15)

恢复原版指定米米号、账号别名及直接 @成员的橱窗查询。共享 `LuckySkinQuery`
分别携带操作者、已确认关联的个人身份和目标游戏账号；缓存检查与确认后的查询
通过同一个授权入口。普通用户只可查自己的已配置账号，超级管理员可以查询账号库
中配置了登录凭据的账号，无需本人订阅。不存在 OpenID 推算 QQ 号或按昵称猜测身份。

查询、关注及退订按现有命令声明的最长前缀归属，避免“橱窗订阅”被查询入口抢占。
结果关注星标沿用原版查看者的偏好；无个人订阅的管理员得到不带个人星标的结果，
查询不会读取目标用户的关注设置。删除旧 `check_for_actor` / `cached_for_actor`
查询入口，两平台使用共享操作、确认菜单与图片结果。README 已同步，配置字段不变。
真实官方成员提及、平台权限及其余命令差异仍须验收。

### Shared Lucky Window Query (2026-09-15)

OneBot 的橱窗查询现使用 `build_portable_lucky_skin_operations` 和通用
`make_portable_query_handler`。删除该插件内重复的登录确认、登录异常处理、
结果图片转换和皮肤详情选择流程。两端均先查缓存；未缓存时通过共享确认菜单
发起查询，取消不会登录。数字选择和按钮由统一会话与平台能力适配。

保留每日调度及关注管理的现有行为；关注管理尚有独立 OneBot handler，后续仍需
收口。指定账号橱窗查询尚未恢复：主线允许超级管理员查询已有专用账号，目标版
当前只支持本人配置。下一步应统一账号目标解析及授权，再由上述共享查询流程消费。
本次无需调整 TOML、env、Docker 或 Unraid。测试覆盖两端共享查询、确认与取消、
缓存、皮肤详情，以及 NoneBot 安装和命令目录；这不替代真实平台验收。

### Administrator Binding Parity (2026-09-15)

原版 `plugins/seer/query/commands/player.py` 的绑定命令把直接 @ 作为绑定收件人，
仅允许超级管理员在群聊中为单个成员绑定。目标版现由共享
`build_portable_player_operations` 实现同一行为：`绑定米米号123456 @成员` 或
`绑定米米号别名 @成员`。OneBot 通过通用 portable query adapter 执行该操作，
删除独立绑定 handler；QQ Official 使用同一操作和结构化 ActorRef。

玩家引用和收件人分别解析。缺少米米号、多个收件人、私聊 @ 或非超级管理员请求
明确拒绝；不会读取被 @ 成员的米米号再绑定给操作者。管理员替成员绑定沿用原版
免换绑冷却行为，但查询仍归操作者，普通自助绑定仍检查冷却。此操作只设置游戏
账号偏好，不建立 OpenID 与 QQ 号的身份关联。

验证包括官方共享命令权限与目标解析、OneBot 安装、两平台身份的 SQLite 持久化
和查询归属。真实官方消息中的成员提及能力仍以平台事件及实机验收为准。
无需迁移 TOML、env、Docker 或 Unraid。指定账号橱窗查询及全量参数化命令
对照仍待完成，不能据此宣称原版所有命令已等价迁移。

在不恢复已退役 `command_directory`、旧 `plugins/*`、旧 runtime registry 或 renderer
数据访问的前提下，逐项把仍有产品价值的主线行为迁入 V5。每一项在 V5 内拥有唯一
semantic owner、真实的用户契约和针对性验证。

## Non-Goals

- 不把一次 Git merge 成功视为功能完成。
- 不因本 Spec 而自行 `fetch`、`pull` 或 `merge` `main`；默认只读取本地 `main`。
- 不复制旧 renderer 预览矩阵来替代 V5 的 immutable render document。
- 不将主线暂时未验证的实现或测试夹具带入 V5。

## Ownership And Reuse

- Semantic owner: 行为归各自领域 service；OneBot 插件仅适配事件和发送结果。
- Reused contracts: `CommandCatalog`、`CommandContract`、`TaskOwner`、Seer
  repositories、immutable render document 与现有 outbound ports。
- Adapter boundary: OneBot matcher 不拥有命令语义、持久化或渲染数据读取。
- New interface: 仅当某一上游行为无法由既有窄接口表达时再建立；不能以同步为理由
  新增 registry 或万能服务。

## User And Data Contract

- Inputs: 当前本地只读 `main` 的已审计提交及其公开用户行为。
- Outputs: 与主线相同或明确改进的可观察行为；失败时保留 V5 的真实错误语义。
- Permissions and scope: 复用 V5 feature policy 与 command catalog，不复制旧 matcher
  的权限判断。
- Persistence: 仅在对应功能 Spec 明确 schema、迁移与备份后变更。
- Compatibility: V5 是唯一运行路径；旧主线路径不进入正常读取或启动路径。

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| Bilibili 正文补全与历史摘要 | 缺正文与截断 Opus 使用详情补全；推送和历史详情复用同一压缩服务，摘要持久化且按需生成 | 无 | completed |
| 开服别名与竞技池变动入口 | 命令由 V5 service contract 提供，数据由 repository 提供 | 无 | completed |
| 活动周快照 | 只通过活动 service 与 runtime-state 事实存储实现 | 无 | verified |
| 竞技池、专家池与大师池变动渲染 | seerapi 发布周内变化事实和官方有效期；机器人经 presenter 产出不可变 document，再接 HTML renderer | 无 | completed：直接查询与新增内容根图均保留变化图；2026-09-20 审计补回曾在 renderer 拆分时丢失的根图矩阵 |
| 巅峰投票展示增强 | service 提供投票级别与周期；纯 presenter 计算总票数和占比；renderer 只消费不可变 document | 无 | completed |
| 幸运橱窗卡片与价格菜单 | 使用 skin repositories、关注偏好和 V5 prompt 边界 | 无 | completed：价格批量读取发布库，数字菜单复用皮肤详情服务；2026-09-20 审计恢复原版最终布局和价格展示契约 |
| Docker 维护/更新确认 | 使用 operations service、明确管理员权限与确认会话 | 目标平台管理员身份最终验收 | completed：动作与菜单已收口；跨平台身份延期 |
| 绑定限制 | 审计后不迁入：V5 已确认所有米米号入口支持一个直接 @ 用户解析，不能额外要求请求者先绑定 | 无 | superseded |
| Bilibili 抽奖/中奖拆分 | 复用配置驱动分类，不增加硬编码枚举或旧配置迁移器 | 无 | completed |
| 新增技能根菜单预览 | 根预览只含新增项；技能排除本周新精灵自带技能，详情保留完整数据 | 无 | completed |
| 队列推送加固 | 由 `ProactiveMessageDelivery` 限制并发并按通用失败类型重试；平台适配器只分类错误 | 真实平台 smoke | completed：通用策略已完成；真实传输验收延期 |
| 群星牌觉醒卡合并 | 在 Autocard repository/view model 合并普通/觉醒事实，适配器只发送结果 | 发布数据契约审计 | completed |
| 玩家战队菜单与私聊概览 | 复用玩家详情 action、team service 和共享交互会话；当前玩家战队置顶并与订阅去重 | 真实平台按钮与数字回退 smoke | completed：玩家详情 action 与交互式战队概览已由两个平台共用 |
| 战队详情增强 | repository 产出类型化事实，service 决定展示段，不复制旧 matcher 格式化 | 无 | partial：直接战队号详情完成；QQ 玩家目标延期 |
| Docker 交接失败恢复 | 复用 operations 状态机并保留明确失败结果 | 可控 Docker client fixture | completed |
| 旧生产模块拆分 | 不移植旧目录拆分；V5 已由职责边界和 800 行守卫独立完成 | 无 | completed |
| 临时诊断类型排除 | 不移植；V5 类型检查不排除临时生产模块 | 无 | completed |

## Migration And Rollback

- Migration: 每个切片单独评估；涉及状态时使用一次性迁移工具及备份。
- Rollback: 每个切片独立提交；未通过 V5 验收则不替换现有行为。
- Removal condition: 对应主线行为已有 V5 target owner、测试与实际用户路径后，才可在
  阶段账本记为已吸收。

## Acceptance Tests

- [ ] 每个迁入的行为有 V5 路径上的正常、权限与失败语义测试。
- [ ] `CommandCatalog` 没有旧目录来源或重复命令说明。
- [ ] renderer 不导入 ORM 或直接读取数据库。
- [ ] `ruff`、相关 pytest、`compileall` 与 `git diff --check` 实际通过。
- [ ] 不存在已退役 `command_directory`、旧 plugin 或 runtime registry 的运行时 import。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-14 | Bilibili 正文补全 | focused hydration tests, Ruff, compileall | 已由 V5 `7231bae8` 吸收。 |
| 2026-08-15 | 历史自动 merge 尝试（未保留半合并状态） | compile/Ruff preflight | 证明旧/新目录边界不兼容；该记录不授权后续 fetch、pull 或 merge。 |
| 2026-08-15 | 只读比较本地 `main` `af2e8810` 与 V5 | commit/diff/document audit | 仅用于识别产品行为与 V5 owner；当前 V5 未合并 `main`。 |
| 2026-08-15 | 活动周快照 | activity storage/service/command tests, Ruff, compileall | 18 项通过；首次观察明确提示缺少上周快照。 |
| 2026-08-15 | 请求者绑定限制 | `PlayerIdResolver` 与既有用户契约审计 | 不迁入；会缩窄已确认的直接 @ 用户解析能力。 |
| 2026-09-13 | 本地 `main` `55a39fd1` 只读复核 | 最近 30 项提交、差异与 V5 owner 审计 | 未 fetch、pull 或 merge；QQ 身份/投递项按平台能力延期规则留到最后。 |
| 2026-09-13 | 玩家战队菜单与私聊概览复核 | 本地 `main` `6844980e`、`b14df7a5` 与 V5 player/team owner 对照 | 已在显式身份关联完成后落入共享 player/team operation；没有复制旧 OneBot matcher。 |
| 2026-09-13 | Bilibili 抽奖/中奖拆分 | 配置加载、通用分类与订阅回归 | V5 已支持任意配置分类；示例声明独立 `lottery` / `winning`，无生产枚举或兼容迁移。 |
| 2026-09-13 | 新增技能根菜单预览 | service、文本菜单、原生菜单准备与配置链路回归 | 统一 preview selector；修改项折叠，详情菜单不裁剪。 |
| 2026-09-13 | Docker 交接失败恢复 | preflight 状态机、入口脚本、Docker gateway 与配置回归 | 默认等待 90 秒后清理失败更新器并启动当前镜像；可配置为严格等待。真实 Docker 交接仍留待 Linux 镜像验收。 |
| 2026-09-13 | 群星牌觉醒卡合并 | Autocard repository、service、菜单与图片回复回归 | `compose/composeTo` 形成只读变体索引；任一名称或 ID 返回同一组事实，异常关系不合并。 |
| 2026-09-13 | 战队详情增强（非 QQ 部分） | team service、配置与订阅简版回归 | 直接战队号查询补标语、公告与 Boss 剩余能量；订阅提醒保持简版。按 QQ 玩家目标查询延期。 |
| 2026-09-15 | 玩家所属战队详情 | team service、共享玩家菜单、OneBot 会话和 QQ Official portable 路由专项 | 显式身份关联完成后，玩家详情菜单共用 `player_team` action；米米号解析、战队查询与权限上下文不复制到平台适配器。 |
| 2026-09-15 | 当前玩家战队概览 | team resource service、共享查询会话、OneBot 与 QQ Official 入口专项 | “战队”展示绑定玩家战队优先的去重概览；选项复用完整战队查询，单项失败不阻断其余订阅。 |
| 2026-09-15 | 原版用户口令全目录复核 | 本地 `main` 81 项 command descriptor 与目标分支 CommandCatalog、配置型消息动作及 matcher grammar 对照 | 恢复精灵头像、玩家所属战队查询和遗漏口语；大师池/圣域已有统一语法；固定图片保留配置能力但不恢复私有内置素材；官方账号关联与镜像预检是目标分支新增能力。 |
| 2026-09-13 | 竞技池、专家池与大师池变化 | seerapi 317 tests；机器人 focused 327 tests、full 3189 passed/7 skipped、Ruff、BasedPyright、compileall | seerapi `c608ac3`、`dadfe83` 直接使用既有池表和精灵外键发布变化及真实有效期；机器人统一分类、详情、图片与大师池直接查询，不复制旧专用 renderer。 |
| 2026-09-13 | Docker 维护菜单 | operations service、命令所有权、配置与 OneBot 适配专项 143 项；Ruff、BasedPyright、compileall | 两个维护动作具有唯一 service 契约；所有维护入口打开同一菜单，删除 `check_on_restart` 和旧确认双轨。QQ/目标平台管理员身份只在最终平台阶段验收。 |
| 2026-09-13 | 主动推送加固 | outbound core、通用 proactive service、OneBot adapter、目标平台能力与调用方专项 172 项；Ruff、BasedPyright | 有限并发、缩批重试、不确定结果防重发和传输中断止损均由平台无关 service 实现；OneBot 仅分类自身错误。真实 OneBot/官方平台发送仍留到最终验收。 |
| 2026-09-13 | 巅峰投票展示增强 | 巅峰 service、纯 presenter、render adapter 专项 64 项；Ruff | 限制级/准限制级、投票周期、总票数和非负票数占比进入不可变 document；机器人不新增图片资源或数据读取职责。 |
| 2026-09-13 | Bilibili 历史摘要 | 长文本、历史存储、菜单详情、主动投递与运行装配专项测试；Ruff、BasedPyright、compileall | 推送和详情复用 `DynamicContentCompactor`；修正 AI 摘要关键字参数契约，结果写入既有历史库并惰性复用，不执行启动批量 AI 回填。 |
| 2026-09-13 | 幸运橱窗价格与详情菜单 | 价格 repository/service、四栏 presenter、数字 prompt 与皮肤详情复用专项测试 | 四个皮肤价格通过一次发布库查询获取；缺价格时保留卡片并明确降级；选择 1-4 复用统一皮肤详情服务。未打包货币图标或写死资源 URL。 |
| 2026-09-13 | Python 3.11 运行基线 | 隔离 CPython 3.11.15 全量 3241 passed/7 skipped；专项 90 passed；BasedPyright、冻结依赖导出 | 吸收主线平台无关的运行版本目标并统一 Docker/CI/类型检查；未 merge 主线，Ruff 语法风格目标暂不机械升级。 |
| 2026-09-13 | Bilibili 历史详情渲染收口 | Bilibili parser/outbound/plugin/registry 专项测试；Ruff、BasedPyright | 历史查询和主动推送复用平台无关 `OutboundMessage` 组装；删除 OneBot 专用 renderer 与资源回调。动态源图保留为远程图片部件，不错误纳入 SeerAPI 素材发布。 |

## Progress

```text
Program  [███████□] 7/8 verified phases; Phase 7 remains open
Slice    [███████████████□□] 15/17 tracked outcomes resolved; 2 remain
Current  [██████████] Bilibili portable history rendering verified
```

QQ-specific product work remains subject to the platform capability deferral rule.
The remaining planned entries and real platform acceptance are not implicitly
completed by this slice.
