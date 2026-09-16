# SeerAPI 发布构建编排职责拆分

Status: `implementing`

Contract: `transition`

Owner: `seerapi` 发布 SQLite 构建管线

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#engineering-principles)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

`seerapi/scripts/build_seerapi_data_db.py` 当前为 727 行（本 Spec 开始时为 3,098 行）。它曾同时拥有网络请求、官方
包读取、精灵/皮肤资源探测、效果图 PNG cache CLI、SQLite 表写入和最终发布编排。
此前已迁出 ConfigPackage、群星牌、效果元数据、伙伴契约、渲染 manifest、效果图来源与
PNG 渲染等职责，但总构建器仍违反 800 行上限，且继续在此新增表或资源逻辑会重新扩大
它。

## Goal

将发布构建器降为不超过 800 行的流程编排入口。每个迁出模块只拥有一个真实职责，并且
不改变发布 SQLite schema、环境变量名称、CLI 选项、网络端点或 IronsBot 消费语义。

## Non-Goals

- 不借此次拆分改变任何发布表、素材 URL 或终端用户查询结果。
- 不在 IronsBot 运行时增加旧 schema 双读或兼容层。
- 不把构建器中的所有函数机械移动到 `utils`、`common` 或一个新的万能模块。
- 不把真实 GitHub Actions 发布视为本地单元测试可以替代的验证。

## Ownership And Reuse

- Semantic owner: `build_seerapi_data_db.py` 只拥有 CLI 与发布顺序编排。
- Reused contracts: 现有 `config_package_sources`、`effect_icon_build`、
  `render_asset_manifest_build`、`autocard_sources`、`new_content_index_*` 值对象。
- Adapter boundary: 网络/文件/SQLite 适配器各自位于专属 source、resource 或 writer
  模块；纯解析模块不读取环境变量、网络或数据库。
- New interfaces: 只在迁出 SQLite 写入或资源探测时引入窄的参数值对象；不建立通用
  service locator 或跨领域数据库仓储。

## Design

| Slice | 唯一职责 | 入口保留的职责 | Acceptance criteria | Status |
| --- | --- | --- | --- | --- |
| ConfigPackage table writer | 写入刻印品质、皮肤商店、皮肤价格、道具说明与皮肤素材 resolution 表 | 创建连接、确定发布顺序 | 写入前后表内容不变；writer 不读取环境或网络 | completed (`seerapi` `39b7348`) |
| Reference table writer | 写入兑换商店、官方效果描述与状态表 | 创建连接、确定发布顺序 | 写入前后表内容不变；writer 不读取环境或网络 | completed (`seerapi` `3cc386a`) |
| Soulmark icon writer | 写入魂印图标 PNG 与失败诊断表 | 执行效果图解析并确定发布顺序 | PNG、URL 和确认缺失语义不变；writer 不读取环境或网络 | completed (`seerapi` `59b4857`) |
| Autocard table writer | 写入群星牌角色、sidecar、卡牌、自然、buff 与赛季效果表 | 读取官方 JSON 并确定发布顺序 | 官方 schema 拒绝规则和 sidecar 语义不变；writer 不读取环境或网络 | completed (`seerapi` `ee89f06`) |
| Partner table writer | 写入伙伴分组、成员与升级契约表 | 创建连接、确定发布顺序 | 伙伴 group/member/upgrade 与正规化来源语义不变；writer 不读取环境或网络 | completed (`seerapi` `6821c15`) |
| Render manifest table writer | 写入 render manifest 事实表 | 创建连接、确定发布顺序 | manifest 行、hash 与不可用素材语义不变；writer 不读取环境或网络 | completed (`seerapi` `9988e7f`) |
| Release metadata projection | 构造并写入 `seerapi_metadata` | 创建连接、确定发布顺序 | 写入前后 metadata 不变；writer 不读取环境或网络 | completed (`seerapi` `9d197bd`) |
| Skin image resolution rules | 经典皮肤的同名 fallback、内容哈希消歧和 resolution 事实 | 传入已验证资源与哈希 | 相同 fixture 产生相同 resolution 与缺失语义；规则不读网络或 SQLite | completed (`seerapi` `e268bbe`) |
| Pet/skin asset probe | 探测精灵头像、皮肤资源及经典皮肤输入 | 传入来源 URL、超时与 logger | 相同 fixture 产生相同资源验证、临时失败重试与缺失语义 | completed (`seerapi` `0dbf0d3`) |
| Build I/O | HTTP 重试、下载、包 manifest 和上游数据库复制 | 传入构建配置并处理 CLI 错误 | 重试、HTTP 错误和本地上游路径保持当前语义 | completed (`seerapi` `ce39c67`) |
| Effect-icon cache CLI | cache seed、分片导出/渲染的 CLI adapter | 正常发布与参数选择 | `--seed`、`--render-shard`、`--help` 保持兼容 | completed (`seerapi` `a92c3d0`) |
| Final orchestration | 只协调输入、纯/适配器调用、SQLite writer、quick check 和日志 | 无 | 主脚本不超过 800 行；每个新生产模块不超过 800 行 | completed (`seerapi` `13730e4`) |

## Migration And Rollback

- Migration: 无发布 schema 或生产数据迁移；每个切片先用临时 SQLite 和 cache 目录验证。
- Rollback: 每一切片独立提交，可直接回退，不替换 release 资产。
- Removal condition: `build_seerapi_data_db.py` 不再定义已迁出职责的实现，不能保留
  forwarding wrapper 或第二条写入路径。

## Acceptance Tests

