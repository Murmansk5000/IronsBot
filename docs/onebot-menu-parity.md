# 双平台菜单与入口核对

本轮将菜单返回和独立会话放入公共服务。OneBot 的 TD、推送时间及维护操作不再创建临时 Prompt；两端仍分别负责事件解析、平台发送和回执。

## 菜单规则

- 子菜单 `0` 返回一层，顶层 `0` 退出；无上级的确认流程取消后结束。
- 返回恢复选项快照，不重新查询或扣额。同层刷新替换当前层，不增加导航深度。
- TD 返回时重新读取订阅和当前管理权限；新增内容返回时校验数据快照与分类权限，不显示已失效批次。
- 新菜单及返回后的菜单使用新会话 ID，以实际发送回执登记引用锚点。旧按钮、旧层引用、结果图片不作为当前菜单入口。
- 返回、退出、替换任务会使旧查询代次失效，已排队输入及迟到结果不能重新安装旧菜单。
- 引用他人菜单仍检查实际操作者的权限、冷却和额度；接入后保留自己的选项快照。原发起人退出不关闭副本。
- 帮助、TD、推送时间的打开动作不留下已完成查询的重复占用；实际查询和维护操作仍沿用原规则。

公共实现：`services/portable_menu_navigation.py`、`portable_query_sessions.py`、`portable_interactions.py`。新增子菜单使用 `PortableMenuSpec(child=True)`，同层刷新保持默认；只有具有真实导航意义的详情才使用 `offer_view()`。需要刷新状态的上级提供 `refresh_on_return`，不得在该回调中重做付费查询或业务修改。

## 已统一

| 功能 | OneBot 实际入口 | 公共实现与官方端对应 |
| --- | --- | --- |
| 帮助 | `plugins/onebot/help/__init__.py:install` | `services/help_menu.py`；详情有返回层 |
| TD、推送时间 | `plugins/onebot/messaging/matchers.py:install` | `portable_messaging_commands.py`；本轮替换旧入口 |
| 普通资料、头像、立绘、装备、刻印、属性 | `seer/query/commands/*_queries.py:install` | `portable_seer_commands.build_portable_catalog_queries` 统一搜索、候选标签、选择回调与会话；删除独立 `query_conversation` |
| 玩家详情、快捷详情 | `seer/query/commands/player.py`、`player_shortcuts.py` | `portable_player_commands.py`；玩家选择进入详情可返回 |
| 榜单列表、范围、分数查询 | `seer/query/commands/rank_list.py:install` | `portable_rank_commands.py`；进入玩家详情保留榜单父层 |
| 群星牌、圣域 | `seer/query/commands/autocard.py`、`autocard_sanctuary.py` | `portable_autocard_commands.py`；本轮移除未注册旧会话代码 |
| 新增内容 | `seer/query/commands/new_content.py:install` | `portable_new_content_commands.py`；本轮移除未注册旧 Prompt 及测试，替换为公共服务验证 |
| B站历史、刷新、账号、推送模式 | `plugins/onebot/bilibili/commands.py:install` | `portable_bilibili_commands.py`；统一命令契约、执行前权限和失败状态，移除独立账号与刷新处理器 |
| 战队资料、订阅战队详情 | `seer/query/commands/team.py`、`plugins/onebot/team_resource.py` 的查询注册 | `seer/team_commands.py`、`portable_team_resource_commands.py` |
| 橱窗及皮肤详情 | `plugins/onebot/lucky_skin_window.py:_install` | `portable_lucky_skin_commands.py`、`portable_lucky_skin_result.py` |
| 数据同步确认、镜像维护确认 | `plugins/onebot/operations/db_sync.py`、`docker_update.py` | `portable_operational_commands.py`；本轮迁移；仍限制超管，重启在回复发送成功后执行 |
| 身份关联、状态、撤销 | `seer/query/commands/player.py` | `identity_link_commands.py`；保留关联开始与确认的平台约束 |
| 榜单帮助 | `plugins/onebot/rank_help` | `portable_seer_commands.build_portable_rank_help_operation` |
| 精灵配置 | `plugins/onebot/pet_config` | `portable_pet_config_commands.py`；复用应用会话，不另建独立菜单存储 |
| AI 意图、聊天、单独提及提示 | `plugins/onebot/ai` | `ai/chat_operation.py`、`ai/fallback_operations.py`；平台只提供事件及来源信息 |
| 配置提及回复、主题管理 | `plugins/onebot/messaging/matchers.py` | 公共 messaging 操作与公共投递；不在 handler 中直接拼装平台消息 |
| 启动通知 | `plugins/onebot/startup_notice/__init__.py` | `operations/startup_delivery.py`；适配器只负责生命周期钩子 |

