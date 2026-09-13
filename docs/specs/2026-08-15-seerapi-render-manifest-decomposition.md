# SeerAPI 渲染素材 Manifest 职责拆分

Status: `in_progress`

Contract: `transition`

Owner: `seerapi` 发布构建管线的渲染素材 manifest 领域

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#rendering-and-published-seer-data)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

`seerapi/scripts/build_seerapi_data_db.py` 当前为 4,553 行。它同时承担下载协议、
ConfigPackage 解码、图片探测、SWF/Unity 图标转换、SQLite 表替换、素材 manifest 枚举、
release metadata 和 CLI 编排。此前已经拆出群星牌、效果元数据、兑换商店、伙伴契约、
ConfigPackage 解码与 asset-repository snapshot 读取，但 manifest 的领域逻辑仍嵌在总构建器
的 `_pet_info_remote_asset_requests()` 至 `_render_asset_manifest_metadata()` 区段。

这段代码有明确的输入输出：它从发布 SQLite 的 ID 域和 immutable asset snapshot 枚举素材，
产生 manifest entries、complete scopes 和 metadata。它不应继续依赖总构建器的环境变量、
HTTP、FFDec、命令行或表替换顺序。继续往总脚本添加新的 renderer 素材种类会扩大已经登记的
transition 债务，也会让消费者难以证明每一种素材范围的语义。

## Goal

将渲染素材 manifest 的领域计算迁到 SeerAPI 的专用模块。`build_seerapi_data_db.py` 仅保留：

- 读取环境并构造 immutable repository snapshot；
- 在已完成的 SQLite 数据上调用 manifest builder；
- 原子替换 `render_asset_manifest` 表并写入 metadata；
- 保持现有 CLI、发布 schema、metadata key、manifest revision 和 complete-scope 语义不变。

新模块必须有显式配置和值对象，能在纯 SQLite fixture 与静态 snapshot 下直接测试。它不能访问
网络、环境变量、文件系统、FFDec 或 CLI 参数。

## Non-Goals

- 不在本 Slice 发布座驾 PNG 到 asset repository；该工作由
  [新增内容座驾素材发布契约](2026-08-15-new-content-mount-asset-contract.md) 单独推进。
- 不改变 `render_asset_manifest` 表、manifest v2 或 IronsBot 的严格消费契约。
- 不移动 SWF/Unity 效果图标 PNG 转换；它是下一独立 Slice，不能为了凑行数与 manifest 混拆。
- 不把所有构建辅助函数塞入 `utils`、`common` 或万能 `builder` 模块。

## Ownership And Reuse

- Semantic owner: `render_asset_manifest` 负责“发布 SQLite 的 renderer 素材需求，与某个
  immutable repository tree 的可用性证明”这一事实计算。
- Reused contracts: `AssetRepositorySnapshot`、`render_asset_manifest` 表、manifest v2
  metadata keys、现有 scope 常量和现有 SQLite schema。
- Adapter boundary: `render_asset_repository.py` 继续是 repository snapshot 的读取 adapter；
  新模块只接受它已读取出的 `AssetRepositorySnapshot`。总构建器继续拥有 HTTP、环境变量和
  SQLite 写入时机。
- New interface: 新建 `scripts/render_asset_manifest_build.py`。导出的公共输入为
  `RenderAssetManifestConfig`、`RenderAssetManifestBuild` 和 `build_render_asset_manifest()`；
  模块内部拥有素材请求、candidate path、scope 推导、revision 与 metadata 的纯逻辑。

## User And Data Contract

- Inputs: 已完成的发布 SQLite connection、可选 immutable asset snapshot、release revision、
  `RenderAssetManifestConfig`。
- Outputs: 有序 immutable manifest entries、`complete_scopes`、release metadata；缺表或
  snapshot 不可用时返回不完整结果，不伪造 complete scope。
- Permissions and scope: 仅 SeerAPI 构建期；IronsBot 不导入该模块。
- Persistence: builder 不写库。编排层继续以 `(asset_kind, asset_key)` 唯一替换
  `render_asset_manifest`，并保留现有 schema/version 检查。
- Compatibility: API 仅替换构建器内部调用。旧私有 helper 删除，不保留 wrapper；对外已发布
  SQLite 与 metadata 契约不变。

## Design

### Explicit configuration

`RenderAssetManifestConfig` 包含 asset repository name、scope 名称、各素材的 immutable path
规则和 metadata contract version。它由总构建器根据环境构造一次。模块不得直接读取
`os.environ` 或引用 `build_seerapi_data_db` 的 module globals。

### Pure build result

`collect_remote_asset_manifest()` 与 `build_render_asset_manifest()` 依次返回
`RenderAssetManifestBuild`：

- `entries`：按 `(asset_kind, asset_key)` 稳定排序；
- `pet_info_scope_complete` 与 `new_content_standard_scope_complete`：分别保留当前的完整性
  规则；
- `complete_scopes`：只有所依赖的素材范围都完整时才包含 scope；
- `metadata`：保持现有 key、值和 order-independent revision 算法。

效果图标 PNG 的 entries 由下一 Slice 作为显式输入并合入同一个 `entries` 序列。模块不负责
从 SWF 或 Unity 包计算这些 PNG。

