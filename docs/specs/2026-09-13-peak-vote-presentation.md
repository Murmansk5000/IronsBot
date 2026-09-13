# 巅峰投票展示增强

Status: `completed`

Contract: `target`

Owner: `services.seer.peak`、纯 render presenter 与 Seer 数据 render adapter

## Goal

同步主线巅峰投票的有效展示信息，同时保持 V5 的数据、展示和资源边界。用户看到
限制级/准限制级、精确投票周期、总票数、各精灵票数与整数占比。

## Contract

- 巅峰 service 只构造投票级别、周期和脱离数据库 Session 的快照。
- 纯 presenter 将负票按零计入统计；总票数为零时所有占比均为零。
- 占比仅是展示数据，不反向改变原始票数。
- render adapter 继续复用按需图片源和最终图片缓存。
- HTML renderer 只消费不可变 document，不读取数据库或新增静态资源。

## Verification

- 巅峰查询和投票展示专项：64 passed。
- Ruff：通过。
- Windows 默认 pytest 临时目录存在宿主权限残留；改用工作树内独立临时目录后
  测试正常完成，证明该异常不来自产品代码。
