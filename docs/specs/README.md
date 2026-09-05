# IronsBot Feature Specs

本目录存放可执行的功能 Spec。它把一次改动的产品行为、边界、迁移与验收写成
可核对的记录，避免需求在插件、测试、聊天记录和提交说明之间分叉。

## 何时需要 Spec

以下改动必须先创建 Spec：

- 跨模块、跨仓库或跨平台边界；
- 新增或修改公开命令、帮助、权限、配置或定时行为；
- 新增、迁移或删除持久化数据；
- 改变渲染输入、发布数据 schema 或资源管线；
- 从 `main` 吸收与 V5 目标架构存在目录或职责冲突的功能。

小型局部 bug 修复可以使用任务中的短设计记录，但一旦调查发现它影响上述任一项，
立即转为 Spec。

## 文件与状态

- 文件名使用 `YYYY-MM-DD-<domain>-<short-name>.md`，例如
  `2026-08-15-upstream-weekly-activity-snapshots.md`。
- 每份 Spec 顶部必须有 `Status`、`Contract` 和 `Owner`。
- 状态仅可为：`draft`、`accepted`、`implementing`、`verified`、`completed`、
  `blocked`、`superseded`。
- `completed` 必须列出实际运行的验证和已知风险；`blocked` 必须说明阻塞条件及
  下一步，不得把猜测写成完成。
- 一份 Spec 只覆盖一个可独立验收的用户行为或数据契约。范围扩大时拆分，而不是
  把所有相邻重构塞进同一份文件。

## 文档职责

- [ARCHITECTURE.md](../../ARCHITECTURE.md)：长期目标、所有权和禁止事项。
- [engineering-workflow.md](../engineering-workflow.md)：实施、审查、进度与提交纪律。
- [multiplatform-refactor.md](../multiplatform-refactor.md)：阶段依赖和已验证账本。
- 本目录：本次功能的可执行范围、决策、验收与证据。

Spec 不复制前三者。它只链接相关章节，并明确本次如何遵守它们。

## 最小工作流

1. 从 [TEMPLATE.md](TEMPLATE.md) 创建 Spec，写清现状、目标、非目标和验收标准。
2. 将状态改为 `accepted` 后才开始生产代码；跨仓库工作先记录发布顺序。
3. 每个实现切片只完成一个或几个验收标准，并在 Spec 中追加实际验证证据。
4. 上游同步时，先列出 commit、行为和 V5 owner；不得直接复活旧路径来消除冲突。
5. 所有验收项通过后标记 `verified`；提交、回滚点和残余风险就绪后标记 `completed`。

Spec 是持续维护材料：发现真实数据或测试改变结论时先更新它，再改代码。
