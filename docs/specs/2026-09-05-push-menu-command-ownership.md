# 推送菜单入口与会话回复分离

Status: `verified`

Contract: `target`

Owner: messaging 领域服务与 OneBot 菜单适配

## Problem

推送管理、TD、恢复订阅和推送时间实际是直接文本入口，却以 conversation 登记，
被 CommandCatalog 的直接输入认领跳过。菜单入口 matcher 也被当作二级回复豁免，
没有真实 command/help ID。推送时间实际支持私聊本人，目录仅声明群管理者。

## Design

- 菜单打开命令改为 direct，登记独立 command/help ID。后续数字、时间值仍仅由
  现有 PromptFlow / enter_prompt_loop 管理；不放宽 core 的 conversation 认领。
- 订阅命令文本由现有 subscription_options 统一构建：固定“推送管理”与当前
  commands / restore_commands 去重；领域服务和目录共用，不再重复维护字面量。
- 时间入口文本由现有 push_time 模块拥有，服务和目录共用。
- 订阅菜单保持群普通成员只读、管理员可修改和私聊本人操作；时间菜单保持群管理者
  或私聊本人可用。目录声明匹配实际 rule，不改变存储、推送或功能授权。
- 配置文本 matcher 的 help IDs 仅来自已启用的配置文本动作，不能因为新 direct
  菜单而登记虚假的配置文本入口。两个管理 matcher 自己登记自己的 help ID。
- 现有 PushUnsubscribeConfig 没有 enabled 字段，本项不复活已删除配置或兼容分支。

## Acceptance

- 默认/自定义订阅与恢复口令在实际 rule 和目录中一致，私聊不被 AI 接管。
- 私聊时间入口可认领；群普通成员不可管理时间，群主/管理员/超级管理员可以。
- 数字、普通时间值和无关聊天不被全局目录认领；PromptFlow 原有回复仍可工作。
- 空配置和有配置文本两种安装都通过 catalog/matcher 全量登记校验，菜单不豁免。
- 既有退订持久化、定时发送、菜单身份隔离与权限测试通过。
- Ruff、公开代码/测试类型检查、公开回归、私有回归、编译与 diff 检查。

## Evidence

- 原始菜单入口专项：22 failed / 1 passed；失败覆盖实际 rule 已接受而目录不认领、
  私聊时间权限漏声明、以及安装登记仍是 exempt。
- 修复后订阅/发送/目录与安装专项 66 passed。真实 plugin_contribution 安装覆盖空
  配置和启用文本动作；PromptFlow 验证数字/时间输入及不同群、用户、私聊、QQ 回复隔离。
- 公开全量 `uv run pytest -q --basetemp=.test-tmp/push-menu-full`：2286 passed，
  151 条既有依赖告警（新增安装测试增加相同告警次数），104.22 秒。
- 私有仓库明确指定当前 V5 为 IRONSBOT_PUBLIC_ROOT：26 passed。
- `uv run basedpyright ironsbot tests`：0 errors / warnings / notes，退出码 0；
  Ruff、compileall、git diff --check 通过。
- 生产代码净增 9 行，不新增运行模块、依赖、TOML 字段或数据库变更；未操作生产。
- 总进度保持 4/8。其余命令覆盖、玩家多榜回归、数据发布和真实平台验收仍未完成。