B站正文、图片、战队普通详情等不额外建立虚假的返回页面；有可继续选择的菜单保持原会话。

## 公共业务与适配器边界

刻印数值榜、活动、固定／图库图片、会议、数据版本、预告及赛季倒计时均已由 OneBot 适配器调用公共操作。榜单管理同样共用公共操作，超过 3 秒提示一次，快速结果不提示，提示发送失败仍继续执行。

开服和关于已接入 `portable_operational_commands` 公共操作，OneBot 独立开服处理器已删除。OneBot 通过 `make_authorized_portable_handler` 在执行前使用同一 CommandContract 复核功能、超管、会话范围与黑名单；无头实例状态仅允许超管私聊。无前缀“开服查询”只返回用法提示，不触发重连；关于与开服不增加慢提示。管理员重连失败保留公告及失败原因，并显式标记业务失败。

这里保留的适配器负责事件转换和发送，不是另一套查询实现；主动推送同样不重复注册业务调度。

主动推送由应用生命周期注册公共业务服务和共享投递路由，不因本轮菜单迁移新增调度或收件人。

## 必要平台差异

- OneBot 事件、自发消息识别、身份辅助核对、昵称及群名补查、群角色 API。
- QQ 官方 AppID 作用域身份、消息时效、富媒体上传、Markdown／按钮及回执格式。
- 戳一戳、红包等平台特有事件，不在官方端伪造接口。
- OneBot matcher 负责注册事件，权限使用公共 CommandContract；不再用 NoneBot 原生 SUPERUSER 另建超管判定。菜单执行再次检查实际操作者。

## 五项差异的统一结果

| 项目 | 公共行为 | 实际入口与保留边界 |
| --- | --- | --- |
| 配置文本附带的 @ | 显式成员优先，否则使用配置对象，无目标交由回复层回复发送者；去重，不附加发送者 | OneBot `handle_message_command` 调用 `build_portable_text_operation`；官方配置目标须解析为同账号的可信成员 |
| 战队订阅确认 | 公共确认菜单归发起人及当前机器人，确认时检查管理权限及待办快照，`0` 取消 | 普通战队、订阅详情、玩家详情扩展均接入 `subscription_confirmation`；旧按群捕获是／否的 matcher 已移除 |
| 巅峰查询进度 | 池子、投票和统计榜超过 3 秒提示一次，已有等待提示则不再发送；提示失败继续交付结果 | 两端使用公共巅峰操作；发送仍经过平台消息限流 |
| 个人榜单目标 | 两端由公共操作解析目标，允许多候选；按最终玩家及榜单做重复判定 | OneBot 规则仅确认格式和可见目标，不提前执行单目标解析；候选展示不查询淘米 |
| AI 执行 | 两端共用聊天执行，保留各自事件来源信息及共同的意图路由 | 删除“处理中...”及 ai.waiting_notice；旧 TOML 字段记录完整路径警告后忽略，不再生效 |
| 战队订阅管理 | 新增、取消、列表调用同一操作，执行前重新检查目标授权与管理角色 | 查询后的确认仍归当前机器人、群和发起人 |
| 旧 Prompt 公共基础设施 | 删除临时 matcher、旧队列、状态管理、应用注入及兼容 API | 请求令牌独立保存在 request_state；公共菜单独立负责取消、FIFO 和迟到结果 |

私有 `details` 已基于当前私有 main 源码整合公共扩展基础，删除旧 OneBot matcher、PrivateExtensionRuntime、load_peak_pools 和裸 QQ 参数调用。普通阵容与详细阵容都由公共扩展操作执行，保留特性、技能、刻印及详细图片；没有修改私有 main，没有合并或重写分支历史。

详细阵容仅允许超管发送“阵容详情<数字米米号>”，不进入普通玩家菜单、不触发绑定建议。动作的访问范围、菜单可见性、目标语法与绑定建议通过公共注册契约声明；入口与执行前按实际操作者复核。内置及私有动作共用 core/player_detail_actions.py 中同一请求类型，公开契约不再重复定义请求。详细包使用公共连接、排队和额度服务，解析及渲染成功后幂等结算；失败或元数据不完整不结算，不补零。

