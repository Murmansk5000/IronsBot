# 双平台菜单与入口核对

消息正文由无 NoneBot 依赖的 `decode_onebot_segments` 唯一解码：CQ 字符串只在分段时解码转义一次，数组文字不反转义、不按 CQ 重解析，嵌套自定义数据保留；规范允许的非文字空参数对象转为空字典。坏消息段和非字符串 post_type 在协议边界拒绝，固定日志不输出消息内容。命令、观察和自身回声共用消息段文字提取，不调用原生 get_plaintext 或异常兜底。接收/发送消息与通知均使用框架无关的协议校验；保留扩展字段，整数拒绝布尔值，不输出坏字段内容。其他控制事件、宿主和插件依赖仍未全部去框架化。

临时私聊即使带来源 group_id 或 sender.role，仍以 message_type=private 构造会话和交接帧，不取得来源群权限或群角色，不切成群回复。实际反向 WebSocket 的 CQ/数组回放覆盖私聊权限、同连接私聊发送及回执结算；来源群已开放功能但私聊未开放时，不执行业务或 AI。

正向/反向 WebSocket 与 HTTP 接收的引用、机器人提及、昵称和连续文字段预处理共用无框架依赖的 message_preparation。普通接收与 message_sent 经 OneBotReceivedMessages 直接进入同一公共准入，不构造原生消息、不经过 matcher，不调用 SDK Bot.handle_event，不伪造交接帧或尝试原生解析 fallback；notice 也直达既有服务。42 组群/私聊样例对照已安装 SDK 的真实预处理，保留空消息、重复入口提及、引用失败保留正文及昵称前缀语义。引用元数据最多查询一次，失败只记录错误类型，取消继续传播。原始消息保留给身份观察；引用正文中的提及不进入命令目标。三种接收入口均有禁止原生转换/派发的实际公共业务与回执测试。

接收/发送 DTO 共用来源字段校验，发送观察允许缺少 font/sub_type/sender/raw_message，缺省不合成身份或群角色；接收 DTO 仍要求原有必填元数据。自身发送沿用正式 OwnAccountCommandPolicy 的开关、前缀、路由例外和回声抑制；普通 message 不能冒充 message_sent。其他账号的群发送只观察，不查询引用、不进入业务、AI 或红包处理；私聊发送事件保持忽略。反向桥已删除原生消息预处理与回填代码，自身完整/最小报文也在禁止原生转换/派发的真实 CQ/数组矩阵中执行。

组合根在 router 确定后注册接收适配器，显式注入同一 admission/router/messenger，无全局业务服务或未绑定时的旧路径兜底。普通群、私聊和临时私聊的 CQ/数组真实接收矩阵禁止原生转换、SDK 预处理及原生派发，并按对象身份断言同一公共上下文只构造一次。静默、黑名单和路由拒绝仍先完成后台身份观察；@全体不进入业务。红包仅在贡献已安装且消息处理允许时启用；与命令的先后仍采用原有优先级，没有更改配置或主动扩大通知范围。

红包消息及灰条通知的识别、摘要和可选群名查询现由 integrations.onebot.red_packet 处理，只依赖规范消息段与连接端口；旧插件函数删除，不保留转发导出。CQ 摘要编码与原生显示逐例对照，保留标题、文字优先及 80 字截断。管理收件人、TD、并发冷却仍由既有 RedPacketNoticeService/AdminNoticeService 处理；可选群名响应缺失或形状错误不阻断通知，取消继续传播，不打印错误正文。

实际注册审查仍有 command_ingress、红包被动消息及戳一戳/审核入群/红包 notice 的原生声明，但三种传输的消息和通知都已绕过这些 matcher。声明及原生测试入口尚待宿主/插件清理，不作为第二套业务权威。player_shortcuts/group 没有生产注册消费者，私有 details 的并发测试仍引用，未擅自删除。私有 main/details 的阵容和倒计时贡献未安装额外消息 matcher。

三种传输的 notice 由 OneBotNoticeIngress 直接校验来源并交给戳一戳、审核入群和红包服务，复用同一组 notice_events 动作。保留原有准入、安装条件及同优先级并发/后续优先级阻断，取消继续传播。异常只交给既有管理员报告器，不伪造消息 ID 或向普通群补发。原生测试入口与直达入口使用相同实际服务行为矩阵；红包两种来源仍复用群冷却，并非精确事件判重。

