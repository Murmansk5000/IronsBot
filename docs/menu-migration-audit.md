# 双平台菜单迁移核对

参考归档：`origin/legacy/napcat-main-2026-09-16`。本文记录本次改动的覆盖范围，
不代表全仓库所有历史功能均已逐项验证。

## 入口对应

| 归档入口/行为 | 当前入口 | 状态 |
| --- | --- | --- |
| `runtime/conversations.py` 的预备输入 | `services/portable_interactions.py`、`portable_session_state.py` | 查询前预约，发送回执后释放 FIFO |
| `runtime/prompts.py` 的引用菜单和语义请求 | `services/portable_query_sessions.py` | 引用者复制选项快照，独立会话、操作者、超时与请求令牌 |
| `plugins/help` 的共享帮助 | `services/help_menu.py` | 按回复者权限筛选帮助，不继承原菜单权限 |
| `plugins/seer/query/query_conversation.py` 通用多选 | 当前同名 OneBot 模块 + 公共 QueryOperationSpec | 不注册临时选择 matcher，提前接收数字，包括 7 |
| 玩家详情、群星牌、场地、动态历史 | `services/portable_*_commands.py` | 公共只读菜单，共用两种平台入口 |
| 新增内容的自定义图片菜单 | `portable_new_content_commands.py` | 图片编号与快照共用，支持字母及 a1/b3，不把结果图登记为菜单 |
| 战队列表、橱窗四皮肤详情 | `portable_team_resource_commands.py`、`portable_lucky_skin_result.py` | 只读共享；每日橱窗也使用相同图片与菜单 |
| 旧 Prompt 和排队路由 | `integrations/onebot/{prompts,prompt_sessions,queued_conversation_router}.py` | 保留兼容；会话键增加机器人账号，统一解析引用 |
| TD、维护、绑定、登录等确认 | 原专用处理器或非共享 PortableMenuSpec | 特意不开放跨成员复制；权限和确认不能借用 |
| 自回复防护、自定义 @ 回复、OneBot 戳一戳 | 原入口 | 保留防循环规则，不借本次迁移扩大自动回复权限 |

旧 `bilibili/dynamic_actions.py` 和新增内容模块中的 Prompt 辅助函数仍保留兼容测试，
但对应生产命令已经只注册公共菜单处理器，不构成第二个输入入口。

## 会话与权限边界

- 交互按平台、机器人账号、会话和操作者隔离，业务身份共享不等于菜单共享。
- 只有菜单发送成功的真实回执 ID 才能成为引用锚点；官方端同时保存平台提供的引用索引。
  无法解析的官方引用保留“这是引用”的事实，不降格为裸数字。
- 引用有效只读菜单后，选项快照和编号复制给回复者；绑定等修改项不在副本中。
  未授权、非法选项、冷却拒绝不替换回复者的菜单。
- 请求去重、冷却、业务查询额度与语义跟踪使用实际操作者。免费帮助不新增查询计费；
  通用查询搜索出菜单时释放初始请求占位，实际选择仅计一次。
- `0` 只清理发送者在当前机器人和会话下的状态。退出、替换、失败会使迟到任务失效；
  不取消其他参与者的副本。子菜单只更新自己的锚点。
- 群功能看群策略，私聊功能看用户策略。超管主动操作遵循 `superuser_bypass`，
  黑名单及平台能力不绕过。旧官方账号权限字段接受但告警、忽略。
- `admin_notice` 必须显式授予；`all`、超管和 bypass 不创建通知或业务推送订阅。
  仍使用原 TD 退订规则，不新增超管收件人配置。

## 官方身份与橱窗

`official_user_addresses` 按 AppID + OpenID 唯一保存地址，独立记录群成员与私聊来源。
只有已观察或明确配置的私聊地址，且已有可信用户关联，才进入公共私聊路由。
同样的字符串在不同 AppID 下不自动关联，不通过昵称或历史日志自动绑定。

`PrivateConversationRoutes` 由 B站、通知及每日橱窗共用。多个可用地址没有默认路由时
不猜测账号。平台允许的既有机器人回退规则不扩大。

橱窗发送账本按逻辑用户和日期原子领取，与数据缓存独立：成功回执才完成；
明确失败可在下一次调度重新领取，发送结果不确定或崩溃遗留领取不自动重发。
路由不可用、TD 退订不记成功。本次不扫描或补发历史橱窗。

生产只读核对发现的案例：当天调度、玩家绑定及缓存均正常，无 TD 退订；
发送前因 OneBot 私聊目标不支持而跳过。另有官方 C2C 被旧账号路由过滤的记录。
它们不能证明所有漏推送或 AI 问题都来自同一原因。

## 验证与剩余证据

- `test_menu_event_ingress.py` 经过真实 NoneBot `handle_event()`，覆盖三种引用结构、
  双机器人、独立退出、拒绝保留原菜单和生成期 FIFO。
- `test_official_menu_ingress.py` 经过 EventParser、路由、官方发送器和回执登记，
  验证引用索引、后续裸输入、旧引用拒绝。
- `test_portable_interaction_lifecycle.py` 检查操作者计费、冷却、发送失败、
  进度期间排队和迟到结果失效。
- `test_daily_delivery_receipts.py`、`test_official_addresses.py` 检查并发领取、
  重启持久化、未知结果、可信 C2C、来源去重、解绑和 AppID 隔离。
- 现有业务测试继续覆盖玩家、帮助、群星牌、新增内容、橱窗、TD 和维护确认。

仍需生产证据：特定官方群聊 AI 未响应的原始消息/时间/账号；各官方账号真实
引用事件的字段形态及其发送回执；私聊地址缺失的用户需要实际 C2C 事件或明确配置。
测试不会冒充腾讯真实发送成功，日志与数据库检查均未修改生产状态。

## 配置交付

完整 `config.example.toml` 保留；群和用户使用内联表。个人精简配置只生成到
Git 忽略的 `config/`，不覆盖生产配置。逐项比较保留值和身份顺序，
仅删除废弃的账号权限/通知名单；保留现行 AI providers、原 superusers、
owner 的显式 admin_notice，不自动为其他超管增加 all。
