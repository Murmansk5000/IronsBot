# 新增内容座驾素材发布契约

Status: `draft`

Contract: `target`

Owner: `seerapi` 素材发布管线、IronsBot `SeerImageSource` 适配器与新增内容素材准备器

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#rendering-and-published-seer-data)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

当前新增内容的座驾图片先按 `equip` 走统一 `SeerImageSource`。当该素材不存在时，
`new_content_renderer` 会直接调用 `flash_mount_repository`，从发布 SQLite 的
`flash_mount_image.png_data` 读取构建期渲染出的字节。旧 release 缺表和查询异常均被
视为无图片。

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
- Reused contracts: `render_asset_manifest` v2、immutable asset repository revision、
  `ImageKind`、`SeerImageSource`、`NewContentAssetRequest` 与 `RenderCache`。
- Adapter boundary: SQL、SWF、PNG 生成和素材发布止于 SeerAPI；OneBot 与 HTML renderer
  只消费准备完成的 data URI / `RenderDocument`。
- New interface: 增加受 manifest 覆盖的 `mount` asset kind；不得新增座驾专用 HTTP、
  SQLite 或缓存接口。

## User And Data Contract

- Inputs: SeerAPI 构建期识别的座驾 ID 与生成的 PNG；已发布 asset repository revision。
- Outputs: `mount` manifest 条目和按 revision 固定的素材 URL；缺图时的现有可见提示。
- Permissions and scope: 仅 `new_content_standard` 中座驾缩略图；不影响其他 Seer 查询。
- Persistence: SeerAPI 的 manifest 以 `(asset_kind="mount", asset_key)` 唯一；PNG 的
  位置和 SHA-256 必须可由该 release 复现。IronsBot 只保留通用 asset/render cache。
- Compatibility: 新 release 是唯一正常路径。IronsBot 删除 `flash_mount_repository`、
  `fallback_data` 和 `flash_mount_image` runtime 查询；旧 release 不得被静默读取。

## Design

1. SeerAPI 构建管线将成功生成的座驾 PNG 放入已声明的 immutable asset revision，并为
   每个座驾写入 `mount` manifest 条目；未成功生成的条目必须明确为 unavailable 或不在
   完整 scope 中，不能伪造可用素材。
2. manifest scope 计算将座驾素材纳入 `new_content_standard` 的完整性判断。scope 只有
   在新增内容 renderer 需要的所有标准素材均存在、可校验且来自同一 revision 时才完整。
3. IronsBot 在 `ImageKind` 与 `HttpSeerImageSource` 中注册 `mount` 的标准路径映射。
   新增内容快照对座驾只产生 `NewContentAssetRequest(kind="mount", key=...)`。
4. renderer 图片请求失败时沿用现有“条目仍显示、图片为空、禁用最终缓存”的语义；不再
   回读 release SQLite blob。
5. 删除 `flash_mount_repository.py`、其测试、`fallback_data` 字段和
   `_with_mount_fallback()`。任何残留 `flash_mount_image` runtime import 都由架构测试拒绝。

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| SeerAPI 素材发布 | `mount` PNG、SHA-256、availability 和 revision 进入 manifest | 明确 asset repository 路径 | planned |
| 完整 scope | `new_content_standard` 对座驾素材做范围验证 | 发布 manifest slice | planned |
| IronsBot 通用读取 | `ImageKind` / HTTP source 能按 release revision 获取 `mount` | 新 SeerAPI fixture | planned |
| 删除专用 fallback | 无原始 SQL、blob fallback 或缺表兼容；缺图仍有可见语义 | 通用读取 slice | planned |
| 真实 consumer smoke | 新 release 下 mount 菜单渲染、缓存准入与缺图场景均验证 | 已发布测试 release | planned |

## Migration And Rollback

- Migration: 不迁移用户状态。先发布带 `mount` manifest 的 SeerAPI schema/fixture，再在
  IronsBot 删除专用读取路径；不得在生产运行时双读。
- Rollback: 在新 release smoke 通过前，不替换生产 data release；代码回滚到独立提交，
  不恢复旧 release 的运行时兼容。
- Removal condition: `flash_mount_image` 可继续作为 SeerAPI 的构建中间事实，直到其
  发布职责被替换；IronsBot 侧的 repository、测试和 fallback 字段必须在本 Spec 完成时
  全部删除。

## Acceptance Tests

- [ ] SeerAPI 为已生成座驾 PNG 发布稳定 `mount` manifest 条目、SHA-256 和 revision。
- [ ] 一个缺失座驾 PNG 使 `new_content_standard` scope 不完整，不能被误报为完整。
- [ ] IronsBot 只用 `SeerImageSource` 读取座驾素材，URL 固定到发布 revision。
- [ ] 缺图时菜单条目仍显示“官方图片暂未上线”，且最终图不写缓存。
- [ ] 不存在 `flash_mount_repository`、`fallback_data` 或 `flash_mount_image` 的 IronsBot
  运行时 import / SQL 查询。
- [ ] SeerAPI 与 IronsBot 各自通过针对性 pytest、Ruff、compileall、静态架构检查和
  `git diff --check`；使用真实生成 release 做 consumer smoke。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | 当前路径审计 | `new_content_renderer`、`flash_mount_repository`、SeerAPI Flash render script 与 focused tests | 已确认 PNG 在构建期生成，但 IronsBot 仍从 SQLite blob 作隐式 fallback；尚未实施。 |

## Progress

```text
Program  [████████░░] 79%  global verified progress; this draft does not change it
Phase    [░░░░░░░░░░] 0%   verified slices: 0/5   estimated remaining: 2-4 h after asset-path evidence
Current  [██████████] 100% audit complete; next: accept asset publication path before code changes
```
