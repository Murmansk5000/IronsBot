# 原版修复回归审计

Status: `verified`

Scope: `legacy/napcat-main-2026-09-16` 与当前公开 `main`

## 审计方法

- 以架构分叉前提交 `14a105e9` 为起点，检查原版至 `55a39fd1` 的功能与修复提交。
- 对比最终文件，而不是用提交是否可达代替行为比较；历史合并后，旧提交可达不代表
  重构后的最终实现仍包含该行为。
- 优先核对 renderer/template、玩家详情、菜单会话、榜单、B站和主动投递。
- 架构位置不同不算回归；只有用户可见数据、交互或失败语义丢失才需要迁回。

## 已确认并修复

| 模块 | 原版最终行为 | 重构回归 | 当前处理 |
| --- | --- | --- | --- |
| 幸运橱窗卡片 | 220px 立绘区、紧凑名称区、关注星位于立绘、风尚券和钻石图标、原版价格文案 | 重构后的模板改成 270px 立绘区并简化价格模型；后续只补回货币图标，没有恢复最终布局 | `25ec900f` 恢复最终展示契约；保留纯 presenter 和 integration 素材边界；最终缓存升至 `lucky_skin_window_v3` |
| 新增内容根图 | 竞技池变化使用 4x4 矩阵；专家池显示进出池；大师池显示竞技点变化；精灵头像直接出现在根图 | `c9df414f` 拆 renderer 后丢失 `pool_preview`，后续同步提交未迁回，分类只剩标题 | `b13e42ac` 增加纯 `PoolChangePreview` 文档与批量素材装配，恢复三类池变化；缺图时不缓存残缺结果 |
| 固定口令与会议目标成员 | “口令 @成员”只把结果发给明确目标；没有目标时回复发送者；关键词自动回复不能借成员 @触发 | 重构后的 OneBot matcher 退回 `explicit_command`，便携执行器丢弃 `member_mentions`，会议回复也只指向发送者 | 统一使用 `MessageInputContext.member_mentions` 和 `MentionPart`；OneBot 只在精确口令启用成员目标，QQ Official 保留明确目标而不额外 @发送者 |

前两项的共同原因不是旧代码未进入 Git 历史，而是重构时用较早或较小的 view model
替换了原实现，后续只验证了“能渲染图片”，没有锁定最终图片中的字段和布局。第三项
则是平台中立命令迁移时只迁移了回复正文，没有同时迁移输入中的目标成员语义。

## 已核对且保留

| 修复簇 | 当前权威实现与证据 | 结论 |
| --- | --- | --- |
| 巅峰池有效期、历史位置、变化箭头和大师池 | `services/seer/peak.py`、纯 `rendering/peak_pool.py`、`integrations/seer_data/peak_pool_renderer.py`；池查询及渲染专项测试 | 行为已迁移；当前使用观测时间并按发布事实显示有效期，是比旧生成时间更准确的实现 |
| 玩家巅峰分项与榜单未确认状态 | `player_peak_formatting.py`、统一 rank summary/cache；玩家格式和榜单专项测试 | 已迁移；未把个人分数是否存在错误绑定到榜单名次是否命中 |
| 魂印词条、专属效果与伙伴强化 | `integrations/seer_data/pet_display_data.py` 与不可变 pet render snapshot；special-effects 测试 | 已迁移到发布事实读取，不恢复旧 renderer 内的运行时猜测 |
| B站正文补全、图片、摘要和不确定投递 | `services/bilibili/hydration.py`、`content.py`、`outbound_delivery.py`；hydration/dedup/delivery 测试 | 原版相关修复已由平台无关投递路径吸收；不确定发送不会盲目重试 |
| 菜单抢占、快速回复、引用和旧会话关闭 | 通用 `PortableQuerySessionStore` 与 OneBot/QQ Official adapter；portable session 与 OneBot 集成测试 | 已迁移；不恢复旧 matcher 状态字典和专用 fallback |
| 推送订阅、并发与失败分类 | `ProactiveMessageDelivery`、统一订阅状态和平台送达结果；proactive delivery 测试 | 已迁移；平台适配器不再各自实现重试 |

上述跨模块专项回归在 2026-09-20 运行，结果为 `215 passed`。幸运橱窗专项为
`38 passed`；新增内容专项为 `78 passed`；成员目标与平台回复专项为 `179 passed`。
依赖库仍产生既有 NoneBot ForwardRef 和 SQLAlchemy relationship 警告，本次没有新增
业务警告。

最终公开仓库全量回归为 `3852 passed, 7 skipped`；Ruff lint/format、生产与测试
BasedPyright、compileall、`scripts/check_repo.py --static` 和 diff check 全部通过。

## 有意差异

- 巅峰投票模板与原版 `51cb0808` 不是字节级一致。当前仍保留池标题、周期、总票数、
  排名、精灵图、属性、限制级标记和百分比；差异主要是背景渐变、阴影和布局 CSS，
  没有发现数据字段或排序丢失，因此不回滚当前模板。
- 多个 renderer 的 footer 只有在能解析当前仓库地址时才显示项目链接；这避免把旧 fork
  地址写进图片，属于修复，不恢复无条件旧链接。
- 固定图片和部署者私有内容继续由配置与挂载资源提供，不重新打包旧环境的私有素材。
- 戳一戳、群成员管理等平台原生能力不强行伪装成 QQ Official 能力；这属于平台能力差异，
  不是共享业务迁移缺失。
- `messaging.commands[].at_user_ids` 仍是显式的 OneBot 引用列表，带该字段的动作不会注册到
  QQ Official。数字 QQ 号不能被猜成 OpenID；若将来要跨平台静态收件人，应另行迁移为
  平台身份别名，而不是静默忽略目标或自动映射。

## 仍需继续验收

- `docs/specs/2026-09-15-command-parity.md` 中配置型文本/图片仍需按实际生产配置逐项核对。
- 玩家二级菜单、榜单全部参数组合和私有扩展仍以真实客户端矩阵为最终证据。
- Phase 7 尚缺普通群管理异常不泄漏、真实 AI 备用 provider failover，以及官方平台主动
  消息拒绝/额度/receive-reject 证据；本审计不把这些外部门槛标成通过。

## 防回归规则

- renderer 迁移必须为关键展示字段和布局约束增加测试，不能只断言返回 PNG 字节。
- 原版后续修复同步时同时检查 service、presenter、template、缓存版本和用户文案。
- 视觉样式可以改进，但删除字段、预览或交互入口必须在 Spec 中明确记录，不能以
  “架构重构”作为行为变化理由。