HTTP 上报由 OneBotHttpReceiver 校验账号、原始正文 HMAC-SHA1 签名和来源，TaskOwner 持有任务。保留三个 URL 与可选 onebot_secret：缺少/错误签名返回 401/403，畸形或来源不符返回 400，接受返回空 204，停止后拒收。群聊、私聊、临时私聊及自身发送的 CQ/数组矩阵验证权限范围、一次上下文投影、回执、并发重放和失败释放。HTTP 出站协议也已独立；ASGI 与 HTTP 客户端资源宿主仍待迁移。

HTTP 出站由 OneBotHttpApi 负责地址/正文、总超时和响应校验，宿主只翻译 HTTP 请求/响应及已知网络错误；不调用 SDK API 发送或解析函数。HTTP 与 WebSocket 共用唯一 onebot_api_result：只接受 ok/0、async/1，后者不产生最终回执；缺失或矛盾的状态、布尔/字符串 retcode、错误响应附带的 message_id 均不采信。缺地址和停止后明确未发送；提交后超时、坏 HTTP 响应或回执缺失保持不确定，不自动重发。地址按账号保存构建时快照，旧 socket 不回落 HTTP；本步不新增配置。

正向连接由 OneBotForwardClient 等待合法 lifecycle/connect 报文后登记账号；该控制帧不成为业务输入，仍执行原有连接钩子。正反向共用 OneBotSocketEvents 的解码、来源核验、RPC 回执及任务提交，不重复接收循环。保持三秒重连间隔，不自动重试业务；重复账号拒绝替换，断线关闭等待请求，旧 Bot 永远不能借用新连接或回落 HTTP。停止唤醒重连等待，握手或连接器迟到完成也不登记账号；取消释放连接与回执。多 URL 测试验证账号/会话/回执独立，同时保留同一用户跨机器人共用的既有指令冷却。独立无 NoneBot 进程验证正向接收、受管任务及关闭；不等于独立 ASGI 宿主已经完成。

