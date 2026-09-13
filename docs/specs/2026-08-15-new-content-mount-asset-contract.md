# 新增内容座驾素材发布契约

Status: `implemented; production smoke pending`

Contract: `target`

Owner: `seerapi` 素材发布管线、IronsBot `SeerImageSource` 适配器与新增内容素材准备器

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#rendering-and-published-seer-data)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

旧实现让座驾图片先按 `equip` 查询，再从发布 SQLite 的 Blob 表读取构建期 PNG。
当前实现已删除该运行时分叉：SeerAPI 将 Flash PNG 增量发布到自身的
`generated-render-assets` 分支，manifest v3 按素材类型声明仓库和不可变提交；机器人只
通过统一图片源读取 `mount`。每个 `mount` 请求拥有有序不可变候选：先使用 Unity
`equip` PNG，缺失时才使用 SeerAPI 生成的 Flash PNG。

这不是运行时 SWF 转换，但它仍让一个已生成的 PNG 绕开了统一 `AssetStore`、素材
manifest 和明确的 release 兼容检查。`NewContentAssetRequest.fallback_data` 也使素材
来源无法只由 `kind/key` 和已发布 revision 表达。当前行为会保留菜单行并显示“官方图片
暂未上线”，这是正确的可见失败语义；本 Spec 不改变该产品行为。

## Goal

座驾 PNG 与其他 Seer 渲染素材使用同一发布契约：SeerAPI 在构建期声明稳定的
`mount` 素材种类、键、可用性、内容校验和 immutable revision；IronsBot 只通过
`SeerImageSource.fetch("mount", key, fallback=False)` 获取它。新增内容 renderer 不再
执行原始 SQL，不再携带嵌入式 `fallback_data`，也不通过缺表判断旧 release。

素材未发布、缺失或不可用时，菜单仍保留条目、明确显示没有官方图片，并禁止该次最终
图片进入缓存。数据 schema 不满足该契约时，由数据加载边界按既有不兼容 release 语义
禁用相应新增内容图片能力，而不是静默走旧路径。

## Non-Goals

- 不重新引入运行时 SWF 下载、FFDec 或 Java。
- 不改变座驾条目、菜单选择、文字详情或普通装备图片的用户语义。
- 不把群星牌任意 URL 图片纳入此 manifest；它仍不允许最终图缓存。
- 不在 IronsBot 中保留 `flash_mount_image` 的双读或缺表兼容。

## Ownership And Reuse

- Semantic owner: SeerAPI 负责从 Flash 资源生成 PNG 并作为 release 素材事实发布；
  IronsBot 的 `HttpSeerImageSource` / `AssetStore` 是唯一运行时字节读取路径。
- Reused contracts: `render_asset_manifest` v3、immutable asset repository revision、
  `ImageKind`、`SeerImageSource`、`NewContentAssetRequest` 与 `RenderCache`。
- Adapter boundary: SQL、SWF、PNG 生成和素材发布止于 SeerAPI；OneBot 与 HTML renderer
  只消费准备完成的 data URI / `RenderDocument`。
- New interface: 增加受 manifest 覆盖的 `mount` asset kind；不得新增座驾专用 HTTP、
  SQLite 或缓存接口。

## User And Data Contract

- Inputs: SeerAPI 构建期识别的座驾 ID 与生成的 PNG；已发布 asset repository revision。
- Outputs: `mount` manifest 条目和按 revision 固定的素材 URL；缺图时的现有可见提示。
- Permissions and scope: `new_content_standard` 座驾缩略图和普通座驾详情查询；不影响
  非座驾查询。
- Persistence: SeerAPI 的 manifest 以 `(asset_kind="mount", asset_key)` 唯一；PNG 的
  位置和 SHA-256 必须可由该 release 复现。IronsBot 只保留通用 asset/render cache。
- Compatibility: 新 release 是唯一正常路径。IronsBot 删除 `flash_mount_repository`、
  `fallback_data` 和 `flash_mount_image` runtime 查询；旧 release 不得被静默读取。
