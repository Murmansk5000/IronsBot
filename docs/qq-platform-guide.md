# QQ 平台接入、身份与发送细节

QQ 官方机器人与 OneBot 可在同一个 IronsBot 进程中运行。
NoneBot2 只托管 OneBot V11/NapCat，QQ 官方连接由腾讯 `qqbot-agent-sdk` 作为应用资源
启动和关闭，不经过 `nonebot-adapter-qq`。只要任一 TOML 官方账号拥有完整的
AppID 和 Secret 环境变量，QQ 官方就会自动成为唯一出站平台；NapCat
不回复指令、不主动发送，官方端掉线或发送失败也不会回退到 NapCat。
没有任何官方凭据时，才由 `[bot.onebot].send_messages` 决定 NapCat 是否发送。

官方端支持群聊
`@机器人` 与 C2C 被动消息，开放基础说明、米米号、赛尔数据、战队、精灵/立绘、刻印/宝石、
套装/部件/称号、属性/异常状态、巅峰资料、榜单、刻印数值榜、群星牌资料、圣域/祝印、
活动、本周新增内容和 B站历史动态查询。查询出现多个候选项时可发送数字选择，
发送 `0` 退出；已开通并启用自定义按钮的账号还会显示同一组快捷按钮。其中
`下周预告` 也可验证图片回复链路。引用输入通过公共菜单锚点校验，
引用正文中的 @ 不作为本次成员目标。绑定状态按可信统一身份解析；未关联的端点不按昵称合并。
群内直接 @ 一名已绑定成员可将其作为查询或绑定目标，但仍受未绑定者及超管账号访问策略限制。跨平台群成员身份可选由静默 NapCat 观察验证，见下方配置。
启用 `ai_chat` 后，私聊中的未注册文本和群内直接 `@机器人` 的未注册文本会进入
同一个 AI 服务；已注册查询始终优先。没有为任一 `[ai.providers.<别名>]`
配置对应的 `AI_KEY_<大写别名>` 时，不会开放 AI 聊天入口。提供商按
`ai.provider_order` 切换，每个提供商内部再按 `models` 顺序切换模型。
`[[messaging.commands]]` 中的文本口令，以及
`[[messaging.sendpic.configs]]` 图片口令，也会直接复用同一配置；需要把文本口令的
`feature` 或图片功能 `image` 加入相应群／用户策略。本地图片继续从挂载目录
读取，远程图片继续使用已配置后端，不会复制进机器人镜像。带数字 QQ 提醒对象的文本
口令通过可信身份解析到当前 AppID 的成员；无法解析时明确提示，不静默丢弃提及或更换收件人。

学习力、巅峰姬、必先、技能石和伪随机表的八个固定图片口令默认启用，
五张图片随程序发布，不再需要额外挂载。可在
[固定图片配置说明](examples/fixed-images.md) 中查看如何使用相同 ID 关闭或覆盖
内置口令，以及如何添加自定义图片口令。

主动发送默认开启；只有明确不应承担任何主动投递的专用账号才需要设置
`proactive_messages = false`。开启 `team_resource_subscription` 时不能关闭该项，
否则配置会被明确拒绝，避免订阅成功后无法收到提醒。平台实际发送额度和权限以
当前机器人应用后台为准。运行时会接收并持久化腾讯的
`GROUP_MSG_RECEIVE/GROUP_MSG_REJECT`、`C2C_MSG_RECEIVE/C2C_MSG_REJECT` 以及机器人
加入/移除事件；目标明确关闭主动消息或移除机器人后，所有主动推送会在调用平台接口前
停止。重新开启后自动恢复，被动命令回复不受该状态影响。
OneBot 主动推送以返回消息 ID 作为平台受理回执；超时、无法判定是否发送的
异常或缺少回执时标记为送达不确定，不自动重发，避免重复推送。明确离线或
发送中连接中断后，后台推送按该账号暂缓，默认 60 秒，冷却到期先放行一次探测；可通过
`messaging.proactive_delivery.transport_failure_cooldown_seconds` 调整；
其他账号和直接命令回复不受影响。平台受理不等于接收者已读。
橱窗私聊推送可用 `seer.lucky_skin_window.verify_onebot_history = true`
额外查询 OneBot 消息历史；默认关闭，仅使用实际发送账号，最多等待 5 秒。
历史核验失败只记录状态，不撤销平台回执或重新发送。QQ 官方端没有此核验能力。

