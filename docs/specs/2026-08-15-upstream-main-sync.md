# V5 上游 Main 功能同步

Status: `implementing`

Contract: `transition`

Owner: `各领域 service、repository、render presenter 与 OneBot adapter`

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#change-design-gate)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

`origin/main` 已推进至 `af2e8810`，新增活动周快照、竞技池变动、幸运橱窗展示、
Docker 维护菜单、更新确认和玩家绑定限制等行为。V5 已将插件、命令目录和运行时
装配迁至新的目标边界；直接合并会恢复已退役目录，或将新功能的一半代码留在旧路径。

## Goal

在不恢复已退役 `command_directory`、旧 `plugins/*`、旧 runtime registry 或 renderer
数据访问的前提下，逐项把仍有产品价值的主线行为迁入 V5。每一项在 V5 内拥有唯一
semantic owner、真实的用户契约和针对性验证。

## Non-Goals

- 不把一次 Git merge 成功视为功能完成。
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

- Inputs: 当前 `origin/main` 的已审计提交及其公开用户行为。
- Outputs: 与主线相同或明确改进的可观察行为；失败时保留 V5 的真实错误语义。
- Permissions and scope: 复用 V5 feature policy 与 command catalog，不复制旧 matcher
  的权限判断。
- Persistence: 仅在对应功能 Spec 明确 schema、迁移与备份后变更。
- Compatibility: V5 是唯一运行路径；旧主线路径不进入正常读取或启动路径。

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| Bilibili 正文补全 | 缺正文与截断 Opus 使用详情补全，不改变 V5 任务所有权 | 无 | completed |
| 开服别名与竞技池变动入口 | 命令由 V5 service contract 提供，数据由 repository 提供 | 无 | completed |
| 活动周快照 | 只通过活动 service 与 runtime-state 事实存储实现 | 无 | verified |
| 竞技池变动渲染 | presenter 先产出不可变 document，再接 HTML renderer | 需要 render document Spec | planned |
| 幸运橱窗卡片与价格菜单 | 使用 skin repositories、关注偏好和 V5 prompt 边界 | 需要幸运橱窗 Spec | planned |
| Docker 维护/更新确认 | 使用 operations service、明确管理员权限与确认会话 | 需要 operations Spec | planned |
| 绑定限制 | 审计后不迁入：V5 已确认所有米米号入口支持一个直接 @ 用户解析，不能额外要求请求者先绑定 | 无 | superseded |

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
| 2026-08-15 | 抓取 `origin/main` `af2e8810` 并尝试语义合并 | compile/Ruff preflight | 自动 merge 证明旧/新目录边界不兼容，未将半合并状态保留。 |
| 2026-08-15 | 活动周快照 | activity storage/service/command tests, Ruff, compileall | 18 项通过；首次观察明确提示缺少上周快照。 |
| 2026-08-15 | 请求者绑定限制 | `PlayerIdResolver` 与既有用户契约审计 | 不迁入；会缩窄已确认的直接 @ 用户解析能力。 |

## Progress

```text
Program  [████░░░░░░] 45%  verified slices: 3/7  estimated remaining: 1-3 focused specs
Phase    [█████░░░░░] 45%  current: upstream behaviour migration
Current  [██████████] 100% complete: activity snapshot committed as V5 `80ce3c3e`
```

The activity snapshot slice is committed as V5 `80ce3c3e`. The remaining
entries are planned rather than implicitly merged.