- Selection: manifest 和消费者使用相同的候选顺序。仓库和路径均固定到发布 revision；
  不允许把所有座驾强制路由到生成仓库，也不允许回退到可变分支。

## Design

1. SeerAPI 构建管线将成功生成的座驾 PNG 放入已声明的 immutable asset revision，并为
   每个座驾写入 `mount` manifest 条目；未成功生成的条目必须明确为 unavailable 或不在
   完整 scope 中，不能伪造可用素材。
2. manifest scope 计算将座驾素材纳入 `new_content_standard` 的完整性判断。scope 只有
   在新增内容 renderer 需要的所有标准素材均存在、可校验且来自清单声明的不可变
   revision 时才完整。
3. IronsBot 在 `ImageKind` 与 `HttpSeerImageSource` 中注册 `mount` 的标准路径映射。
   新增内容快照对座驾只产生 `NewContentAssetRequest(kind="mount", key=...)`。
4. renderer 图片请求失败时沿用现有“条目仍显示、图片为空、禁用最终缓存”的语义；不再
   回读 release SQLite blob。
5. 删除 `flash_mount_repository.py`、其测试、`fallback_data` 字段和
   `_with_mount_fallback()`。任何残留 `flash_mount_image` runtime import 都由架构测试拒绝。

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| SeerAPI 素材发布 | `mount` PNG、SHA-256、availability 和 revision 进入 manifest | 设计并验证 asset repository 写入/发布机制 | implemented |
| 完整 scope | `new_content_standard` 对座驾素材做范围验证 | 发布 manifest slice | implemented |
| IronsBot 通用读取 | `ImageKind` / HTTP source 能按 release revision 获取 `mount` | 新 SeerAPI fixture | implemented |
| 删除专用 fallback | 无原始 SQL、blob fallback 或缺表兼容；缺图仍有可见语义 | 通用读取 slice | implemented |
| 真实 consumer smoke | 新 release 下 mount 菜单渲染、缓存准入与缺图场景均验证 | 已发布测试 release | planned |

## Migration And Rollback

- Migration: 不迁移用户状态。先发布带 `mount` manifest 的 SeerAPI schema/fixture，再在
  IronsBot 删除专用读取路径；不得在生产运行时双读。
- Rollback: 在新 release smoke 通过前，不替换生产 data release；代码回滚到独立提交，
  不恢复旧 release 的运行时兼容。
- Removal condition: 已满足。旧 Blob 只允许在构建时作为上一版 release 的一次性种子，
  随后从新数据库删除；IronsBot 不含旧读取路径。

## Acceptance Tests

- [x] SeerAPI 为已生成座驾 PNG 发布稳定 `mount` manifest 条目、SHA-256 和 revision。
- [x] 一个缺失座驾 PNG 使 `new_content_standard` scope 不完整，不能被误报为完整。
- [x] IronsBot 只用 `SeerImageSource` 读取座驾素材，URL 固定到发布 revision。
- [x] 缺图时菜单条目仍显示“官方图片暂未上线”，且最终图不写缓存。
- [x] 不存在 `flash_mount_repository`、`fallback_data` 或 `flash_mount_image` 的 IronsBot
  运行时 import / SQL 查询。
- [x] SeerAPI 与 IronsBot 各自通过针对性 pytest、Ruff、compileall、静态架构检查和
  `git diff --check`。
