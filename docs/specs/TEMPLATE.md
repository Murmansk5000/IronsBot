# <功能名称>

Status: `draft`

Contract: `target | transition | baseline`

Owner: `<domain service / port / repository / adapter>`

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md#change-design-gate)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

<用户或系统当前遇到的问题，以及已核实的事实。>

## Goal

<完成后可观察、可验收的行为。>

## Non-Goals

- <本次明确不处理的相邻问题。>

## Ownership And Reuse

- Semantic owner: <唯一领域 owner>
- Reused contracts: <现有值对象、port、resolver、repository>
- Adapter boundary: <平台适配在哪里停止>
- Why a new interface is or is not needed: <最小通用边界>

## User And Data Contract

- Inputs: <命令、事件、配置或发布数据>
- Outputs: <回复、状态变化、渲染或错误语义>
- Permissions and scope: <feature、用户、群或平台限制>
- Persistence: <数据生命周期、主键、迁移和备份；无则写无>
- Compatibility: <唯一正常路径；若迁移，旧路径删除条件>

## Design

<用短段落或表格说明实现切片、依赖关系和不变量。不要复制文件级实现细节。>

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| 1 | <可独立验证的行为> | <前置条件> | planned |

## Migration And Rollback

- Migration: <一次性工具、备份、校验或无>
- Rollback: <提交、备份或不替换生产数据的恢复点>
- Removal condition: <何时删除旧路径或兼容物>

## Acceptance Tests

- [ ] <正常路径>
- [ ] <权限或范围边界>
- [ ] <失败/超时/缺数据语义>
- [ ] <迁移或回滚验证，若适用>
- [ ] <架构、静态与针对性测试>

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| YYYY-MM-DD | <提交或工作切片> | <命令> | <事实，不写推测> |

## Progress

```text
Program  [░░░░░░░░░░] 0%   verified phases: 0/0   estimated remaining: <range>
Phase    [░░░░░░░░░░] 0%   verified slices: 0/0   estimated remaining: <range>
Current  [░░░░░░░░░░] 0%   next: <one concrete action>
```

Only verified, committed, or explicitly waived work counts toward progress.
