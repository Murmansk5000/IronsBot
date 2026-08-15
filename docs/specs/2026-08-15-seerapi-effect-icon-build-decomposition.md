# SeerAPI 效果图标构建职责拆分

Status: `in_progress`

Contract: `transition`

Owner: `seerapi` 构建期效果图标 PNG 发布管线

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#rendering-and-published-seer-data)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

Related manifest spec: [SeerAPI 渲染素材 Manifest 职责拆分](2026-08-15-seerapi-render-manifest-decomposition.md)

## Problem

`seerapi/scripts/build_seerapi_data_db.py` 仍同时实现效果图标的 Flash URL 探测、DefaultPackage
Unity 资源定位与解码、Flash/Unity 优先级与逐个回退、FFDec 子进程调用、可见像素校验、磁盘
缓存、分片预热、缺图诊断和 SQLite 写入编排。它既读取环境变量，又发 HTTP、导入 UnityPy、
调用 Java、读写缓存，并决定 release metadata。

这不是一个可维护的单一模块。尤其是“素材来源选择”与“PNG 生成”有不同失败语义：官方资源
不可用、Unity 包缺图、FFDec 超时、缓存失效和 SQLite 发布失败不能互相伪装。当前直接构建器
约 4,122 行，继续把新的渲染策略放入其中会违背 800 行目标和已建立的 adapter 边界。

## Goal

将效果图标构建拆为三个有真实职责边界的 SeerAPI 模块。结果必须保持当前发布 SQLite 中的
`soulmark_icon` PNG、availability、缺图 issue、effect-icon metadata 和 render manifest entries
语义不变。

1. `effect_icon_sources.py`：只负责官方 Flash/Unity 素材定位、下载和来源优先级解析。
2. `effect_icon_png_renderer.py`：只负责给定 SWF 或 Unity 图片生成、校验和缓存 PNG。
3. `effect_icon_build.py`：只负责把来源选择与 renderer 协调为一个完整、可诊断的结果，并支持
   cache shard 的窄用例。

`build_seerapi_data_db.py` 最终只构造配置和 adapter、调用完整结果、写入已存在的 SQLite 表与
metadata。它不得重新拥有图标解析、缓存或子进程细节。

## Non-Goals

- 不改变 Flash 优先、Unity 优先、逐图标回退和 `require_cached` 的当前配置语义。
- 不改变 FFDec 版本、Java 运行参数、PNG 可见像素/最大尺寸规则或缓存版本格式。
- 不把 FFDec、Java、UnityPy 或 Pillow 带入 IronsBot Docker runtime；它们只在 SeerAPI 的 GitHub
  Actions 构建环境中存在。
- 不改变座驾 SWF 转 PNG；它有独立发布契约。
- 不在此 Slice 修改已发布 SQLite schema 或增加运行时 SWF 回退。

## Ownership And Reuse

- Semantic owner: effect-icon build domain 拥有“从官方素材生成可发布效果图标 PNG”的事实。
- Reused contracts: `ConfigPackageData.soulmark_icons`、现有 `soulmark_icon` 与
  `soulmark_icon_render_issue` 表、render manifest v2、`render_asset_manifest_build`。
- Adapter boundary: HTTP 下载和 UnityPy/FFDec/filesystem 操作止于 SeerAPI build modules；
  IronsBot 仅消费发布 PNG 与 metadata。
- New interfaces:
  - `EffectIconBuildConfig`：所有原先由环境决定的 URL、优先级、超时、并发、FFDec、缓存版本
    和路径的已解析值，不在领域模块读取 `os.environ`。
  - `EffectIconSourceGateway`：下载 bytes、探测 Flash、读取 Unity package manifest 的窄 adapter。
  - `EffectIconPngCache`：按 `(icon_id, source fingerprint, renderer version)` 读取和原子写入 PNG。
  - `EffectIconBuildResult`：每个 icon 的 source check、PNG render、优先来源、fallback 统计与
    诊断错误。SQLite 写入层只接收这个结果。

## User And Data Contract

- Inputs: ConfigPackage 解析出的图标 ID 集合、已解析 `EffectIconBuildConfig`、官方资源 adapter、
  可选旧 PNG 缓存。
- Outputs: 每个 ID 的确定性 PNG 或失败事实；不允许缺图被标记为 available。
- Permissions and scope: 仅 SeerAPI 构建和 cache-shard CLI；不影响任何 QQ 命令或机器人镜像。
- Persistence: 磁盘缓存是构建加速器，发布 SQLite 是唯一消费者事实。缓存丢失只导致重建，不能
  被当作发布数据缺失的双读来源。
- Compatibility: 新模块是唯一正常实现。旧 `_resolve_effect_icon_png_assets`、FFDec/cache helper
  和 Unity/SWF source helper 在迁移完成后删除，不保留包装函数。

## Design