- [ ] 使用真实生成 release 做 consumer smoke。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | 当前路径审计 | `new_content_renderer`、`flash_mount_repository`、SeerAPI Flash render script 与 focused tests | 已确认 PNG 在构建期生成，但 IronsBot 仍从 SQLite blob 作隐式 fallback；尚未实施。 |
| 2026-08-15 | 上游发布能力审计 | SeerAPI `render_flash_mount_images.py`、`render_asset_repository.py`、build workflow 与 asset manifest builder | Flash 脚本只写 release SQLite；现有 asset repository 仅提供 immutable snapshot 读取，尚无 PNG 写入/发布路径，因此不得开始消费者切换。 |
| 2026-09-05 | 重新核对真实消费者和流水线 | `services/seer/equipment.py`、新增内容 renderer、SeerAPI build workflow | 普通座驾查询也调用 `load_flash_mount_image`，删除 repository 时必须一同迁入统一素材源；上游仍只向 SQLite 写 PNG，尚无 immutable asset repository 发布步骤。本次未删除消费者或改动生产发布。 |
| 2026-09-13 | manifest v3 与座驾素材外置 | SeerAPI 全量 327 passed；IronsBot 全量 3239 passed、7 skipped，当前 focused tests 67 passed；两仓 Ruff、compileall 与改动范围 BasedPyright | 构建端增量发布 `generated-render-assets`，消费者专用 Blob 路径已删除；尚需真实 Actions release 和机器人 consumer smoke。 |
| 2026-09-13 | 真实座驾来源复核 | 本地真实发布库 36 个座驾 manifest 条目；候选路由专项测试；生产 HTTP 图片源读取 `1300067` | 25 个已有 Unity `equip` PNG，11 个缺失；候选链固定为 Unity 优先、生成 PNG 兜底。真实固定 commit 返回 26,603 字节、193×184 的有效 PNG；生成分支仍待线上发布 smoke。 |
| 2026-09-13 | 本地跨仓库 release smoke | 62 MB 真实发布库经生产 finalizer 重封装为 manifest v3；IronsBot `DatabaseManager`、`SeerDatabase` 与生产 HTTP 图片源消费 | 机器人识别 `default`、`mount` 两个不可变仓库，36 条座驾中 25 条 Unity 事实可用，`1300067` 成功解码为 193×184 PNG。未发布的生成分支和 11 个 Flash 缺口仍待 Actions smoke。 |
| 2026-09-13 | 本地生成分支生命周期 smoke | 使用临时 bare remote 原样执行工作流的 orphan branch 创建、worktree 更新、提交和 push 命令 | 首次发布和增量发布生成两个不同提交，远端分支最终包含 `README.md`、`mount/1.png`、`mount/2.png`。这只验证 Git 编排，不替代真实 Actions、资源生成或消费者 smoke。 |
| 2026-09-13 | 生成范围收口 | SeerAPI 全量 `331 passed`；真实发布库经当前 finalizer 重建 manifest 后执行候选筛选 | 生成器按 manifest v3 的 `default` 仓库事实跳过 Unity 已覆盖座驾，并清理生成分支中的重复 PNG；36 个座驾只留下 11 个 Flash 缺口，首次 FFDec 候选减少约 69%。生成仓库自身的 manifest 事实不会被误判为 Unity；缺少当前 manifest 或仓库元数据会立即失败，不再静默全量渲染。 |
| 2026-09-13 | 热构建 FFDec 门 | 完整/缺失生成 PNG 计划测试、工作流条件结构与 YAML 解析；SeerAPI 全量 `335 passed`；Ruff、CLI、compileall、diff check | 座驾生成器先复用旧 PNG、裁剪 Unity 已覆盖和退役项，再输出精确候选数；候选为空时不安装 FFDec，候选存在时继续执行原下载、渲染、pending 与增量发布路径。真实 Actions 耗时仍待量化。 |
| 2026-09-13 | SWF 可用性预检 | 当前 v3 数据库的 11 个 Flash 候选真实预检；SeerAPI `09d66dc` 全量 `338 passed`、Ruff、compileall、diff check | 11 个官方 URL 均明确返回 404，计划输出 `renderer_required=False`，不再仅因 PNG 缺失就安装 FFDec；可下载源或瞬时网络/服务错误仍保守启用 renderer。缺图继续记 pending，不生成占位图，也不宣称 scope 完整。 |

## Progress

```text
Program  [█████████░] verified phases: 7/8
Phase    [████████░░] 80%  verified slices: 4/5   estimated remaining: one production release smoke
Current  [██████████] 100% local real-release smoke complete; next: publish and verify generated assets
```
