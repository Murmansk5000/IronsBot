# 配置回复的直接与自动入口

Status: `verified`

Contract: `target`

Owner: messaging 领域选择逻辑与 OneBot matcher 安装

## Problem

仅配置 keyword_replies 时，配置回复 matcher 因 command_help_ids 为空而不安装。
存在精确口令时关键词虽能触发，却沿直接命令的会话结束策略，并与同 ID 精确口令
共用冷却键。只扩大安装条件会继续混淆自动回复与用户指令。

## Design

- 直接与自动回复各登记一个 matcher，复用同一个选择规则与发送 handler；不是
  每个配置动作生成一个 matcher。各自仅在存在已启用动作时安装。
- 领域 match_action 显式接收 direct/automatic。两类共享精确口令优先规则；
  同一输入只有一个 matcher 成立，不依赖相同优先级的执行次序。
- 自动入口绑定自己的 keyword help IDs，保持 automatic 目录属性，不参与 AI
  直接命令认领；使用已有 closes_active_conversation=False，不增加新的调度器。
- 直接冷却 ID 保持 message.<id>；自动为 message.keyword.<id>，避免配置中同名
  动作互相影响。不保留缺失动作时返回泛化 ID 的静默回退。
- 只做同一功能的输入和注册收口，保留 feature、QQ 回复/@ 排除、正文和发送语义。
  不改推送菜单、状态数据库、TOML 或运行依赖。

## Acceptance

- 仅关键词、仅精确、混合、全关闭、空配置的真实插件安装和 catalog 校验。
- 自动关键词实际 rule 可触发；精确/关键词相撞时至多一个 matcher 成立。
- 禁用或无 feature 权限的精确口令不阻断合法关键词；所有动作各自检查权限。
- 自动命中不结束菜单，直接命令仍沿正常命令策略；冷却 ID 不冲突。
- 自动说明不被 AI 当成直接输入，也不作为戳一戳候选。
- 相关选择、发送、菜单、matcher、AI 测试，以及 Ruff、类型、公开/私有回归、编译、diff。

## Evidence

- 改动前真实插件安装矩阵：2 failed / 6 passed；仅关键词无 matcher，混合配置没有
  独立自动入口。最终矩阵检查真实 rule 与 matcher 默认状态，确认同一输入最多一个
  入口成立，且仅 direct 设置结束旧会话标记。
- 选择/发送相关专项 66 passed；覆盖独立功能权限、禁用动作、exact 优先、自动词条
  不进入目录直接认领/戳一戳、冷却 ID 隔离与缺失动作状态不静默成功。
- 公开全量 `uv run pytest -q --basetemp=.test-tmp/keyword-full`：2302 passed，
  271 条既有依赖告警（安装矩阵增加同类告警次数），94.15 秒。
- 私有仓库指定当前 V5 为 IRONSBOT_PUBLIC_ROOT：26 passed。
- BasedPyright 对 ironsbot/tests 为 0 errors / warnings / notes；Ruff、compileall
  和 git diff --check 通过。
- 没有新增运行模块、依赖、配置字段或数据库；没有生产操作。若部署者曾为关键词
  单独配置 command_cooldown.commands，键从 message.<id> 改为 message.keyword.<id>；
  精确口令键保持不变，默认冷却配置无需修改，不提供旧键兼容。
- 本地 main 仍为 f19c7089，本轮只读引用。总进度保持 4/8，下一道审计重点为
  玩家多榜独立失败与渐进返回，不把所有命令或 Phase 5 宣称为已完成。