| Module | Owns | Does not own |
| --- | --- | --- |
| `effect_icon_sources.py` | Flash range probe、Unity manifest/bundle 选择、每个 ID 的候选来源与 source fingerprint | FFDec、PNG disk cache、SQLite、环境变量 |
| `effect_icon_png_renderer.py` | PNG 透明/尺寸校验、FFDec sprite/shape export、原子磁盘缓存、有限并发 | HTTP、Unity manifest、来源优先级、SQLite |
| `effect_icon_build.py` | Flash/Unity 选择顺序、逐 ID 回退、失败分类、分片预热、结果统计 | 直接 `os.environ`、原始 SQL、metadata 写入 |
| `build_seerapi_data_db.py` | 环境配置、HTTP/Unity adapter 装配、ConfigPackage 输入、SQLite 表与 metadata 写入 | 图标策略实现、FFDec 命令、缓存路径拼装 |

### Required invariants

1. 每轮只为同一图标发布一个结果；Flash 与 Unity 均成功时，必须按当前配置的优先来源选择。
2. 一个来源超时或失败只影响该图标，能使用另一个官方来源时仍发布 PNG。
3. `require_cached=true` 只拒绝本应可取得但未获得 PNG 的图标；官方明确 404 的图标保持明确缺失。
4. cache metadata 必须至少含 source fingerprint、content length 和 renderer version；三者任一
   变化都不能复用旧 PNG。
5. FFDec 的 composite 失败可回退 shape export；两者生成透明、过大或不可读 PNG 必须失败而非
   写入缓存。
6. cache-shard 使用与完整构建相同的 resolver/renderer，不得保留第二套生成路径。

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| Types/config | `EffectIconBuildConfig` 与结果值对象可由构建器显式构造；无模块读取环境 | 本 Spec 接受 | completed |
| Renderer/cache | FFDec、PNG 校验、缓存与并发移出总构建器；原测试迁到模块 | Types/config | completed |
| Source adapters | Flash/Unity 探测、包解码和每图标来源事实移出总构建器 | Types/config | planned |
| Resolver/shard | 优先级、回退、缺图诊断与 shard 复用同一 resolver | Renderer/cache + source adapters | planned |
| Release smoke | 全量 release 构建、PNG/issue 行、metadata、manifest 与 IronsBot consumer smoke 验证 | 所有前序 slice | planned |

## Migration And Rollback

- Migration: 无用户数据库迁移；先将现有测试转到新模块并用固定 bytes/fixture 锁定结果，再删除
  总构建器 helper。
- Rollback: 构建流程只在生成 release 后替换产物。任何 slice 失败不发布新 SQLite；可回滚独立
  提交，但不恢复旧新双路径。
- Removal condition: 全量 build、cache-shard 和缺图 issue 测试均经新模块通过后，原构建器不再
  定义 Unity/SWF source、FFDec/cache 或 resolver helper。

## Acceptance Tests

- [ ] Flash 优先与 Unity 优先的单图标回退行为与现有 fixture 一致。
- [ ] Unity bundle 中 Sprite/Texture2D 的优先选择、无可见 PNG 与下载异常分别记录正确结果。
- [ ] composite -> shape FFDec 回退、透明图、超尺寸图、缓存 source/content/version 失效均验证。
- [ ] 多 worker 完成顺序不改变按 icon ID 发布的结果；同一 ID 不重复渲染。
- [ ] cache shard 与完整构建使用同一 resolver/renderer，输出一致。
- [ ] `soulmark_icon`、issue、metadata 和 manifest entries 与现有发布 fixture 语义一致。
- [ ] SeerAPI 全量 pytest、Ruff、CLI、compileall、`git diff --check`，以及真实 release 的
  IronsBot consumer smoke 通过。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | 当前代码依赖审计 | 函数调用图、图标测试清单、GitHub Actions build workflow | 目前 source、FFDec、cache、resolver 和 shard 均在总构建器；Actions 已正确只在构建环境安装 Java、UnityPy、Pillow 与 FFDec，IronsBot runtime 未引入这些依赖。 |
| 2026-08-15 | SeerAPI `c1faedf` | `uv run pytest -q`（260 passed）、Ruff、构建器 `--help`、compileall、`git diff --check` | `effect_icon_build_types.py` 解析配置和值对象，`effect_icon_png_renderer.py` 成为 FFDec、PNG 校验、缓存和并发的唯一实现；总构建器从 4,122 行降至 3,542 行。source adapters、resolver/shard 与真实 release consumer smoke 尚未完成。 |
| 2026-08-15 | SeerAPI `6ff44d0`、`1f8d029` | effect-icon 构建测试 51 passed、Ruff、compileall、`git diff --check` | Flash/Unity URL、asset path、来源 URL 与 ID 解析迁入纯 `effect_icon_source_paths.py`，只接收 `EffectIconBuildConfig`；构建器删除 50 行路径规则。Unity bundle 与 Flash HTTP adapter 仍在构建器，尚未宣称 source-adapter slice 完成。 |

## Progress

```text
Program  [████████░░] 79%  global verified progress; this draft does not change it
Phase    [████░░░░░░] 40%  verified slices: 2/5   estimated remaining: 3-5 h
Current  [██████████] 100% renderer/cache extraction verified; next: isolate Flash/Unity source adapters
```

Only verified, committed, or explicitly waived work counts toward progress.