正文协议依据：[CQ 字符串](https://github.com/botuniverse/onebot-11/blob/master/message/string.md)和[消息段数组](https://github.com/botuniverse/onebot-11/blob/master/message/array.md)。20 个样例与当前 SDK 的既有分段结果逐例对照；有效命令、转义字面量、提及、引用和畸形 CQ 的行为保留，不引入业务兼容路径。

命令、后台身份观察与自身指令现从同一份 OneBotMessageFacts 投影，原生入口不再重复读取消息段。普通群、私聊、自身发送及其他账号发送的来源分类仍明确区分：其他账号发送只产生观察，不成为自身口令。命令使用处理后的文本与去重后的直接目标，观察使用原始当前消息文本及数字提及；引用作者仅在没有显式数字提及时补充观察，绝不成为命令目标。删除无生产消费者的原生 own_account_input，不保留测试专用生产 API；测试改走真实投影。当前已有正式 CQ/数组正文解析，但仍未替换完整原始事件模型。

正反向 WebSocket 的 API 等待由 `OneBotWebSocketSession` 持有，每连接独立 echo 与等待表，不进入 SDK 全局回执等待表。并发回执可乱序；超时、取消、断线清理等待者；迟到和未知 echo 只消费、不派发业务。OneBotReverseServer 仍持有反向令牌核验、连接预占和关闭，收帧/回执由正反向公共实现执行。原生宿主只转换 socket、登记 Bot 并交接事件；没有 native_reverse 旧导出。交接前绑定原连接，立即断线不丢弃已接受事件；任务拒收关闭协程。反向 accept 中途停止不发布 Bot，取消或断线钩子失败也关闭 socket。其他控制事件、原生注册声明及 ASGI/插件/渲染/HTTP 资源宿主仍待收口，不宣称已完整移除 NoneBot。

协议依据：[OneBot v11 WebSocket](https://github.com/botuniverse/onebot-11/blob/master/communication/ws.md)、[反向连接](https://github.com/botuniverse/onebot-11/blob/master/communication/ws-reverse.md)及 [API 状态](https://github.com/botuniverse/onebot-11/blob/master/communication/http.md)（本轮核对）。`async/1` 只表示提交异步处理，不产生成功消息回执，即使响应错误附带 message_id 也不采信。未增加业务重试、权限或配置字段。

本轮将菜单返回和独立会话放入公共服务。OneBot 的 TD、推送时间及维护操作不再创建临时 Prompt；两端仍分别负责事件解析、平台发送和回执。

OneBot 出站路由、执行账号昵称及管理通知来源补充共用应用持有的连接目录，不再读取 NoneBot 全局连接表。连接登记先于业务连接回调，断线仅移除对应连接对象，重连后的迟到旧断线不清除新连接或重复触发断线业务。正常关闭在服务和任务结束后清空目录；昵称解析与缓存由出站回执和素材失败报告共享，按实际连接及 600 秒有效期隔离，迟到旧响应不能覆盖新连接昵称。没有连接仍跳过发送，不改群/私聊路由与备用账号策略。这不是 OneBot 接收服务已脱离 NoneBot 的声明。

公共生命周期与 TaskOwner 已不依赖 NoneBot 驱动、Bot 类型或日志器。资源及贡献启停、调度和任务排空直接执行；唯一原生宿主绑定在 integrations/nonebot_lifecycle.py，由应用显式创建并安装四类驱动钩子。该边界保留连接登记和迟到断线防护，不重做资源编排。禁止导入 NoneBot 的独立进程已验证完整资源启停；主应用的宿主、插件加载和 HTML 引擎仍未去框架化。

OneBot 正式出站序列化输出带类型的 JSON 消息段数组，发送端口只依赖账号身份和 call_api，不再构造或要求 NoneBot Message。文本、图片、成员提及及有符号回复 ID 的实际编码保持一致；回声事实由原生自身事件和正式出站共用一套段提取。旧 matcher 投递仍在自身边界转换成原生消息对象，不提供旧 API re-export。禁止导入 NoneBot 的独立进程已执行真实公共限流投递、回执验证和回声阻断；接收宿主尚未替换。

连接目录、路由、投递、历史回执核验、通知名称补充与审核群探测统一使用 OneBotConnection（self_id + call_api），不再把连接写成 NoneBot Bot 或要求原生便捷查询方法。历史查询保留执行账号隔离、超时、缺失与错误状态，不重发原消息；群探测使用框架无关的 OneBotActionError，网络失败不作为成员离群处理。原生 SDK 错误仅在协议适配器边界转换，接收宿主尚未替换。

OneBot 当前消息的解码规则已移到无 NoneBot 依赖的 message_facts 模块。原生适配器只提取 SDK 当前文本、原始当前消息段和元数据；唯一解码器处理寻址、直接成员提及去重、全体成员标识、回复优先级和公共上下文构建。引用正文及其中的 @ 不进入该快照；私聊的 to_me 标记仍不被当作群 @，私聊不携带群角色。准入通过后发布与事件对象绑定的不可变交接帧；命令入口验证平台、账号、操作者、会话和消息 ID，并复用同一上下文执行及回复，缺帧或错帧不重解码、不执行业务。普通及自身输入均只解码一次；自身指令由公共准入不可变地替换命令文本，不再修改原生事件或将 CQ 文本重新解析成消息段。接收宿主仍需迁移。

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

身份存储的成员/群映射、Union 证据、令牌及撤销读写统一使用受管工作线程；取消和正常关闭等待数据库操作结束后才释放写锁与资源。令牌关联、镜像观察与 Union 证据共用组合根注入的身份变更协调器，已接受的写入及 principal/地址发布完成后才返回取消；排队时取消不启动变更，后续变更不能越过前一发布。映射作用域、冲突规则、令牌和表结构不变。Union 回调只发布地址，不重复注册 principal。此保证不等于跨资源原子事务，不覆盖回调自身失败或进程崩溃后的自动修复。

调度器已从 NoneBot 插件移到应用资源：每个应用独立创建 APScheduler，公共生命周期在资源和服务注册完成后启动，关闭时先停止调度并等待运行中回调，再停止服务、排空自有任务和逆序关闭资源。同步回调与 SQLite 共用受管工作线程等待机制，异步回调等待取消清理；不保留旧绑定 API、调度插件或 NoneBot 自动启停配置。HTML 渲染和 OneBot 接收仍有框架依赖，此项不表示 NoneBot 已整体移除。

公共命令账本与身份观察账本均由应用显式持有事务任务，连接、SQL、提交及关闭使用同一受管 SQLite 事务入口；取消时等待已提交事务结束再释放认领锁，正常关闭先等待事务再关闭资源。两种账本用途和文件位置不变。已经提交的输入认领在调用取消后仍保留，不表示业务成功，也不承诺自动重放或 exactly-once。

黑名单由同一 FeatureService 决定，公共命令入口将已屏蔽输入视为静默终止，在消息账本、AI、菜单和业务执行前退出；身份准备后再次核验。OneBot 公共准入在任意 matcher 运行前使用同一策略，避免较高优先级红包/扩展处理器漏过。黑名单插件仅声明 Feature 归属，不再注册 matcher、规则或独立优先级。NapCat 身份观察仍先执行，notice 的既有策略不变，超管也不能绕过显式黑名单。

生产命令统一经过 `integrations/onebot/command_ingress.py`，下表旧入口仅用于追溯迁移，不表示仍注册运行。

| 功能 | 历史 OneBot 入口 | 公共实现与官方端对应 |
| --- | --- | --- |
| 帮助 | `plugins/onebot/help/__init__.py:install` | `services/help_menu.py`；详情有返回层 |
| TD、推送时间 | 旧 `messaging/matchers.py` 已删除 | `portable_messaging_commands.py`；公共路由统一命令认领、权限及菜单 |
| 普通资料、头像、立绘、装备、刻印、属性 | `seer/query/commands/*_queries.py:install` | `portable_seer_commands.build_portable_catalog_queries` 统一搜索、候选标签、选择回调与会话；删除独立 `query_conversation` |
| 玩家详情、快捷详情 | `seer/query/commands/player.py`、`player_shortcuts.py` | `portable_player_commands.py`；玩家选择进入详情可返回 |
| 榜单列表、范围、分数查询 | `seer/query/commands/rank_list.py:install` | `portable_rank_commands.py`；进入玩家详情保留榜单父层 |
| 群星牌、圣域 | `seer/query/commands/autocard.py`、`autocard_sanctuary.py` | `portable_autocard_commands.py`；本轮移除未注册旧会话代码 |
| 新增内容 | `seer/query/commands/new_content.py:install` | `portable_new_content_commands.py`；本轮移除未注册旧 Prompt 及测试，替换为公共服务验证 |
| B站历史、刷新、账号、推送模式 | `plugins/onebot/bilibili/commands.py:install` | `portable_bilibili_commands.py`；统一命令契约、执行前权限和失败状态，移除独立账号与刷新处理器 |
| 战队资料、订阅战队详情 | 旧 `seer/query/commands/team.py` 已删除，`team_resource.py` 的命令安装器已删除 | `seer/team_commands.py`、`portable_team_resource_commands.py`；贡献元数据与定时资源扫描保留 |
| 橱窗及皮肤详情 | `lucky_skin_window.py` 的旧命令安装器已删除 | `portable_lucky_skin_commands.py`、`portable_lucky_skin_result.py`；未知异常由公共管理告警处理，日常扫描与缓存行为保留 |
| 数据同步确认、镜像维护确认 | `plugins/onebot/operations/db_sync.py`、`docker_update.py` | `portable_operational_commands.py`；本轮迁移；仍限制超管，重启在回复发送成功后执行 |
| 身份关联、状态、撤销 | `seer/query/commands/player.py` | `identity_link_commands.py`；保留关联开始与确认的平台约束 |
| 榜单帮助 | `plugins/onebot/rank_help` | `portable_seer_commands.build_portable_rank_help_operation` |
| 精灵配置 | `plugins/onebot/pet_config` | `portable_pet_config_commands.py`；复用应用会话，不另建独立菜单存储 |
| AI 意图、聊天、单独提及提示 | `plugins/onebot/ai` | `ai/chat_operation.py`、`ai/fallback_operations.py`；平台只提供事件及来源信息 |
| 配置提及回复、关键词回复、主题管理 | 旧 `messaging/matchers.py` 和 `matcher_rules.py` 已删除 | 公共 messaging 操作与公共投递；关键词回复统一请求冷却，且不替换正在使用的菜单 |
| 启动通知 | `plugins/onebot/startup_notice/__init__.py` | `operations/startup_delivery.py`；适配器只负责生命周期钩子 |

B站正文、图片、战队普通详情等不额外建立虚假的返回页面；有可继续选择的菜单保持原会话。

## 公共业务与适配器边界

刻印数值榜、活动、固定／图库图片、会议、数据版本、预告及赛季倒计时均已由 OneBot 适配器调用公共操作。榜单管理同样共用公共操作，超过 3 秒提示一次，快速结果不提示，提示发送失败仍继续执行。

开服和关于已接入 `portable_operational_commands` 公共操作，OneBot 独立开服处理器已删除。公共 `PortableCommandRouter` 在执行前使用同一 CommandContract 复核功能、超管、会话范围与黑名单；无头实例状态仅允许超管私聊。无前缀“开服查询”只返回用法提示，不触发重连；关于与开服不增加慢提示。管理员重连失败保留公告及失败原因，并显式标记业务失败。

这里保留的适配器负责事件转换和发送，不是另一套查询实现；主动推送同样不重复注册业务调度。

命令通过 `PortableCommandRouter.execute` 执行并交给公共 `CommandReplyDelivery` 投递。菜单引用锚点由公共层依据实际回执登记，不在 OneBot 发送闭包或官方发送器中注册。公共层同时负责出站身份观察的候选生命周期与投递异常收尾；平台只转换协议、发送并返回回执。未认领群的官方提示保留原有不推断出站身份策略，入站路由及身份观察仍须进一步收口。

规范化输入先进入公共 `CommandIngress.handle`，统一消息 ID 判重、身份准备、路由检查顺序、识别及识别失败的管理告警，再进入业务执行。OneBot 原生规则不再提前调用识别；仅认领输入或确认重放停止后续 matcher，投递失败也不重新进入 AI 或旧入口。官方身份观察、union 合并入口及榜单目标镜像补查已经移出 SDK runtime。OneBot 镜像观察/静默/自身事件预处理及路由委托仍待统一，尚不能视为完整公共入站策略。

消息 ID 账本与业务请求生命周期分开：前者按平台、执行账号、群/私聊、会话 ID 和消息 ID 防止重放，不标记业务成功；后者在业务或投递失败时释放，使新消息可以重试。应用组合根为两端注入同一个 SQLite 账本，沿用 `cache_root/qq_official/inbound.sqlite` 路径并迁移原官方表；目录名不表示只有官方消息使用它。无外部资源的独立公共运行时使用有界内存存储，生产 SQLite 出错不会回退到它。账本异常只向管理目标告警，不执行命令或向任意未识别输入回复。此账本不承诺跨崩溃的 exactly-once；同一消息在保留期内不因失败释放而自动重做副作用。

主动推送由应用生命周期注册公共业务服务和共享投递路由，不因本轮菜单迁移新增调度或收件人。

OneBot 数字账号路由由公共 `services/onebot_routing.py` 唯一解释；入站归属、主动推送、能力与账号别名读取同一配置，协议 `BotRouter` 只查找选中账号的在线连接。私聊入站仍归接收账号，主动发送仍按用户路由；离线不换用其他账号。预处理调用时机及官方动态端点路由仍需进一步收口，没有新增路由配置字段。

自身口令准入由公共 `OwnAccountCommandPolicy` 读取规范化事实，公共准入将结果写入新的上下文并保留引用/提及，协议适配器不再重写事件或维护 accepted/admin_binding 状态。消息 ID 只由公共入站账本判断；自身策略仅维护有界出站回声记录，覆盖前缀及代绑文本，按账号、完整会话、正文和被提及成员隔离。组合根为收发两端注入同一实例；显式发送在 SDK 提交前登记最终内容，从结构化回执结算，不再注册全局 calling-api 回声钩子。已知未发送释放，成功/不确定送达/提交后取消保留；相同内容并发发送共享一条带待定数和保留时间的记录，失败不能清掉其他发送或延长旧记录有效期。通过准入仍须遵守公共 Feature、黑名单与业务授权；静默模式优先于自身口令开关。

镜像观察、静默、自身口令、群归属和全体提及的准入顺序现由无框架依赖的 `OneBotAdmissionService` 负责，原生 `OneBotEventIngress` 只解码、应用结果和注册事件预处理；旧 `ingress_policy` 模块已删除，无兼容导出。镜像证据必须与规范化账号、群和发送者一致。准入异常复用组合根持有的公共错误报告器，仅向管理目标告警，不调用查询、AI 或普通消息发送；取消不转换成失败。保留静默期间后台观察及代绑路由例外，群/私聊仍使用各自必要路由语义。有界内存回声不提供跨进程恢复保证；持久重放边界及框架生命周期仍需继续核验。

身份观察通过公共消息认领端口按平台、账号、群/私聊、会话和消息 ID 隔离，来源只首次进入待配对缓冲；重放既不能再次关联，也不能刷新配对时间窗。不同群偶然使用相同消息 ID 时，两份证据均保留。删除原来的两段候选替换判重，不再并行维护。该缓冲是身份核对证据，不是业务请求成功记录。

生产身份观察复用 `SqliteInboundMessageClaims`，但使用独立的 `<cache_root>/identity/observations.sqlite`，不与命令执行的认领记录相互消费。两种处理目的使用同一存储实现与规范化键，分别拥有状态；重启后保留期内的旧观察仍被拒绝，原有配对窗口及可信来源规则不变。独立无外部资源的测试使用有界内存端口；生产存储失败向上交给公共错误边界，不退回内存、不继续猜测关联。失败后需要新消息重新观察，不把来源认领解释成业务或投递成功。没有新增 TOML/env 配置，也不迁移身份绑定表。

OneBot 发送与历史回执的消息 ID 共用 `integrations/onebot/receipts.py`，复用现有有符号 ID 语法。布尔值、容器、浮点或无效字符串不再被转成成功 ID；指令回复和主动发送共用结果转换，将无有效 ID 的结果标记为不确定送达，不自动重发。负数及零 ID 仍有效，历史核验不再只接受非负数字。实际命令入口验证异常回执后释放请求和成功冷却，新消息可重新执行，原消息仍受公共重放账本约束。

配置的数字群出站窗口、超管优先队列、管理群豁免和许可结算统一由公共 `services/messaging/outbound_limits.py` 的显式发送入口负责。生产命令、戳一戳、审核、管理/业务通知及私有动作均通过应用出站端口；删除 `outbound_hooks.py`、SDK 数据字典关联表和全局额度钩子，不保留兼容安装或回执接口。主动推送与普通回复继续共享原窗口，预占只扣一次，未将这套数字群规则套用到官方端。任意外部插件绕过应用端口的原生 API 调用不属于受支持的业务发送路径。

重置不再复用许可令牌，迟到的旧失败回执不能退款新请求。队列 worker 的结束回调由公共服务负责，覆盖启动前/运行中取消；释放等待者且不重生 worker，旧 worker 不能清理替换后的队列。队列任务名和异常日志使用脱敏目标，日志不包含源异常正文。遗留测试入口、状态 I/O 和框架生命周期仍待审计，不因此宣称完整目标完成。

`GroupOutboundRateLimitService.execute_send` 显式持有发送尝试：准入/排队、冷却提示决策、开始提交标记和回执结算在公共层完成。删除只为原生钩子借用许可而存在的 ContextVar、owns_send 及尝试内无消费者的 group_id；发送回调只接收当前真实尝试，不读取环境中的许可。窗口条目自身记录是否已结算，重复/矛盾回执不能退款已确认的不确定发送，不另建回执账本。

提交前取消或明确未发送会释放许可；提交后取消、超时、缺回执及未分类失败保留窗口。中断标记由协议端转换，公共层决定清除普通推送等待者，保留超管优先通道。HTTP/WS 原始响应由唯一协议校验转成 OneBotActionError；已知 HTTP 网络失败由宿主转成 OneBotTransportError，不依赖 SDK 异常类或读取异常正文/repr。API 未提供能确认未提交；通用网络错误无法区分超时与断线，保留不确定状态且不据此开启断连冷却。真实 ConnectionError 可标记连接中断但仍不能证明未送达。删除离线/断连文本猜测；并发 details 旧测试入口尚未移除。

生产普通命令现由组合根显式注入 OneBot 出站端口，主 matcher 只转换输入、传递接收连接并在认领后停止传播，不再调用 `Matcher.send`。`reply_from` 校验规范化执行身份与接收账号，使用同一公共回复模板及 `execute_send`；群/私聊回复均固定接收连接，不查询主动推送路由，也不补查昵称或换用其他在线账号。原生预处理在身份观察之前校验连接来源，独立命令入口及发送端也拒绝来源不匹配。自身账号不 @自己、图片引用、负数/零消息 ID、配置成员提及、菜单和超管优先队列保持原语义。

传输端从异常转为失败回执不能使管理告警丢失：公共 `CommandReplyDelivery` 对已尝试但未确认送达/连接不可用的结果调用现有安全管理报告器，两平台一致；不记录回执原文，不重试，也不向普通用户追加失败消息。明确拒绝、未尝试发送仍按其结果结束，不因此新增告警。旧 `send_portable_event_reply`/portable_queries 仍有旧测试及并发 details 测试消费者，尚未删除；它们不参与生产普通命令注册，不添加旧入口的新消费者。非命令事件和旧测试迁移仍未完成。

戳一戳已迁入公共 `PokeReplyService`：接收规范化 `CommandContext`，公共层先判断群提示限流，再请求群角色、选择用户/群自定义文案或权限过滤的随机口令、组装结构化提及并交付。数字配置在组合根编译，不由服务解析；群内保留原 `@用户 + 空格 + 文本`，私聊不添加提及、也不新增提示限流。原生插件不再调用 `Matcher.finish/send`，通过 `send_from` 固定真实接收连接，经同一公共发送许可与回执结算；通知没有消息 ID，不伪造引用，也不查询主动路由。官方端只验证公共策略可复用，不声明存在官方戳一戳事件。红包、入群、旧测试和框架资源仍待继续核验/迁移。

红包通知的消息、notice 两个真实入口现注入组合根持有的同一个 `RedPacketNoticeService`。插件只识别原生红包字段、转换规范化上下文和提供群名协议查询；启用开关、群冷却、管理文案与 `AdminNoticeService` 调用在公共层执行。删除独立红包冷却字典，复用通用 limiter，保留冷却边界和设为 0 时不限次；准入发生在群名查询前，失败或取消不重置本次冷却，避免双来源立即重复通知。没有红包唯一事件 ID，因此不宣称精确去重。群名失败仍降级无群名提醒，但日志只保留错误类型。通知沿用既有管理目标、TD 与平台出站路由，不向触发的普通群补发。

公共回复模板只修改展示片段，不重建业务结果：自动补发送者提及时使用原消息替换 `parts`，保留 `request_succeeded` 与交互 prompt。双平台群聊的失败文本曾在此被默认值改成成功，现已通过修复前失败的矩阵回归；群/私聊、图片及既有提及的可见格式不变。这是模板状态完整性修复，不将其描述为已证明发生的额度事故。

审核提醒的扫描由应用 startup 注册，OneBot 连接只触发公共服务恢复待办，不再重新完整启动；shutdown 清理审核任务但保留待办数据，不删除其他服务任务。关闭功能或后续提醒时不注册空扫描。任务键包含会话和操作者的账号作用域，避免同 ID 在不同账号下互相覆盖；公共在途保护阻止同一待办重叠发送，成功后重读待办状态，失败/异常/取消保留待办并释放在途状态。该保护不宣称跨进程或崩溃时的 exactly-once。实际入群入口仍只转换协议信息、忽略机器人自身入群，权限、通知和安排后续提醒归公共服务；不伪造官方群成员入群事件。

## 必要平台差异

- OneBot 事件、自发消息识别、身份辅助核对、昵称及群名补查、群角色 API。
- QQ 官方 AppID 作用域身份、消息时效、富媒体上传、Markdown／按钮及回执格式。
- 戳一戳、红包等平台特有事件，不在官方端伪造接口。
- OneBot matcher 负责注册事件，权限使用公共 CommandContract；不再用 NoneBot 原生 SUPERUSER 另建超管判定。菜单执行再次检查实际操作者。

## 五项差异的统一结果

| 项目 | 公共行为 | 实际入口与保留边界 |
| --- | --- | --- |
| 配置文本附带的 @ | 显式成员优先，否则使用配置对象，无目标交由回复层回复发送者；去重，不附加发送者 | 两平台公共路由调用 `build_portable_text_operation`；官方配置目标须解析为同账号的可信成员 |
| 战队订阅确认 | 公共确认菜单归发起人及当前机器人，确认时检查管理权限及待办快照，`0` 取消 | 普通战队、订阅详情、玩家详情扩展均接入 `subscription_confirmation`；旧按群捕获是／否的 matcher 已移除 |
| 巅峰查询进度 | 池子、投票和统计榜超过 3 秒提示一次，已有等待提示则不再发送；提示失败继续交付结果 | 两端使用公共巅峰操作；发送仍经过平台消息限流 |
| 个人榜单目标 | 两端由公共操作解析目标，允许多候选；按最终玩家及榜单做重复判定 | OneBot 规则仅确认格式和可见目标，不提前执行单目标解析；候选展示不查询淘米 |
| AI 执行 | 两端共用聊天执行，保留各自事件来源信息及共同的意图路由 | 删除“处理中...”及 ai.waiting_notice，旧字段按未知配置报错 |
| 战队订阅管理 | 新增、取消、列表调用同一操作，执行前重新检查目标授权与管理角色 | 查询后的确认仍归当前机器人、群和发起人 |
| 旧 Prompt 公共基础设施 | 删除临时 matcher、旧队列、状态管理、应用注入及兼容 API | 请求令牌独立保存在 request_state；公共菜单独立负责取消、FIFO 和迟到结果 |

私有 `details` 已基于当前私有 main 源码整合公共扩展基础，删除旧 OneBot matcher、PrivateExtensionRuntime、load_peak_pools 和裸 QQ 参数调用。普通阵容与详细阵容都由公共扩展操作执行，保留特性、技能、刻印及详细图片；没有修改私有 main，没有合并或重写分支历史。

详细阵容仅允许超管发送“阵容详情<数字米米号>”，不进入普通玩家菜单、不触发绑定建议。动作的访问范围、菜单可见性、目标语法与绑定建议通过公共注册契约声明；入口与执行前按实际操作者复核。内置及私有动作共用 core/player_detail_actions.py 中同一请求类型，公开契约不再重复定义请求。详细包使用公共连接、排队和额度服务，解析及渲染成功后幂等结算；失败或元数据不完整不结算，不补零。

私有 experiments 仅保留历史参考，不参与运行注册、测试收集或发布；tools 保留原有未跟踪内容。测试基于本地公共工作区，发布前仍需在公共提交完成后更新 private 的 public-runtime.json 并重新验证配对，不能把旧 SHA 视为新契约的发布依据。

共享命名与位置已清理：QQ 配置引用使用 config/qq_references.py；橱窗 TD 使用 services/seer/lucky_skin_window_subscriptions.py；目标配置编译移出平台适配器；战队审核功能策略使用公共 FeatureTeamAuditPolicy。数字 QQ 的逻辑身份仍沿用现有存储表达，不迁移身份或数据库。

审核待办的存取统一为异步接口，连接、迁移、SQL 和事务关闭在同一 worker 中完成；应用显式拥有这些事务任务，关闭共享资源前等待其结束。调用取消不保证已提交事务回滚。停止或重启之后，旧恢复读取不能重新注册提醒任务；待办表结构与调度时刻不变。完成、离群清理和阶段推进只在待办仍与读取时一致时执行，避免旧流程删除或覆盖新入群记录；不改变其他账号的记录。调度回调只处理已到期记录，成员检查后再次核验待办与生命周期；旧回调不能提前处理新待办或在停止后清理它。其他同步仓库仍需核验，不将此步骤视为全部状态 I/O 已完成迁移。

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
