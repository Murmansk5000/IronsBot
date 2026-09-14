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
| 竞技池、专家池与大师池变动渲染 | seerapi 发布周内变化事实和官方有效期；机器人经 presenter 产出不可变 document，再接 HTML renderer | 无 | completed |
| 巅峰投票展示增强 | service 提供投票级别与周期；纯 presenter 计算总票数和占比；renderer 只消费不可变 document | 无 | completed |
| 幸运橱窗卡片与价格菜单 | 使用 skin repositories、关注偏好和 V5 prompt 边界 | 无 | completed：价格批量读取发布库，数字菜单复用皮肤详情服务 |
| Docker 维护/更新确认 | 使用 operations service、明确管理员权限与确认会话 | 目标平台管理员身份最终验收 | completed：动作与菜单已收口；跨平台身份延期 |
| 绑定限制 | 审计后不迁入：V5 已确认所有米米号入口支持一个直接 @ 用户解析，不能额外要求请求者先绑定 | 无 | superseded |
| Bilibili 抽奖/中奖拆分 | 复用配置驱动分类，不增加硬编码枚举或旧配置迁移器 | 无 | completed |
| 新增技能根菜单预览 | 根预览只含新增项；技能排除本周新精灵自带技能，详情保留完整数据 | 无 | completed |
| 队列推送加固 | 由 `ProactiveMessageDelivery` 限制并发并按通用失败类型重试；平台适配器只分类错误 | 真实平台 smoke | completed：通用策略已完成；真实传输验收延期 |
| 群星牌觉醒卡合并 | 在 Autocard repository/view model 合并普通/觉醒事实，适配器只发送结果 | 发布数据契约审计 | completed |
| 玩家战队菜单与私聊概览 | 复用玩家详情 action 与 team service、平台作用域身份 | 共享身份与会话服务 | completed：玩家菜单和群/私聊绑定战队概览均接入，真实平台测试留在发布门槛 |
| 战队详情增强 | repository 产出类型化事实，service 决定展示段，不复制旧 matcher 格式化 | 无 | completed：战队号及统一玩家目标查询均接入；真实平台验证仍属最后验收 |
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
| 2026-09-13 | 玩家战队菜单与私聊概览复核 | 本地 `main` `6844980e`、`b14df7a5` 与 V5 player/team owner 对照 | 直接战队号详情已由 V5 service 覆盖；菜单与私聊概览依赖 QQ 用户绑定和会话身份，按用户确认延期到 Phase 7 最后，不复制旧 OneBot matcher。 |
| 2026-09-13 | Bilibili 抽奖/中奖拆分 | 配置加载、通用分类与订阅回归 | V5 已支持任意配置分类；示例声明独立 `lottery` / `winning`，无生产枚举或兼容迁移。 |
| 2026-09-13 | 新增技能根菜单预览 | service、文本菜单、原生菜单准备与配置链路回归 | 统一 preview selector；修改项折叠，详情菜单不裁剪。 |
| 2026-09-13 | Docker 交接失败恢复 | preflight 状态机、入口脚本、Docker gateway 与配置回归 | 默认等待 90 秒后清理失败更新器并启动当前镜像；可配置为严格等待。真实 Docker 交接仍留待 Linux 镜像验收。 |
| 2026-09-13 | 群星牌觉醒卡合并 | Autocard repository、service、菜单与图片回复回归 | `compose/composeTo` 形成只读变体索引；任一名称或 ID 返回同一组事实，异常关系不合并。 |
| 2026-09-13 | 战队详情增强（非 QQ 部分） | team service、配置与订阅简版回归 | 直接战队号查询补标语、公告与 Boss 剩余能量；订阅提醒保持简版。按 QQ 玩家目标查询延期。 |
| 2026-09-13 | 竞技池、专家池与大师池变化 | seerapi 317 tests；机器人 focused 327 tests、full 3189 passed/7 skipped、Ruff、BasedPyright、compileall | seerapi `c608ac3`、`dadfe83` 直接使用既有池表和精灵外键发布变化及真实有效期；机器人统一分类、详情、图片与大师池直接查询，不复制旧专用 renderer。 |
| 2026-09-13 | Docker 维护菜单 | operations service、命令所有权、配置与 OneBot 适配专项 143 项；Ruff、BasedPyright、compileall | 两个维护动作具有唯一 service 契约；所有维护入口打开同一菜单，删除 `check_on_restart` 和旧确认双轨。QQ/目标平台管理员身份只在最终平台阶段验收。 |
| 2026-09-13 | 主动推送加固 | outbound core、通用 proactive service、OneBot adapter、目标平台能力与调用方专项 172 项；Ruff、BasedPyright | 有限并发、缩批重试、不确定结果防重发和传输中断止损均由平台无关 service 实现；OneBot 仅分类自身错误。真实 OneBot/官方平台发送仍留到最终验收。 |
| 2026-09-13 | 巅峰投票展示增强 | 巅峰 service、纯 presenter、render adapter 专项 64 项；Ruff | 限制级/准限制级、投票周期、总票数和非负票数占比进入不可变 document；机器人不新增图片资源或数据读取职责。 |
| 2026-09-13 | Bilibili 历史摘要 | 长文本、历史存储、菜单详情、主动投递与运行装配专项测试；Ruff、BasedPyright、compileall | 推送和详情复用 `DynamicContentCompactor`；修正 AI 摘要关键字参数契约，结果写入既有历史库并惰性复用，不执行启动批量 AI 回填。 |
| 2026-09-13 | 幸运橱窗价格与详情菜单 | 价格 repository/service、四栏 presenter、数字 prompt 与皮肤详情复用专项测试 | 四个皮肤价格通过一次发布库查询获取；缺价格时保留卡片并明确降级；选择 1-4 复用统一皮肤详情服务。未打包货币图标或写死资源 URL。 |
| 2026-09-13 | Python 3.11 运行基线 | 隔离 CPython 3.11.15 全量 3241 passed/7 skipped；专项 90 passed；BasedPyright、冻结依赖导出 | 吸收主线平台无关的运行版本目标并统一 Docker/CI/类型检查；未 merge 主线，Ruff 语法风格目标暂不机械升级。 |
| 2026-09-13 | Bilibili 历史详情渲染收口 | Bilibili parser/outbound/plugin/registry 专项测试；Ruff、BasedPyright | 历史查询和主动推送复用平台无关 `OutboundMessage` 组装；删除 OneBot 专用 renderer 与资源回调。动态源图保留为远程图片部件，不错误纳入 SeerAPI 素材发布。 |