## 账号归属与凭据

基本配置见 [README 的官方部署](../README.md#方式一qq-官方机器人)，不要重复声明同名 TOML 表。

每个 `[bot.qq_official.accounts.<别名>]` 都是独立机器人账号；别名只能使用字母、
数字和下划线。可继续增加 `example_bot_2` 等账号表，共用同一套 IronsBot 业务逻辑。
`default_account` 只有在共享默认路由开关允许时才接管未分配目标；私聊由实际收到事件的账号处理。启用多个官方账号时必须明确填写，
不按 TOML 书写顺序猜测。`group_routes` 使用 `[identities.groups]` 的逻辑群别名，
把特殊群交给指定账号；同一逻辑群中的其他官方账号保持静默。
若逻辑群只声明了一个已启用官方账号的 OpenID，该账号会自动成为该群响应者，
不必在 `group_routes` 重复填写；一个逻辑群声明多个官方账号时才需显式选择。
业务功能只由 `features.group_policy` 和 `features.user_policy` 授权，机器人账号不授予
默认服务。旧账号级 `features/group_policy/user_policy` 仅兼容读取并告警，不再生效。
普通用户个人权限仅用于私聊，不放行群内未开放的功能；超管遵循 `superuser_bypass`。
`bot.superusers` 可同时填写 owner 和多个 NapCat QQ；统一授予管理权限。
管理通知只取 `features.user_policy` / `group_policy` 中显式授予的 `admin_notice`，
并遵循 TD 退订。`all`、超管身份及 `superuser_bypass` 都不会自动订阅通知或业务推送。
例如 `superusers = ["owner", "xiaohao"]`，仅在用户策略给 owner 添加
`admin_notice`，即可让两者都有管理权限但只有 owner 收到管理通知；不必给 xiaohao 加 `all`。
旧 `admin_notice_superusers` 字段已删除，请迁移到显式用户策略。
被动回复始终由收到事件的同一 AppID 发出，不能把一个官方账号收到的消息转给另一个
账号回复；入站路由会在业务执行前选定唯一账号，避免两个机器人重复响应。
账号不再使用 TOML `enabled`；TOML 声明公开 AppID，并由同后缀的
`APP_SECRET_<AppID>` 激活。为未声明 AppID 提供 Secret 会阻止启动。
账号只有在 SDK 收到 `READY` 或成功 `RESUMED` 后才视为健康。
`startup_timeout_seconds` 控制启动等待时间；`required = true` 的账号未能及时就绪会
阻止应用启动，`required = false` 的账号则进入可观察的 degraded 状态并继续重连。
官方入站消息 ID 会在业务执行前持久化到 `/app/data/qq_official/inbound.sqlite`，防止
Resume、平台重投或进程重启导致同一条指令执行两次；该状态无需额外配置。
主动推送目标同样来自共享群/用户配置，账号仅决定使用哪个发送通道。
目标必须填写 `[identities]` 中声明的别名，不再直接散写 OpenID。默认开启的
`proactive_messages` 在应用具备对应权限后，使定时消息与活动/B站推送复用同一套
发送、重试和退订逻辑；用户可发送 `TD`、`退订` 或 `订阅` 管理当前会话，发送
`推送时间` 管理当前会话可修改的定时推送时间。

跨平台使用同一个真实群或用户时，只在 `[identities.groups]` / `[identities.users]`
声明一次 QQ 端点与各官方账号 OpenID。一条全局 `features.group_policy` /
`user_policy` 会展开到该逻辑目标的所有显式端点，不需要再起 `official_admin`
之类的平台专用名字，也不再维护账号内的第二套别名表。
每个原生端点只能归属一个逻辑别名；同一群号、QQ 号或同一账号作用域内的 OpenID
若被多个别名重复声明，严格配置加载会直接失败，而不是任意选择其中一个。

`custom_keyboards` 默认关闭。只有腾讯后台已为该应用开通内邀的“自定义按钮”能力时
才能设为 `true`。启用后，有限选项会附加最多 5 行、每行 5 个的指令按钮；按钮发送的
动态会话 action 与手输序号共用同一个用户和会话绑定，不支持按钮的客户端仍可输入数字。
用户也可以引用机器人的菜单消息后输入序号或命令；引用内容仅作为回复元数据保存，
本次新输入仍经过相同的去重、权限、Feature 和会话路由，不会被静默忽略。

远程图片通过 SDK URL 上传，本地渲染结果通过 SDK 分片上传，不再整体 Base64 编码。
SDK 未公开 `file_info` 的有效期，因此令牌只立即使用一次，不猜测并缓存有效期；平台
拒绝超大图片或当日上传额度耗尽时，机器人会返回明确文字说明。

公开 AppID 写入 TOML，只有 AppSecret 放入环境变量：

```text
APP_SECRET_10001=你的 AppSecret
```

腾讯旧版静态 Token 已弃用，不要把 AccessToken 写入配置。程序使用 AppID 与
AppSecret 获取短期 AccessToken，并在内存中自动刷新。每个账号在 TOML 中声明
`app_id`，例如 `app_id = "10001"` 对应 `APP_SECRET_10001`。新增机器人时只需
再声明一个账号及其公开 AppID，并增加一个同后缀的 Secret 变量。Secret 写进
TOML 会被严格拒绝。

多个账号的连接、AccessToken、OpenID、权限和主动消息路由按 AppID 隔离。同一个
OpenID 不能跨机器人账号复用，所有官方平台目标都必须携带其原始 AppID。
运行日志只记录 TOML 账号别名；消息 ID、群 OpenID 和用户 OpenID 仅记录不可逆短摘要，
便于关联同一次故障而不把平台原始标识写入日志。
OneBot 路由与发送失败同样只记录 QQ 目标和机器人账号的不可逆摘要，不输出原始 QQ 号
或群号。

`官方身份` 只是排障工具，不再是建立群映射的必经步骤。需要查看平台原始标识时，
可临时在目标群或用户的功能策略中显式加入
`qq_official_identity_info`，然后私聊发送“官方身份”，或在目标群 @机器人发送
“官方身份”。机器人只向当前会话返回该事件携带的用户、群或群成员 OpenID；完成
本机配置后应立即移除这个 Feature。它默认关闭，也不会被 `all` 功能包隐式启用。

当前使用 WebSocket 连接，不要求部署额外的公网回调地址。平台下发的是 OpenID，
不是普通 QQ 号。静态 owner 等身份在 `[identities.users]` 中统一声明；普通群成员
不需要手工写入 TOML。设置 `identity_verification = true` 后，身份核对依赖
`trusted_official_bots` 中的可信账号，保留所需 NapCat 消息观察。官方回复通过 `message_reference`
引用触发它的成员消息，NapCat 从引用来源读取数字 QQ。任意正常群命令的回复都可用于
自动建立 `(AppID, group_openid) ↔ 数字群号` 映射；候选数字群只来自
`[identities.groups].qq`，映射写入状态库并在重启后恢复，无需把群 OpenID 再抄回 TOML。
程序使用已确认逻辑群、可信机器人、消息正文、提及顺序、短时间窗口和唯一匹配核对成员。
普通群友或 NapCat 发送的有效触发消息都可提供核对证据；同条消息中的发送者和多个提及目标逐一核对。
结构化目标缺失、数量或顺序无法对应、歧义、超时及绑定冲突时不猜测、不覆盖。
同一 AppID 中相同成员 OpenID 作为同一主体，群用于验证来源。关联后按既有规则合并可信绑定，
不向用户发送验证码；该流程不保证每条消息都有足够信息建立关联。

当前保留 `TODO(identity-migration)`：同一 AppID 下，已验证的 member_openid 暂按 user_openid 地址复用。
这是当前部署采用的临时假设，不是腾讯跨场景恒等保证；跨 AppID 始终隔离，后续迁移需重新核验。
配置的私聊地址、已观察 C2C 地址和此临时策略共同参与现有路由，不另加昵称推断。

B站及其他私聊推送统一使用用户指定账号；无指定且默认开关关闭时策略跳过。
允许默认账号时仅尝试该账号，缺少所选地址不切换唯一其他账号。
TD 和推送时间菜单也按实际选定的发送路由生成。地址修正不会自动补发此前已尝试的动态；
明确安全的失败重试依照[投递账本规则](configuration-and-subscriptions.md#b站投递与诊断)。

## 消息格式与回执

QQ 官方群文本需要提及时，使用经过身份作用域校验的 Markdown 提及与正文；
菜单编号和普通文本中的 # 会转义，URL 片段保持原样。不能把旧版“先单发最小提及、再发正文”的
生产实测当成当前固定消息数量。显式业务目标存在时不额外提及发起人，私聊不附加群成员提及。
被动回复使用来源消息上下文、消息序号和引用回执；多条图片与进度由发送层按平台能力转换。
平台回执表示受理，不表示已读；不确定送达不自动重发有副作用的内容。

依赖数字 QQ 账号配置的个人幸运橱窗也使用这条已验证关联。完成关联后，QQ 官方端可查询
当天橱窗、查看皮肤详情以及管理关注列表；未关联身份不会尝试按昵称或其他资料猜测。
现有 `[seer.lucky_skin_window]` 账号与米米号配置无需迁移。

腾讯官方 `qqbot-agent-sdk` 是可选运行组件。直接运行源码时使用：

```powershell
uv sync --extra qq-official
uv run --no-sync python -m ironsbot
```

源码启动会先读取项目根目录的 `.env`，再读取
`.env.<ENVIRONMENT>`（未设置时为 `.env.prod`）。系统、终端或容器中已经存在的环境变量
优先级最高；环境专用文件覆盖基础 `.env`。例如本机开发可在终端设置
`ENVIRONMENT=dev`，由应用自动读取被 Git 忽略的 `.env.dev`，无需逐项导入 Secret。
行为配置仍由 `APP_CONFIG_PATH` 指向 TOML，所有密钥仍只放环境变量。

源码的默认依赖集不包含该 SDK，因此从源码运行时必须使用上述 `qq-official` extra。
正式发布的 Docker 镜像已经同时包含 OneBot/NapCat 与 QQ 官方运行组件，不需要另外寻找
官方机器人专用镜像或传入 build arg。只有自行构建纯 OneBot 镜像时，才显式传入空的
`--build-arg IRONSBOT_RUNTIME_EXTRA=` 省略腾讯 SDK。

在目标群为机器人开启“接收所有消息”后，腾讯会下发
[`GROUP_MESSAGE_CREATE`](https://bot.q.qq.com/wiki/develop/api-v2/autogen/event/group_message_create.html)。
IronsBot 会处理其中明确匹配的命令和正在进行的选项会话，
普通聊天不会触发 AI 意图、AI 聊天或帮助提示。带 `@` 的消息若同时收到
`GROUP_MESSAGE_CREATE` 与 `GROUP_AT_MESSAGE_CREATE`，会按同一消息去重，只执行一次。
未开启该群设置时，群聊仍需 `@` 机器人。

## OneBot 自发指令与回复

可选配置（默认关闭，不使用时无需修改现有 TOML）：

```toml
[bot.onebot.self_commands]
enabled = false
prefixes = ["演示 ", "示范 "]
```

NapCat 需开启 `reportSelfMessage`。启用后，机器人 QQ 本人在群内发送
`演示 帮助` 可执行命令，菜单续接和退出也必须带前缀：`演示 1`、`演示 0`。
保留前缀末尾空格；只接受本人群消息中的文字和引用，不接受图片或提及段。
使用该 QQ 在 TOML 中的现有权限，不自动提权，也不自动获得管理通知资格。
官方账号接管或 OneBot 发送关闭时，此开关不能解除 NapCat 静默。

旧 `[runtime.self_commands]` 移到 `[bot.onebot.self_commands]`，旧 `prefix`
改为 `prefixes`；旧 `superuser` 不恢复，请使用现有权限配置。没有旧字段兼容别名。

OneBot 文本命令回复统一引用原消息，并以 `@发起者` 加换行开头；纯图片不另发
空提及，自发指令不提及自己。当前消息包含 `@全体成员` 时一律不响应，
即使同时 @机器人；引用正文中的提及不参与判断。主动通知和 Notice 保持原有策略。

## 进一步阅读

[返回 README](../README.md) · [玩家与菜单](player-query-guide.md) ·
[配置与订阅](configuration-and-subscriptions.md) · [当前入口边界](onebot-menu-parity.md)
