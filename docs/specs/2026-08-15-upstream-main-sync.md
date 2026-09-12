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
| Bilibili 正文补全 | 缺正文与截断 Opus 使用详情补全，不改变 V5 任务所有权 | 无 | completed |
| 开服别名与竞技池变动入口 | 命令由 V5 service contract 提供，数据由 repository 提供 | 无 | completed |
| 活动周快照 | 只通过活动 service 与 runtime-state 事实存储实现 | 无 | verified |
| 竞技池变动渲染 | presenter 先产出不可变 document，再接 HTML renderer | 需要 render document Spec | planned |
| 幸运橱窗卡片与价格菜单 | 使用 skin repositories、关注偏好和 V5 prompt 边界 | 需要幸运橱窗 Spec | planned |
| Docker 维护/更新确认 | 使用 operations service、明确管理员权限与确认会话 | 需要 operations Spec | planned |
| 绑定限制 | 审计后不迁入：V5 已确认所有米米号入口支持一个直接 @ 用户解析，不能额外要求请求者先绑定 | 无 | superseded |
| Bilibili 抽奖/中奖拆分 | 复用配置驱动分类，不增加硬编码枚举或旧配置迁移器 | 无 | completed |
| 新增技能根菜单预览 | 根预览只含新增项；技能排除本周新精灵自带技能，详情保留完整数据 | 无 | completed |
| 队列推送加固 | 先审计 V5 `ProactiveMessageDelivery`，仅在 OneBot 最后一跳补真实缺口 | 最终 OneBot smoke | planned |
| 群星牌觉醒卡合并 | 在 Autocard repository/view model 合并普通/觉醒事实，适配器只发送结果 | 发布数据契约审计 | completed |
| 玩家战队菜单与私聊概览 | 复用玩家详情 action 与 team service；QQ 交互部分最后验收 | 目标平台能力 | planned |
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
| 2026-09-13 | Bilibili 抽奖/中奖拆分 | 配置加载、通用分类与订阅回归 | V5 已支持任意配置分类；示例声明独立 `lottery` / `winning`，无生产枚举或兼容迁移。 |
| 2026-09-13 | 新增技能根菜单预览 | service、文本菜单、原生菜单准备与配置链路回归 | 统一 preview selector；修改项折叠，详情菜单不裁剪。 |
| 2026-09-13 | Docker 交接失败恢复 | preflight 状态机、入口脚本、Docker gateway 与配置回归 | 默认等待 90 秒后清理失败更新器并启动当前镜像；可配置为严格等待。真实 Docker 交接仍留待 Linux 镜像验收。 |
| 2026-09-13 | 群星牌觉醒卡合并 | Autocard repository、service、菜单与图片回复回归 | `compose/composeTo` 形成只读变体索引；任一名称或 ID 返回同一组事实，异常关系不合并。 |
| 2026-09-13 | 战队详情增强（非 QQ 部分） | team service、配置与订阅简版回归 | 直接战队号查询补标语、公告与 Boss 剩余能量；订阅提醒保持简版。按 QQ 玩家目标查询延期。 |

## Progress

```text
Program  [███████□] 7/8 verified phases; Phase 7 remains open
Slice    [██████████□□□□□□] 10/16 tracked outcomes resolved; 6 remain
Current  [██████████] direct team detail enhancement verified
```

The activity snapshot slice is committed as V5 `80ce3c3e`. QQ-specific product
work remains subject to the platform capability deferral rule; the remaining
planned entries are not implicitly merged.
