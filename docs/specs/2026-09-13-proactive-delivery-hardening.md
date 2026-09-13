# 主动推送通用加固

Status: `implemented`

Contract: `target`

Owner: `services.messaging.proactive_delivery`

## Goal

所有主动推送使用同一套有限并发、失败分类和重试策略。业务 service 不读取 QQ 号，
也不识别任何平台错误码。

## Contract

- `SendResult.failure_kind` 统一表示永久失败、可重试失败、结果不确定和传输不可用。
- 只有明确标记为可重试的失败才重发。
- 结果不确定时记录到 summary，但不重发，避免重复消息。
- 同一轮最多并发 `max_parallel_targets` 个目标；后续重试按
  `retry_batch_divisor` 缩小批次。
- 一轮中出现明确传输不可用后，不再提交尚未开始的目标。
- 订阅过滤、推广内容和每日退订提示仍只应用一次业务规则。

## Platform Boundary

OneBot 适配器负责把断线、超时和普通失败转换为通用 `DeliveryFailureKind`。目标平台
适配器以后实现同一结果契约即可复用 service，不需要复制队列算法。涉及 QQ 号、机器人
账号路由及官方平台主动消息资格的部分继续延期到最终平台验收。

## Configuration

`[messaging.proactive_delivery]` 提供总尝试次数、最大并发、重试批次除数和重试等待。
全部字段有默认值；现有 TOML 不必新增该表。

## Verification

- 覆盖订阅过滤、有限并发、可重试恢复、不确定结果防重发、断线停止及目标平台能力。
- Ruff、BasedPyright、compileall、专项 pytest 与全量 pytest。