私有 experiments 仅保留历史参考，不参与运行注册、测试收集或发布；tools 保留原有未跟踪内容。测试基于本地公共工作区，发布前仍需在公共提交完成后更新 private 的 public-runtime.json 并重新验证配对，不能把旧 SHA 视为新契约的发布依据。

共享命名与位置已清理：QQ 配置引用使用 config/qq_references.py；橱窗 TD 使用 services/seer/lucky_skin_window_subscriptions.py；目标配置编译移出平台适配器；战队审核功能策略使用公共 FeatureTeamAuditPolicy。数字 QQ 的逻辑身份仍沿用现有存储表达，不迁移身份或数据库。

快捷玩家入口现在只保存未解析引用；数字、别名、成员与默认绑定目标均在公共操作中解析及授权，之后按最终玩家产生语义请求，避免入口和操作重复解析、重复认领。

升级前须从生产 TOML 移除 ai.waiting_notice。没有替代字段；不改变其他查询的慢提示设置。

## 测试证据

- `tests/test_menu_event_ingress.py`：OneBot `handle_event()` 实际 TD 注册，官方 SDK 事件转换、公共投递回执；修改、返回、继续管理、退出、立即重开；三种引用结构和双机器人隔离。
- `tests/test_portable_menu_navigation.py`：多层快照、同层刷新、权限失效、发送失败、文本／按钮返回及迟到结果。
- `tests/test_portable_interaction_lifecycle.py`：FIFO、实际操作者额度与冷却、拒绝不替换已有会话、迟到回调。
- `tests/test_portable_new_content_commands.py`、`test_portable_autocard_commands.py`、`test_portable_player_commands.py`：分类、候选、独立引用与权限重查。
- `tests/test_plugin_import_hygiene.py`：内置业务插件禁止再次导入旧 Prompt 入口；安装过程不得读取网络或创建运行存储。
- 同文件的架构边界检查禁止内置指令插件自行定义查询菜单、直接调用查询服务或直接发送业务结果；戳一戳和红包协议事件明确豁免。
- 私有 tests/test_detail_ingress.py 验证真实 OneBot handle_event 与官方事件解析接入同一详细阵容动作；test_detail_service.py 验证请求归属、协议身份核验与失败不结算；主项目 test_extension_action_access.py 验证菜单隐藏和权限撤销，test_player_lineup_detail_ports.py 验证公共包请求、结算幂等及脱离 ORM 的资料快照。
- `tests/test_portable_behavior_parity.py`：两端目标优先级、官方身份缺失、确认操作者及账号隔离、取消／权限／超时、慢提示失败后的结果交付。
- `tests/test_menu_event_ingress.py` 新增实际 OneBot 文本、榜单候选和战队查询确认入口测试；`tests/test_portable_rank_commands.py` 验证别名选择与数字查询共享最终目标判重。
- `tests/test_remaining_operation_parity.py`：AI 最终回复、旧配置拒绝、两端订阅操作权限复查、错误回复释放重复占用、榜单慢提示失败仍发送结果。
- `tests/test_menu_event_ingress.py` 的开服／关于真实入口矩阵及 `test_qq_official_mvp.py`：普通用户、超管、禁用功能、黑名单、群聊与私聊范围、无前缀提示；`test_server_status_service.py` 和 `test_portable_operational_commands.py`：重连失败状态传递及公告保留。
- 删除仅测试旧 Prompt 接口的用例；其引用隔离、取消、提前输入和 FIFO 行为由公共菜单、真实事件入口及交互生命周期测试覆盖。

验收须针对最终工作区重新运行，先前阶段的测试数量不作为本轮结果。数据版本缺失、预告素材全部失败、刻印发布数据缺失、新增活动缺少基线及 B站刷新／详情失败均显式标记业务失败，发送错误提示不等于查询成功。

2026-10-21 最终工作区验证：公共仓库完整 pytest 5018 通过、7 项环境性跳过；私有 details 72 项全部通过（已启用原生 htmlkit 渲染验收，并查看完整 12 格详细阵容图片）。两仓库 Ruff、BasedPyright、compileall、git diff --check 通过。此结果包含工作区并行整合的改动，验证的是本地源码组合，不代表生产环境已更新或旧发布 SHA 已兼容新契约。

本轮不提交个人配置，不修改生产环境，不自动提交、推送或部署。
