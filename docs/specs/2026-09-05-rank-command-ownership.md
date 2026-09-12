# 参数化榜单命令认领

Status: `verified`

Contract: `target`

Owner: `services.seer.rank_command_contracts` / 现有榜单领域解析器

## Problem

`专家榜15名` 可被 parse_rank_list_command 解析，但有 seer_rank 权限的私聊用户
在 CommandCatalog 中不被认领。现有榜单描述主要只有标题示例；页码、区间、分数、
玩家引用和管理命令参数没有使用对应 parser。另一个公共缺陷是目录将文本和示例
的前导 `/` 都删除，会认领领域要求斜杠而用户未输入斜杠的管理命令。

## Design

- 四类榜单 contract（全服/样本、收集/巅峰）使用实际 list/score/player parser
  认领，分类依据 GLOBAL_RANKS / LOCAL_RANKS，不复制榜名或数字正则。
- 玩家引用复用 actor-aware PlayerIdResolver 和公共数字/别名认领规则。普通未知
  文字不算玩家命令；数字保留给实际查询报告无效米米号。认领不访问绑定或网络。
- rank_help 贡献注入应用现有 resolver，不新增实例或可选旧接口。
- 管理参数分别复用显示条数、缓存状态、刷新、区间 parser；固定管理命令常量归入
  领域，同时供 matcher 与目录使用。移除只为插件拼接这些常量的旧 helper。
- catalog 精确文字匹配保留 `/`；可选前缀只由明确登记的别名或领域 parser 处理。
  不新增命令关键词保护表，不改变 matcher 优先级。
- 前缀影响审计：活动 ending/new 原本允许可选 `/`，current 与 B站刷新必须带 `/`。
  活动目录复用三个已有纯文本判断；B站刷新纯文本判断从适配器移到已有 commands
  服务，并由目录和 OneBot rule 共用。不能依赖公共目录删斜杠来保留合法写法。
- 帮助/戳一戳仍先按原 feature、scope、audience 过滤。群主/管理员只能认领群管理
  命令，缓存操作仍为超级管理员；私聊不开放群显示条数管理。

## Non-Goals

不修改查询算法、缓存、TOML、榜单输出、额度或生产数据。不在这一项宣称 Phase 5
整体验收；完整玩家多榜渐进返回及其余领域参数化入口仍须检查。

## Acceptance

- 榜单 map 中所有标题/别名和页码、名次、范围都被正确分类，只有全服榜接受分数
  和玩家引用；同一输入不被两类榜单 contract 同时认领。
- 普通/本群/管理员别名权限一致；未知文字、错误范围不冒充合法查询。
- 管理命令的参数和别名被认领，但缺少 `/`、普通成员越权、私聊群管理均不认领。
- 真实私聊 AI 捕获规则对上述合法输入让行，对普通聊天保留原行为。
- 公共精确命令前缀回归；真实标准清单装载及命令目录校验。
- Ruff、BasedPyright、完整公开 pytest、私有 pytest、compileall、diff 检查。

## Progress And Evidence

总进度 4/8，本项已完成；整体 ETA 未定。

- 2026-09-05：榜单 map 的全部别名 × 四种窗口，加管理/AI/失败输入矩阵，
  修复前 482 failed / 45 passed；数字表示输入组合，不是独立 bug 数。
- 活动/B站前缀影响矩阵修复前 11 failed / 18 passed，确认不能依赖全局删前缀。
- 修复后榜单、目录、领域来源与既有榜单服务专项 640 passed。
- 最终公开完整 pytest：2209 passed，87 条既有依赖告警，90.52 秒。
  包含标准清单装载、目录注册、私聊 AI 规则与架构边界回归。
- 私有仓库指定当前 V5 公共检出的实际 pytest：26 passed，未修改私有文件。
- Ruff 全仓通过，BasedPyright 0 errors / warnings / notes，compileall 与
  git diff --check 通过；无新增依赖、配置/schema 迁移或生产操作，未执行 push。
- 仍可复现 B站推送模式参数未接入认领，记入 Phase 5 剩余项；本项不是全命令或
  整体重构完成的证明。未做真实平台网络 smoke 或镜像体积测量。
