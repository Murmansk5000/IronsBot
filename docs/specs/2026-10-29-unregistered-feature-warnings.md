# 未注册功能权限项告警并忽略

Status: `verified`

Contract: `baseline`

Owner: `ironsbot.config.models.features`

Related architecture: [配置契约](../../ARCHITECTURE.md)

## Problem And Goal

未知 TOML 字段已经告警并忽略，但普通功能组合中的未注册权限仍会阻止启动。
将未注册权限引用改为按位置告警、失败关闭，保留其他有效权限和原有安全校验。

## Ownership And Design

- 复用公共功能组合解析及策略编译；设置加载、配置检查和应用组装采用相同规则。
- 普通组合和群／用户策略忽略未注册项；嵌套组合可以解析为空，但不能回退成其他授权。
- 编译后的权限事实不能保留未注册原子项。告警仅包含配置位置，不包含无效项的值。
- 不修改磁盘 TOML，不推测旧权限的新名字，不自动迁移旧消息或启用替代功能。
- `all` 显式声明自定义原子功能的既有契约不变；消息动作声明的功能仍有效。
- 回填历史时遵循各节点当时的注册表，不提前停用当时仍合法的功能；本记录的验证日期为 2026-10-29。
- 循环、显式空组合、名称冲突、禁止的管理通知组合、错误类型及身份引用仍严格拒绝。
- 不新增配置、公开类型、数据库或平台分支，不变更生产环境和保留工作文件。

## Acceptance Tests

- [x] 复现含 `web_activity_link` 的 standard 组合，加载和配置 CLI 成功并告警。
- [x] 有效项、消息自定义功能及显式声明的扩展功能继续生效。
- [x] 未注册群／用户授权不进入 FeatureService；全无效及嵌套空结果不扩大权限。
- [x] 黑名单、超管绕过和显式管理通知规则保持原行为。
- [x] 告警不包含无效值；安全校验仍报错。
- [x] 定向测试、质量检查；全量测试显式排除用户保留的测试文件。

## Migration And Delivery

无配置或数据库迁移；按用户授权将原混合提交拆分并合入配置提交，仅本地提交，不推送或部署。

## Evidence

| Date | Verification actually run | Result / remaining risk |
| --- | --- | --- |
| 2026-10-29 | 配置加载、功能服务、CLI、运行策略定向测试 | 155 passed |
| 2026-10-29 | Ruff；四个变更 Python 文件 BasedPyright；compileall；diff 检查 | 通过；Ruff 和 compileall 显式排除两个保留文件 |
| 2026-10-29 | `pytest -q --ignore=tests/test_mintmark_series_ordinal_resolver.py` | 6661 passed、9 skipped，耗时 435.32 秒；预留测试未执行 |

本次修复与未知 TOML 字段处理归入同一独立配置提交；生产仍使用已修正的 TOML，
新容错规则须发布后才生效。
本次不以本地测试通过代替生产验收。
