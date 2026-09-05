# 新增内容菜单领域规划与平台适配

Status: `verified`

Contract: `target`

Owner: `services.seer.new_content_menu` / `plugins.onebot.seer.query.commands.new_content`

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)

## Problem

`commands/data_queries.py` 同时承担普通数据查询、分类比较、菜单布局及 OneBot 会话。
此前只迁出了详情文本格式化，平台无关的选择规则仍需要导入插件才能测试。

## Goal And Ownership

新增内容的分类可比较性、空数据文案、自动展开、分类聚焦和选项列表由纯服务负责。
服务输入发布快照、允许的分类与请求分类，返回菜单计划或明确提示；不接收 QQ 事件。
OneBot 适配器把选项转换成既有 `Prompt`，继续复用会话队列、权限判断和渲染服务。
`data_queries.py` 仅保留预告、版本、赛季倒计时；命令统一安装处登记两个适配器。

## Design

- 复用现有 `NewContentSnapshot`、类别可比较性和条目描述函数。
- 使用不可变菜单布局、选项、动作与计划值对象；不建立新的通用菜单运行时。
- 文本和图片菜单读取同一个布局与自动展开上限。
- 保留根菜单字母编号、分类菜单数字编号和 `0` 退出。
- 保留类别权限、图片渲染失败时的文本菜单、详情查询和 @ 发言人。
- 删除旧插件的菜单实现，不保留重导出或兼容包装器。
- 不新增依赖、TOML、数据库或跨仓库发布契约。此项缩减耦合，不宣称减少镜像 MiB。
- 工作区内的 pytest 临时目录同时由 Git 与 Docker 忽略，避免本地安装夹具进入提交。

## Acceptance

- [x] 可在不导入 NoneBot 插件的情况下验证菜单规划、空数据和权限输入。
- [x] 根菜单、分类聚焦、自动展开阈值、组合分类保持当前行为。
- [x] 禁止访问的类别不能进入菜单计划或聚焦操作。
- [x] OneBot 文本菜单、图片回退和菜单重新发送继续使用既有 Prompt 会话。
- [x] 周预告、版本、赛季查询与新增内容命令仍只注册一次。
- [x] 删除旧实现；架构/800 行守卫、Ruff、类型检查和相关测试通过。

## Migration And Evidence

无数据迁移。回滚以独立提交为单位。
2026-09-05：新增内容领域、菜单适配、预告、命令安装和架构回归 98 passed；
真实 bootstrap smoke 通过，三个改动生产模块的 BasedPyright 为 0 errors；Ruff 通过。
本轮完整回归为 1541 passed（87 条现有依赖告警）。随后补齐类型标注与启动流类型
检查，相关菜单、配置错误和发布库验证 12 passed；全仓 BasedPyright 0 errors，
Ruff、compileall、diff 检查通过。

文件职责：普通数据查询适配器 95 行，新增内容适配器 442 行，平台无关菜单规划
155 行。提取只减少平台耦合，生产总行数没有减少，不作为镜像减重证据。
