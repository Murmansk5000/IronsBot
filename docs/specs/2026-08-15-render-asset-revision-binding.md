# 发布素材 Revision 绑定

Status: `implementing`

Contract: `transition`

Owner: `seerapi 发布数据契约、IronsBot Seer 素材 adapter`

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#rendering-pipeline-and-cache-contract)

Related workflow: [engineering-workflow.md](../engineering-workflow.md#spec-驱动开发)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

SeerAPI 构建期已从 `Murmansk-Seer/seer-unity-assets` 的不可变 Git tree 生成
`render_asset_manifest`，并发布 asset-tree revision、完整 scope 和每项素材的
blob ID。IronsBot 运行时的 `HttpSeerImageSource` 却仍把可验证素材请求指向该
仓库的可变 `main` 分支。

因此同一个 final-image cache key 可以声明某个 release 的 manifest revision，
实际却下载之后更新的素材。当前 `render_category_available()` 只能证明清单存在，
不能证明请求到的字节属于该清单。这个缺口影响 pet 信息、属性、巅峰和新内容等已
启用请求级最终图缓存的渲染类别。

## Goal

发布物中的 manifest revision 成为运行时远程素材 URL 的唯一 revision 来源。对受
manifest 保护的渲染类别，IronsBot 只能下载该 release 发布的资产树 revision；无法
读取、验证或解析 revision 时，禁用该类别的 L3 final-image cache，并返回现有正常的
非缓存渲染/素材错误语义，不回退到可变 `main`。

## Non-Goals

- 不把整套 PNG 素材嵌入 SeerAPI SQLite。
- 不改动不属于 `seer-unity-assets` 的 preview、任意上游 URL 卡牌图或用户上传图片。
- 不以运行时 HTTP 探测重新生成 manifest 或猜测素材版本。
- 不把此项与新增渲染类别、皮肤数据解析或资源仓库重组织捆绑。

## Ownership And Reuse

- Semantic owner: SeerAPI 负责发布 asset repository revision 与 manifest；
  IronsBot 的 Seer-data database adapter 负责读取并验证发布元数据；
  `HttpSeerImageSource` 只按已验证 revision 构造 URL。
- Reused contracts: `render_asset_manifest`、`ironsbot_metadata`、
  `SeerDatabase` 的发布版本/可用范围、`SeerImageSource`、`SeerAssetStore` 和
  `FileRenderCache`。
- Adapter boundary: 服务与 presenter 继续只接收 `SeerImageSource`；HTTP URL
  模板和 Git revision 到 raw URL 的转换停留在 HTTP integration。
- Why a new interface is or is not needed: 需要一个窄的已发布素材快照值对象，
  表达 asset repository、immutable revision 和可用 scopes；不需要新 registry 或
  让 renderer 读取 metadata。

## User And Data Contract

- Inputs: SeerAPI release 的 `render_asset_manifest` 与 metadata。
- Outputs: 已保护类别的素材请求始终引用发布 revision；不兼容 release 不生成 L3
  缓存命中。
- Permissions and scope: 无新的用户命令、feature 或 TOML。
- Persistence: 无新增运行状态；SeerAPI release metadata/schema 按版本发布。
- Compatibility: 没有运行时 `main` 回退。旧 release 缺少完整 revision 契约时保持
  L3 不可用，需通过 `/更新数据` 获取新 release。

## Design

1. SeerAPI 将资产仓库标识和不可变 revision 作为 manifest contract 的显式字段或
   明确定义的 metadata，而不是只留在 `source` 字符串中。
2. IronsBot 在原子加载数据库时一次性读取该快照；只接受已支持的 contract version、
   合法 Git revision 与已声明的 scope。
3. rendering composition 将不可变快照传入 HTTP 素材 adapter。每个 manifest 支持的
   `ImageKind` 使用 `raw.githubusercontent.com/<repository>/<revision>/...`；
   不在 manifest 范围内的素材保持自己的明确来源，不伪装成受保护素材。
4. 素材缓存 key 必须包含 source revision 或由已包含该 revision 的发布版本稳定派生，
   防止 mounted cache 复用可变分支时期的旧字节。
5. scope 完整性要按 renderer 的真实素材家族计算；新增一个 renderer 或 `ImageKind`
   时，先补清单 inventory 与验证，再允许 L3。

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| 1 | SeerAPI 发布显式、可解析的 asset repository snapshot contract 与 fixture | SeerAPI build schema | verified |
| 2 | IronsBot 原子读取并拒绝缺失/无效 snapshot 的 release | Slice 1 | verified |
| 3 | HTTP 素材 adapter 对受保护类别只构造 revision-pinned URL，缓存不复用 mutable source | Slice 2 | verified |
| 4 | 逐个核对 pet/type/peak/new-content inventory 与真实 `ImageKind`；端到端 fixture 验证 | Slice 3 | in_progress |

## Migration And Rollback

- Migration: 先发布 SeerAPI schema 与 fixture，再发布 IronsBot consumer；不改用户
  状态或 SQLite 挂载数据。
- Rollback: 回退 IronsBot commit 或继续使用已验证的旧 release；不能以重新启用
  `main` URL 作为回滚手段。
- Removal condition: 当所有受保护 renderer 均由 immutable snapshot 构造 URL，删除
  这些类别的 mutable asset template 与相关测试。

## Acceptance Tests

- [x] SeerAPI fixture 发布 repository、合法 revision、manifest revision 和 scope。
- [x] 缺少 snapshot metadata 的 release 被 IronsBot 标记为不支持，L3 不可用。
- [x] manifest 支持的 `ImageKind` 通过发布 revision 构造 URL，且缺少 snapshot 时
  不回退到 mutable `main`。
- [x] preview、任意 URL 卡牌图等非 manifest 资源不被错误改写；含任意 URL 的
  新内容最终图不进入 L3 缓存。
- [x] 同一请求在不同 asset revision 下不会复用素材或最终图缓存。
- [ ] SeerAPI 与 IronsBot 分别通过 focused tests、Ruff、类型/编译检查；最后以新
  release 做 consumer smoke test。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | 跨仓库只读审计 | SeerAPI manifest builder/model/tests；IronsBot image source/database/cache | 已确认 manifest 记录 immutable tree revision，但 `HttpSeerImageSource` 仍请求 mutable `main`；尚未实施。 |
| 2026-08-15 | SeerAPI `39c3339` | `uv run pytest -q` (260 passed); Ruff; compileall; diff check | Manifest contract v2 显式发布 repository 与 immutable revision；尚未做真实 release smoke。 |
| 2026-08-15 | IronsBot `a7dd38f4` | `uv run pytest -q` (1521 passed); Ruff; static check; BasedPyright 0 errors; compileall; diff check | 受保护素材改用 revision-pinned URL，素材缓存按 source identity 隔离；尚待逐 renderer inventory 对照与新 release consumer smoke。 |
| 2026-08-15 | SeerAPI / IronsBot scope audit | SeerAPI manifest focused tests (7 passed); IronsBot renderer/cache focused tests (37 passed); Ruff | `new_content_standard` 额外证明皮肤专属头像；外部卡牌 URL 不写最终图缓存；所有公共 Seer renderer adapter 进入缓存版本指纹。幸运橱窗的皮肤 body 尚未有完整 inventory，故 L3 仍刻意不可用。 |

## Progress

```text
Program  [████████░░] 79%  verified phases: 3/8  estimated remaining: cross-repository slices
Phase    [████████░░] 80%  verified scope inventory: pet/type/peak/new-content; remaining: release consumer smoke
Current  [████████░░] 85%  next: full validation and a generated-release consumer smoke
```