## Progress

### 2026-09-14 Merge Follow-up

The user subsequently authorized fetching and merging main. Merge `1c2cadc7`
contains `origin/main` `55a39fd1`; a fresh fetch on September 14 found no newer
main commit. The earlier read-only entries above are historical evidence, not
a description of the current Git ancestry. An ancestor relationship does not
prove every old plugin behaviour is wired into the target architecture.

- Bilibili adaptive images now use the existing collage service for both
  portable history queries and scheduled delivery. The composition root owns
  the HTTP/Pillow implementation; adapters receive binary outbound content.
  The main `combine_images` default is restored, with original-image fallback.
- Configured text replies share service-owned content assembly and the same
  receipt-gated reply sequence. OneBot retains only identity resolution,
  legacy final-text newline normalization, and transport adaptation.
- Docker source diagnostics are now wired through the existing metadata/client
  boundary. Remote labels are read at the digest already observed by the daemon,
  not by resolving a mutable tag a second time. The GitHub repository comes
  from image labels, preferring the target, without a deployment fallback.
  Missing labels or GitHub failure preserve the successful digest comparison.
  The shared formatter names the configured target and reference repository;
  different SHAs do not imply that a preview branch is behind main or that a
  build failed. Invalid revisions are explicitly unknown. Registry references
  now preserve digest pins, including references with both a tag and digest.
  Source acceptance: 69 Docker tests and full 3434 passed / 7 skipped, with Ruff,
  BasedPyright and compile checks passing. The read-only tests reject Docker
  mutation calls and cover optional metadata failure, fallback to the current
  image's source label, missing labels, and exact-digest metadata reads. This
  is source-level acceptance, not a claim of live Docker maintenance testing.

```text
Program  [███████□] 7/8 verified phases; Phase 7 remains open
Slice    [█████████████████] 17/17 tracked source outcomes resolved
Current  [██████████] Shared team overview verified; live platform gate remains
```

QQ-specific product work remains subject to the platform capability deferral rule.
The remaining planned entries and real platform acceptance are not implicitly
completed by this slice.

### Player Team Menu Follow-up

Target owner: the shared portable player menu, not the retired OneBot player
conversation implementation. Current platform-scoped actors and the confirmed
base-player snapshot are sufficient for this action: it does not need a numeric
QQ identity or an OpenID-to-QQ map. The prior identity deferral therefore no
longer applies to the team menu itself; private overview remains a separate gap.

- Append one numbered team choice after existing detail/extension choices only
  when the snapshot has a positive team ID, the team service is installed, and
  `seer_team` is allowed. Preserve existing collection/peak/autocard/lineup numbers.
- Reuse the same authorized team query function as a direct team-ID command;
  pass the captured team ID rather than fetching base-player data again. Preserve
  AppID-scoped actor and conversation, group-management checks, team formatting,
  subscriptions and service error results. Recheck feature access on selection.