- [ ] 现有 `tests/test_build_seerapi_data_db.py` 保持通过，并为每个迁出的边界补充直接测试。
- [ ] 对固定 fixture 比较关键表行、metadata、资源 resolution 和效果图统计。
- [ ] `python scripts/build_seerapi_data_db.py --help`、Ruff、compileall 与 `git diff --check` 通过。
- [ ] SeerAPI 全量 pytest 通过；真实 release 再由 IronsBot 下载并 smoke test。
- [ ] `build_seerapi_data_db.py` 与所有新增生产模块均不超过 800 行。

## Progress

```text
Program  [███░░░░░░░]  verified phases: 3/8; global percentage awaits weighted baseline
Phase 4 [██████████]  verified work: manifest/effect/new-content boundaries, writers, I/O, source loaders, skin assets and final publication
Current  [██████████]  completed: entry script only owns CLI, construction order and health checks
```

Only verified, committed, or explicitly waived work counts toward progress.

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | `seerapi` `39b7348` | focused `tests/test_build_seerapi_data_db.py` (54 passed); full SeerAPI pytest (264 passed); Ruff; compileall; `git diff --check` | ConfigPackage-derived table replacement is a single no-network writer. The entry script fell from 3,098 to 2,903 lines. Remaining table writers, resource probes and CLI adapters are not yet migrated. |
| 2026-08-15 | `seerapi` `3cc386a` | focused `tests/test_build_seerapi_data_db.py` (55 passed); full SeerAPI pytest (265 passed); Ruff; compileall; `git diff --check` | Official shop/effect/status release tables are a second no-network writer. The entry script fell to 2,780 lines. Soulmark, metadata, asset and CLI ownership remain in the builder. |
| 2026-08-15 | `seerapi` `59b4857` | focused `tests/test_build_seerapi_data_db.py` (56 passed); full SeerAPI pytest (266 passed); Ruff; compileall; `git diff --check` | Soulmark PNG publication and failed-render diagnostics are a dedicated SQLite writer. The entry script fell to 2,650 lines. The effect-icon source/renderer remains in its existing modules; remaining release tables, asset probes and CLI adapters are not yet migrated. |
| 2026-08-15 | `seerapi` `ee89f06` | focused `tests/test_build_seerapi_data_db.py` (56 passed); full SeerAPI pytest (266 passed); Ruff; compileall; `git diff --check` | Autocard role/card/nature/buff/season SQLite writing is isolated, including its strict official-schema rejection and raw sidecar. Shared JSON field parsing moved to a pure helper also reused by the Unity item catalog. The entry script fell to 2,167 lines. Partner, manifest, metadata, asset probes and CLI adapters remain. |
| 2026-08-15 | `seerapi` `6821c15` | focused `tests/test_build_seerapi_data_db.py` (56 passed); full SeerAPI pytest (266 passed); Ruff; compileall; `git diff --check` | Partner group/member/upgrade publication is now a dedicated no-network writer. The entry script fell to 2,030 lines. Render manifest/metadata, asset probes, build I/O and cache CLI adapters remain. |
| 2026-08-15 | `seerapi` `9988e7f` | focused `tests/test_build_seerapi_data_db.py` (56 passed); full SeerAPI pytest (266 passed); Ruff; `scripts` compileall; `git diff --check` | Render-manifest table publication is now a dedicated no-network writer. The entry script fell to 1,981 lines. Metadata, asset probes, build I/O and cache CLI adapters remain. |
| 2026-08-15 | `seerapi` `ce39c67` | focused `tests/test_build_http.py` + `tests/test_build_seerapi_data_db.py` (58 passed); full SeerAPI pytest (268 passed); Ruff; `scripts` compileall; `git diff --check` | `BuildHttpClient` now owns retrying HTTP, atomic downloads, verified local upstream input, image probe and ConfigPackage manifest I/O. The entry script fell to 1,861 lines. Pet/skin resource probes and cache CLI adapters remain. |
| 2026-08-15 | `seerapi` `e268bbe` | focused `tests/test_build_seerapi_data_db.py` (56 passed); full SeerAPI pytest (268 passed); Ruff; `scripts` compileall; `git diff --check` | Classic-skin fallback selection, content-hash disambiguation and resolution facts are now pure rules in `skin_image_resolution.py`. The entry script fell to 1,672 lines. Resource probes and cache CLI adapters remain. |
| 2026-08-15 | `seerapi` `0dbf0d3` | focused `tests/test_build_seerapi_data_db.py` (56 passed); full SeerAPI pytest (268 passed); Ruff; `scripts` compileall; `git diff --check` | `SkinImageAssetProbe` now owns ranged PNG checks, transient retry, concurrent validation and content hashes. The entry script fell to 1,503 lines. Effect-icon cache CLI adapters remain. |
| 2026-08-15 | `seerapi` `a92c3d0` | focused `tests/test_build_seerapi_data_db.py` (56 passed); full SeerAPI pytest (268 passed); Ruff; `scripts` compileall; `git diff --check` | Effect icon PNG cache seed, shard rendering and shard export now use the dedicated CLI adapter. The entry script fell to 1,395 lines. Final orchestration and metadata publication remain. |
| 2026-08-15 | `seerapi` `9d197bd` | focused metadata/build tests (57 passed); full SeerAPI pytest (269 passed); Ruff; `scripts` compileall; `git diff --check` | `seerapi_metadata` construction and upsert now belong to a dedicated no-network projection. The entry script fell to 1,226 lines. Final orchestration remains. |
| 2026-08-15 | `seerapi` `13730e4` | focused build tests (56 passed); full SeerAPI pytest (269 passed); Ruff; `scripts` compileall; CLI `--help`; `git diff --check` | Final publication transaction, official source loading and classic-skin resource lookup are separate modules. The entry script is 727 lines; all new production modules are below 800 lines. Real release and IronsBot consumer smoke remain a release gate, not a local unit-test claim. |