### Module boundaries

| Responsibility | Target owner | Forbidden dependency |
| --- | --- | --- |
| Immutable tree snapshot HTTP/Git fallback | `render_asset_repository.py` | manifest builder 不读 HTTP/Git |
| Pet/new-content asset inventory and candidate paths | `render_asset_manifest_build.py` | 不读环境、不执行网络 |
| Scope proof, revision and metadata | `render_asset_manifest_build.py` | 不依赖 FFDec/Unity/CLI |
| Effect icon PNG bytes and checks | 后续 `effect_icon_png_build.py` Slice | 不并入 inventory module |
| SQLite table replacement and release orchestration | `build_seerapi_data_db.py` | 不重新承载领域枚举 |

### Invariants

1. 相同输入数据库、snapshot、release revision 与 config 必须产生相同 entries、revision 和
   metadata。
2. required candidate path 缺失必须使对应 scope 不完整；optional 素材缺失只记录
   `available=false`。
3. `new_content_standard` 只有在 pet-info 与它自己的素材范围都完整时才可声明 complete。
4. snapshot 缺失、所需表缺失或 ID 域不可读时，entries 可以为空，但不得声明 complete。
5. 新素材种类只能在该领域模块增加路径与范围规则，并附 fixture 和 scope 测试。

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| Manifest domain extraction | 新模块从 SQLite + snapshot 生成既有契约的 entries/scopes/metadata；总构建器删除旧 helper | 本 Spec 接受 | completed |
| Effect icon build extraction | SWF/Unity 图标转换使用独立配置/结果值对象，不影响 manifest domain | Manifest extraction | completed |
| Mount publication | mount PNG 进入 immutable asset revision 与 manifest，IronsBot 删除 blob fallback | asset repository 写入设计 | implemented；真实 release smoke 待执行 |
| New-content index extraction | 输入 repository、分类、release state 输出分开，脚本低于 800 行 | 独立 Spec | completed |
| Final size gate | 自有 SeerAPI 生产/构建模块均低于 800 行或有窄化记录的临时例外 | 前述 slices | completed：AST/源码门禁覆盖维护代码，生成文件显式豁免 |

## Migration And Rollback

- Migration: 无数据库或用户状态迁移。先以 fixture 验证新模块输出与当前构建输出字节等价，再
  替换构建器内部调用。
- Rollback: 在真实 release 生成和下游 consumer smoke 之前，不替换生产 release；实现可按
  独立提交回滚。不得通过保留新旧双计算路径回滚。
- Removal condition: 新模块的契约测试覆盖 manifest entries、scope、revision 与 metadata 后，
  总脚本中对应私有 helper 必须全部删除。

## Acceptance Tests

- [x] 静态 SQLite fixture 与 immutable snapshot 生成已锁定的 entries、scope、revision、metadata
  语义。
- [x] pet-info required 素材、new-content 独有素材、optional item/sign-buff 缺失分别验证。
- [x] 无 snapshot、缺失表、空 ID 域均不得声明任何错误 complete scope。
- [x] effect-icon entries 合入后依旧按稳定键排序，revision 对输入顺序不敏感。
- [x] `build_seerapi_data_db.py` 不再定义 inventory、candidate path、scope/revision/metadata
  的领域 helper，也不从领域模块反向导入。
- [x] SeerAPI 运行 focused pytest、Ruff、compileall、`git diff --check`；真实 release 保持
  SeerAPI schema 与 IronsBot consumer smoke 可用。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | 当前职责审计 | 函数声明、调用点、既有 SeerAPI build tests 与规范审计 | manifest inventory 至 metadata 仍位于 4,553 行总构建器；`render_asset_repository.py` 已独立承担 immutable snapshot 读取。 |
| 2026-08-15 | SeerAPI `86c2de5` | `uv run pytest -q`（260 passed）、Ruff、构建器 `--help`、compileall、`git diff --check` | `render_asset_manifest_build.py` 成为唯一 manifest 计算路径；总构建器从 4,553 行降至 4,122 行。真实 release consumer smoke 尚未重跑。 |
| 2026-09-13 | SeerAPI `69f2af4` | 全量 `318 passed`、Ruff、compileall、公开输出器导入和源码行数门禁 | 效果图标与新内容索引已分别拆入窄模块；Schema、JSON/数据库输出职责拆分后最大维护模块 753 行。仅自动生成的 `openapi_comments.py` 显式豁免。座驾远端发布仍未完成。 |
| 2026-09-13 | typed repositories 与 mount publication | SeerAPI 全量 `326 passed`，IronsBot 全量 `3238 passed, 7 skipped`，Ruff、compileall、改动范围 BasedPyright、workflow YAML | manifest v3 支持按素材类型声明仓库；坐骑 PNG 增量发布到生成分支，机器人 Blob 读取已删除。只剩真实 Actions release consumer smoke。 |

## Progress

```text
Program  [███████░] 7/8 verified phases; Phase 7 remains open
Phase    [█████████░] 90%  implementation verified; remaining: production release smoke
Current  [██████████] 100% mount publication implementation verified; next: publish and consume a real release
```

Only verified, committed, or explicitly waived work counts toward progress.
