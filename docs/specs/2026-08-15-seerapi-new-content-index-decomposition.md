# SeerAPI 新增内容索引构建职责拆分

Status: `in_progress`

Contract: `transition`

Owner: `seerapi` 每周新增内容索引发布管线

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#engineering-principles)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

`scripts/build_new_content_index.py` 负责 CLI、SQLite schema 检查、当前内容快照、历史
快照读取、语义比较、每周状态迁移和 release 写入，当前仍为 1,037 行。它超过长期 800 行
限制；新类别继续写进该脚本会把数据提取、比较规则和发布编排混成一个入口。

## Goal

将新增内容索引分成三个可独立验证的职责：

1. `new_content_index_models.py`：内容项、语义摘要、类别与 schema 迁移规则；不访问 SQLite。
2. `new_content_index_snapshot.py`：从当前 SQLite 读取类别快照；不读取路径、CLI 或写 release。
3. `build_new_content_index.py`：读取前一 release、调用纯比较、写入 release 表和 CLI 编排。

最终 CLI 脚本不超过 800 行；不能因为迁移而恢复重复语义摘要、双比较路径或运行时兼容层。

## Required Invariants

- `ContentItem.semantic_digest` 对相同 SQLite 内容保持字节稳定。
- `pet` 的轮换池字段、`skill` 的关联精灵、`pet_skin` 的展示精灵名、`mintmark` 的旧
  rarity 分类仍不产生伪更新。
- 所有当前类别在同一数据库快照下保留稳定 `(category, entity_id)` 排序。
- 不完整来源继续产生既有 category state；不得伪装为“无新增”。
- 发布 SQLite schema、CLI 参数和 IronsBot 消费表不变。

## Delivery Slices

| Slice | Acceptance criteria | Status |
| --- | --- | --- |
| Pure models | 模型、语义摘要和迁移规则脱离 SQLite 构建器；全量回归通过 | completed (`seerapi` `9d04eb4`) |
| Current snapshot | 当前 SQLite 的类别读取、表/列探测和 payload 解码脱离 CLI | planned |
| Release history/write | 历史状态读写和 CLI 编排各自保持单一职责，主脚本不超过 800 行 | planned |
| Release smoke | 用前一 release 建立新索引并由 IronsBot 读取，验证新增/修改/未知来源语义 | planned |

## Verification

- 每个 slice 运行 `tests/test_build_new_content_index.py`、Ruff、compileall、CLI `--help`
  和 `git diff --check`。
- 完成前运行 SeerAPI 全量 pytest；仅真实生成的 release 可作为跨仓库 smoke 证据。
- 不把“文件变短”当成完成证据；必须证明上述语义输出不变。

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-08-15 | `seerapi` `9d04eb4` | 新增内容 focused pytest（29 passed）；SeerAPI 全量 pytest（263 passed）；Ruff、compileall、CLI `--help`、`git diff --check` | 模型层已脱离构建器；脚本由 1,195 行降至 1,037 行。当前快照和发布历史仍在同一编排脚本，不能把 800 行目标误报为完成。 |

## Progress

```text
Program  [████████░░] 79%  global verified progress; this spec does not change it
Phase    [███░░░░░░░] 25%  verified slices: 1/4  estimated remaining: 1-2 h
Current  [██████████] 100% pure model extraction verified; next: current SQLite snapshot boundary
```

Only verified, committed, or explicitly waived work counts toward progress.
