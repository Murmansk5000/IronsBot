# 共享 SQLite 版本检查只读路径

Status: `verified`

Contract: `target`

Owner: `integrations.storage.sqlite.SqliteDatabase`

## Problem

每次连接都在检查迁移版本前执行 `BEGIN IMMEDIATE`。共享状态库或大型缓存已经是
当前版本时，一个纯查询也必须等待其他写事务释放。命名空间版本检查还包含建表语句，
读取和初始化责任没有分开。

## Design

- 复用现有数据库接口，先只读查询 user_version 或指定 namespace 版本。
- 版本相同直接进入调用者操作，不获取迁移写锁，不执行 CREATE/INSERT/UPDATE。
- 版本过新明确拒绝；无 namespace 元数据表时视为未初始化，不在读取函数中建表。
- 只有待执行迁移时获取 `BEGIN IMMEDIATE`，锁内再次读取并验证版本。
- namespace 元数据表仅在有待执行迁移的写事务中创建。
- 不缓存“已检查版本”的进程标记，后续打开替换后的数据库仍须重新验证。
- 保留现有 WAL、busy timeout、事务提交/回滚、独立 user_version 与 namespace 模式。
- 不引入线程池、连接池、配置项、旧表迁移或数据库双读。

## Acceptance

- [x] 已提交数据可在另一连接持有 WAL 写事务时读取，不误读未提交写入。
- [x] 同版本连接的 SQL trace 不包含迁移 BEGIN IMMEDIATE 或元数据写入。
- [x] 两个并发初始化者只执行一次迁移，锁内版本检查不可省略。
- [x] 等待写锁期间被升级到更高版本时，旧应用拒绝继续操作。
- [x] 失败迁移回滚、namespace 独立版本和新版拒绝保持有效。
- [x] 同一个 Database 对象在文件被替换后仍重新检查版本。
- [x] pytest、Ruff、类型检查、compileall、diff 检查通过。

## Scope And Evidence

该优化减少无必要的写锁，不能消除实际写事务的争用，不能宣称所有查询延迟都会改善。
测试使用临时 SQLite 和真实并发连接；不操作生产文件。不更改 TOML 或 schema。

2026-09-05：改动前两个 WAL 并发读取用例均在 `BEGIN IMMEDIATE` 处失败，
报 `database is locked`（共 11.52 秒，包含两次默认写锁等待）。修改后 SQLite
专项 23 passed；全仓 1573 passed，87 条已有依赖告警。全仓 BasedPyright 0 errors，
Ruff、compileall 和 diff 检查通过。本地 main 仍为 `f19c7089`，本项未同步或修改主线。
该证据证明避免了特定无必要的写锁，不是生产吞吐或所有查询延迟的基准测量。
