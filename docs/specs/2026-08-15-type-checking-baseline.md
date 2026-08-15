# V5 类型检查基线与收口

Status: `implementing`

Contract: `target`

Owner: `application composition、领域 port 和测试 fixture`

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#engineering-principles)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

当前 V5 的运行测试、Ruff、静态仓库检查和编译都通过，但 `basedpyright` 在
2026-08-15 的实际运行中报告 46 条错误。它们主要来自尚未完全删除的 B 站 runtime
桥接、V5 composition 的 port 签名、Seer repository 的 `object` 解码，以及测试用假
实现未满足正式 protocol。若以 `Any`、全局 ignore 或降低检查级别处理，会掩盖正在
迁移的平台和数据边界。

## Goal

在保持当前用户行为和运行测试的前提下，让 `uv run basedpyright` 返回零错误。每个
修复必须收紧真实边界：删除退役桥接、修正 port/adapter 类型，或让 fixture 实现其
所声明的 protocol。

## Non-Goals

- 不降低 `basedpyright` 的 `standard` 检查级别。
- 不新增模块级 `# type: ignore`、`Any` 或宽泛 union 来压制未知边界。
- 不将测试 fixture 的类型问题伪装成生产代码错误已解决。

## Ownership And Reuse

- Semantic owner: 每个领域的正式 port/值对象；composition 只连接它们。
- Reused contracts: `ApplicationResources`、B站 delivery port、Seer repository
  snapshot、OneBot prompt contract。
- Adapter boundary: 平台对象只停留在 OneBot adapter；测试 fake 必须实现同一 protocol。
- Why a new interface is or is not needed: 先使用已声明 protocol；只有现有 protocol
  不能表达运行时必须能力时，才在 owner 模块增加窄方法。

## User And Data Contract

- Inputs: 当前 V5 代码与测试 fixture。
- Outputs: 无新增用户命令或持久化数据；类型检查失败变为零错误。
- Permissions and scope: 无变化。
- Persistence: 无。
- Compatibility: 不保留为类型检查临时存在的旧 runtime/import bridge。

## Design

按真实依赖方向处理，而不是按报错文本逐条修补：

1. **删除或迁移旧 B站桥接。** `app/bilibili_runtime.py` 的 10 条错误表明它仍引用
   已退役模块并假设旧 `ApplicationResources` 字段。先确认真实 import graph；若无
   正常路径引用则删除，若仍有调用方则迁入当前 `BilibiliComponents`/delivery port。
2. **收紧 Seer 数据解码和 composition port。** 处理 `object -> int`、预告图片 source、
   分类 literal 与 repository 返回值；边界处校验后再构造类型化快照。
3. **对齐 OneBot 与 B站 callback protocol。** prompt queue 参数和动态推送回调必须由
   唯一 protocol 定义，不能让 adapter 与测试各自猜签名。
4. **让测试 fake 成为正式 contract 的最小实现。** AI client、B站 delivery、确认会话
   和渲染器 fixture 应显式实现 protocol 或使用窄 test-only fake，不扩宽生产接口。

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| B站旧桥接 | 删除无调用桥接，或迁入当前 composition；消除 10 条错误 | import graph 审计 | verified |
| Seer typed snapshots | repository/composition 不再把未验证 `object` 传入领域模型 | published data ports | verified |
| Adapter callback contracts | OneBot/B站回调与队列参数只有一份 protocol | runtime contract | verified |
| Fixture conformance | 测试 fake 满足正式 protocol，测试语义不降级 | 前三项完成 | planned |

## Migration And Rollback

- Migration: 无数据迁移。
- Rollback: 每个切片独立提交；恢复到上一个可通过运行测试的提交。
- Removal condition: 不存在只为过渡而保留的旧 runtime import 或资源字段假设。

## Acceptance Tests

- [ ] `uv run basedpyright` 为 0 errors。
- [ ] `uv run pytest -q` 仍通过。
- [ ] `uv run ruff check ironsbot tests scripts` 仍通过。
- [ ] 静态架构检查、`compileall` 与 `git diff --check` 仍通过。
- [ ] 不新增全局 ignore、宽泛 `Any` 或旧路径兼容导入。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | 建立 V5 质量基线 | pytest 1519 passed；Ruff；repo static；compileall | 运行质量门禁通过。 |
| 2026-08-15 | 运行 BasedPyright | `uv run basedpyright` | 46 errors：B站旧桥接 10、B站测试回调 5、推送时间 handler 3、AI fixture 3，其余为 Seer repository/composition/fixture 边界。 |
| 2026-08-15 | 审计 B站旧运行桥接 | `rg` import graph、composition 对照 | `app/bilibili_runtime.py` 无调用方；真实路径是 `bilibili_composition -> BilibiliDynamicOutboundSender`。 |
| 2026-08-15 | 删除 B站旧运行桥接 | B站/插件/架构测试 85 passed；Ruff；repo static；BasedPyright | 类型错误由 46 降至 36；当前真实 B站 composition 未受影响。 |
| 2026-08-15 | 对齐 B站推送测试回调 | B站监控测试 37 passed；Ruff；BasedPyright | `DynamicPushSender` 的五参数 contract 成为测试唯一签名；类型错误由 36 降至 31。 |
| 2026-08-15 | 清理 OneBot 菜单伪页面参数 | OneBot prompt/confirmation 测试 10 passed；Ruff；BasedPyright | 删除未写入会话状态的 `page_id` 参数，确认测试使用正式 `Matcher` contract；类型错误由 31 降至 24。 |
| 2026-08-15 | 收紧 Seer 数据快照边界 | Seer autocard/new-content/type-query 测试 54 passed；Ruff；BasedPyright | JSON 数值、ORM 属性组合与渲染分类在边界显式转换；类型错误由 24 降至 13。 |

## Progress

```text
Program  [████████░░] 79%  verified phases: 3/8  estimated remaining: depends on cross-repo data ports
Phase    [████████░░] 75%  verified slices: 3/4  estimated remaining: 30-90 minutes
Current  [██████████] 100% next: extract the remaining composition and fixture contracts
```
