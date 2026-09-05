# 离线状态库安装与回滚统一

Status: `verified`

Contract: `target`

Owner: `state_migration_files`，两个离线迁移服务复用

## Problem

平台身份迁移在替换主库、删除 sidecar 后才登记回滚目标。sidecar 删除失败时，
已经替换的主库不会恢复。状态收口迁移若在删除旧库的中途失败，会删除新库，
却不会恢复已经删除的旧库。两处均可能留下一套不完整的状态文件。

## Design

- 在现有文件模块中建立统一 SQLite bundle 变更计划：目标、已验证的替换文件、
  原始备份。删除旧库也是同一计划的一种变更，不另设破坏性清理阶段。
- 执行前检查计划中目标与备份/临时文件不重叠；已有目标必须有备份，缺主库却有
  sidecar 时拒绝操作。迁移调用者仍负责 SQLite 行数和完整性验证。
- 每个目标在第一次改动前登记；同步异常和 KeyboardInterrupt 均尝试逆序回滚。
- 恢复先复制备份到同目录临时 bundle，再替换目标；任何恢复失败都继续恢复其他目标，
  最终报告失败路径及备份位置。备份永不由安装函数删除。
- 备份、恢复、删除共用主库、WAL、SHM 和回滚日志的 bundle 定义。
- 两套迁移删除重复的安装/恢复循环；CLI 仍为 `python -m ironsbot.state_migration`。
- 不新增 TOML、运行时兼容或隐式迁移，不操作生产数据。

## Boundary

单个文件使用原子替换；多个文件并非文件系统事务。本项保证可捕获异常时的补偿恢复，
不能宣称断电、SIGKILL 或机器故障时自动回滚。无法恢复时必须保留备份供停机恢复。
阶段 1 仍需独立审计全部身份与部署迁移完成门，本项不将其直接标为完成。

## Acceptance

- [x] 两套 CLI 路径保持 dry-run、正常迁移和幂等行为。
- [x] 第二个库替换失败，之前已替换的库恢复原内容。
- [x] sidecar 删除失败与旧库清理中途失败，不丢失已有库。
- [x] 回滚一项失败不阻止其余项恢复，错误包含保留备份的路径。
- [x] 无备份/路径重叠计划在任何文件变更前拒绝。
- [x] 新建目标失败后清除，原有 bundle 包括 sidecar 完整恢复。
- [x] 相关测试、Ruff、BasedPyright、compileall、diff 检查通过。

## Evidence

2026-09-05：临时目录中的文件故障、两套迁移及身份存储测试 28 passed；
全仓 pytest 1562 passed，87 条已有依赖告警。全仓 BasedPyright 0 errors；
Ruff、compileall 与 diff 检查通过。未执行生产迁移。
文件恢复测试覆盖 PermissionError、KeyboardInterrupt、sidecar 和后续恢复失败；
真实 SQLite 迁移夹具验证失败后原库字节一致、没有半迁移标记且可重试成功。
此项新增必要的错误处理，生产总行数有所增加，不作为镜像瘦身成果。