- Use the team ID as semantic target and the team-query action/cooldown. Do not
  charge player-detail quota or label this as another collection query.
- Wire both the OneBot installer and platform-neutral router. Keep menu ownership,
  numeric-only selection, exit and delivery callbacks in existing session code.
- No new configuration, persistence, dependency, adapter-specific business branch,
  or renderer. The base-profile formatter is unchanged; the team name and ID
  appear in the newly restored menu choice.

Acceptance covers both platforms and group/private contexts, regular/superuser
policy, no team or snapshot, disabled/revoked permission, extension ordering,
shared team query invocation and original player work-accounting callbacks.
Source tests do not substitute for the real official message-matrix gate.

Source verification: 51 focused player/team/session tests passed; the final
full suite passed 3503 tests with 7 skips and 2879 existing dependency warnings.
Ruff, BasedPyright, compileall and diff checks passed. Both production entry
points inject the same team service into the same portable menu; no native
message transport, live account, or real game-server result is claimed by these
fixtures. The separate private-overview slice remains incomplete.

### Direct Player-Team Query Follow-up

Target owners: `PlayerIdResolver`, the Seer command grammar and the shared team
service. Restore the main baseline without copying native plugin logic:

- `战队123456` and space-separated numeric arguments remain team IDs, at most
  three; `战队米米号700001`, an available player alias, or one direct member
  mention resolve a player and query that player's team.
- Catalog ownership and both production adapters use the same grammar. Unknown
  aliases containing digits are not silently converted into team IDs. Bare
  `战队` retains subscription ownership; a member target belongs only to the
  player-team command. Mixed references and multiple mentions use resolver errors.
- Recheck `seer_team` before game access. Preserve actor/conversation scope and
  group management rights through the existing authorized team-query path.
- Fetch player membership with the configured team-query timeout. No team,
  timeout, disconnection and official error results remain distinct. Do not
  create another binding, cache, quota or QQ-number mapping service.
- No new TOML fields, files, dependencies or render resources. The group/private
  overview combining subscriptions with the caller's bound team remains open;
  this slice provides its shared player-to-team lookup prerequisite.

Focused acceptance: 92 team-service, catalog, subscription and installed-rule
tests passed. Full-suite/type checks and real platform acceptance are separate
gates; mocked game responses are not live connection evidence.

Final source verification: 3531 passed / 7 skipped; Ruff, BasedPyright,
compileall and diff checks passed. The 2886 dependency warnings remain visible
(including the added NoneBot rule tests). Fresh fetch/merge again reports main
`55a39fd1` already contained, with no conflict. Overall verified phases remain
7/8; the overview and real platform acceptance are not claimed complete.

### Shared Team Overview

Target owner: the existing portable team-resource operations and numeric session
service. Restore main's bound-team/group/private overview without its native
quoted-message cache or another menu engine.

- Resolve only the caller's default binding, then reuse the shared membership
  lookup. Put its positive team ID first; append current target subscriptions
  in stored order, deduplicating by team ID before fetching.
- Show name, team ID, member count and resource in a numbered overview. Keep
  failed team entries with their stored name and explicit error; membership
  failure does not suppress other subscribed teams. No binding is required.
- Select by number through `PortableQuerySessions`, reuse full team details,
  keep the menu open for another selection and support `0` exit. The semantic
  target is the selected team, not the caller's player ID. Do not charge player
  query quota or modify subscriptions during a query.
- The overview and its selections require `team_resource_subscription`, including
  a fresh check on selection. This preserves subscription-query access independently
  of the arbitrary-ID `seer_team` feature. Actor/conversation scope remains typed.
- Both adapters receive the same operation and sessions. Delete the native
  query handler and unused `query_target_messages` method; AI's existing
  explicit `query_messages` consumer remains unchanged.
- No TOML changes, new file, dependency, database, image asset or runtime
  compatibility path. A live QQ message matrix is still a separate release gate.

Focused verification: 73 passed using an isolated temporary directory. An earlier
invocation failed while cleaning the host's old pytest temporary directory and
is not accepted evidence. The first full-suite collection exposed the test
registry's outdated composition arguments; update that composition rather than
adding optional production dependencies to accommodate it.

Final full-suite verification: 3544 passed / 7 skipped in 280.76 seconds;
Ruff, BasedPyright, compileall and diff checks passed. Existing dependency
warnings remain visible (2889 with the updated installed-rule tests). Production
code grows by 98 net lines, with no new file or packaged asset. This closes the
17-item main-follow-up source checklist, not the overall 7/8 phase ledger or
the exact-candidate real QQ connection/message matrix.
