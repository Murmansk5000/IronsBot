# 玩家别名认领与执行权限一致性

Status: `verified`

Contract: `target`

Owner: `PlayerIdResolver` / `core.player_reference_commands`

## Problem

执行阶段的 PlayerIdResolver 根据 actor 选择普通或超级管理员别名查询；命令目录的
has_known_reference 只有 conversation，始终走普通查询。因而管理员能执行的私有
别名命令可能未被目录认领，进入私聊 AI。公开玩家查询、绑定、详情快捷查询和私有
阵容都消费同一认领接口，不能分别补关键词。

## Design

- 认领回调显式接收 reference、ActorRef、ConversationRef；不接受原生 QQ 事件。
- resolver 中只保留一个显式引用 lookup 选择点，执行与认领共同调用。
- 认领不读取默认绑定，不解析 @，不发送网络请求，不修改用户状态。
- CommandCatalog 继续先筛 feature、会话和权限；普通用户不能借认领取得私有别名。
- 私有阵容继续使用公开 resolver；同步其实际扩展测试，不保留旧回调签名包装器。
- 不改变别名存储、默认绑定、输入正则、米米号校验、TOML 或生产数据库。

## Acceptance

- 管理员私聊中，米米号、查询玩家信息、收集、巅峰、群星牌、绑定米米号使用私有
  别名时，目录认领结果与实际 resolver 一致，真实 AI 捕获规则让出该输入。
- 普通用户仅认领公开或本群开放别名；未知词仍可走普通聊天。
- 数字、空参数保持原行为；认领不会查询绑定记录。
- 私有阵容用同一 actor-aware 接口，实际扩展契约测试通过。
- 相关测试、全套公开测试、私有测试、Ruff、BasedPyright、compileall、diff 检查。

## Progress

总任务 4/8；本项已验收。Phase 5 仍需完整入口与多榜失败语义验收，本项不代表
阶段完成。整体 ETA 未定。

## Evidence

- 2026-09-05：真实账户 registry、resolver、Seer 命令 contract 和 catalog 组成的
  回归矩阵，修复前 6 failed / 30 passed，六个失败均为管理员私有别名。
- 修复后专项 58 passed；矩阵还执行真实 OneBot AI `_capture_ai_prompt`，确认有权
  别名让出输入、无权或未知别名继续原有聊天判断，认领不读取绑定状态。
- 公开全量 `uv run pytest -q --basetemp=.test-tmp/phase5-ownership-full`：
  1644 passed，87 条既有依赖告警，84.62 秒。
- 私有仓库使用 `IRONSBOT_PUBLIC_ROOT` 指向当前 V5 的实际 pytest：26 passed。
  包含真实私有 contribution + 公开 resolver 的管理员/普通用户别名认领测试。
- 公开 BasedPyright 0 errors / warnings / notes；两仓 Ruff、compileall 与 diff
  检查通过。没有运行网络查询、真实平台投递或构建镜像，不宣称其已验收。
- 未触碰 main、生产数据、配置、私有仓库原有未跟踪 uv.lock；无新增运行依赖。
