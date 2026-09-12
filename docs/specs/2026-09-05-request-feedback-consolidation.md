# 查询状态提示统一接口

Status: `verified`

Contract: `target`

Owner: `services.operations.request_feedback` / `runtime.in_flight_requests`

## Problem

命令入口使用 `request_feedback_scope`，封包调度器和玩家保护服务却读取
`core.request_coordination` 中另一份 ContextVar。现有调度器测试使用后者，
没有验证真实入口的提示上下文是否传递。后者还保留无人使用、以整数 QQ 号
为键的去重器，与现用的 ActorRef 去重服务重复。

## Scope And Design

- 命令、玩家服务、保护服务和封包调度器复用现有 `RequestFeedback`。
- 该接口增加当前上下文读取和显式反馈对象传递；工作流保留对象，支持跨任务执行。
- 一个查询只发送一次状态提示；发送失败记日志，不使查询失败，也不反复发送。
- 保留封包调度器按实际是否拿到 worker 判定排队的行为，不增加外层取消或重试。
- 删除整个旧 `core.request_coordination`，不保留旧符号和重导出。
- 删除无调用的 `core.onebot_group_identity`；群身份仍由现有平台适配器处理。
- 去重只使用现有 `InFlightRequestService`，不改变其权限、冷却或 token 语义。
- 不改 TOML、数据库、主线或其他仓库。检索私有仓库和 SeerAPI 未发现旧接口调用。

## Acceptance

- [x] 使用生产入口的 scope 测试空闲 worker 与排队 worker 的提示。
- [x] 多封包、并发发送和显式工作流对象均只发一次提示。
- [x] 独立/嵌套 scope 相互隔离，异常后恢复外层上下文。
- [x] 提示发送失败不影响查询，未设置 sender 时不发消息。
- [x] 玩家保护、详情会话和现用去重回归通过；旧实现无运行时引用。
- [x] Ruff、类型检查、compileall 和 diff 检查通过。

## Migration And Evidence

无数据迁移；独立提交可回滚。阶段整体保持原验收状态。
本轮获取远端后 `origin/main` 仍为 `f19c7089`；未合并到 V5。

2026-09-05：针对性测试 85 passed；全仓 pytest 1551 passed，87 条已有依赖告警。
全仓 BasedPyright 0 errors，Ruff、compileall 和 diff 检查通过。
生产代码净减少 258 行；该行数不是实际镜像减重测量，也不代表整体重构完成。
