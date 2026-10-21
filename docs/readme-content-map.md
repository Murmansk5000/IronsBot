# README 内容迁移核对表

[返回 README](../README.md)

本表对照本轮改写前 Git 中的 README（1005 行），按空行分段；代码围栏作为整体登记。
来源 Git blob：`405ddd399ef5adadc8f24e7c1f833560c279b6fa`，避免后续提交导致旧行号失去定位依据。
原文用于核对来源，修正后的当前行为位于目标文档，不把旧规则重新当作现行规则。
所有原段均有去向；标题、重复示例和署名也登记。涉及多个主题的段落由目标章节及其交叉链接共同承接。

## 文档分工

| 目标 | 保留内容 |
| --- | --- |
| [README](../README.md) | 两种接入、运行环境、功能权限、常用命令、配置校验、导航、致敬及许可 |
| [玩家查询](player-query-guide.md) | 完整语法、绑定、候选、账号可见性、额度、预热、样本、橱窗及抛精灵 |
| [配置与订阅](configuration-and-subscriptions.md) | env、TOML 示例、AI、文本、图片、会议、B站、战队、定时消息及限流 |
| [平台细节](qq-platform-guide.md) | 官方能力、地址隔离与临时假设、映射、消息格式、回执、免 @ 和自发指令 |
| [运维与扩展](operations-guide.md) | 数据缓存、迁移、构建同步、重启更新、扩展、上游策略及 Windows |
| [已有专题](push-topics.md) | 主题口令、订阅、程序注册、历史和投递保证；固定图片及匹配沿用现有专题 |

## 过期说明修正

| 原说明 | 修正／依据 |
| --- | --- |
| 指定机器人离线回退默认账号；路由只管主动发送 | 选定账号不可用不改账号，OneBot 入站也检查群归属；router.py 与公共路由策略 |
| 默认账号无私聊地址时选择唯一其他账号 | 不跨账号兜底；PrivateConversationRoutes.decision_for |
| 机器人账号 features 授予业务／身份排障权限 | 群／用户策略授权，账号旧字段不生效；配置及 OfficialIdentityInfo 契约 |
| 官方引用输入被忽略／第三者每次都要引用 | 当前有效菜单可建立独立会话，后续直接选择；公共菜单协调器 |
| OneBot 玩家主入口仍未迁移 | 更新为当前公共操作及真实执行链状态，不保留旧阶段结论 |
| 群成员 OpenID 绝不参与私聊 | 记录现有 TODO：同 AppID 暂按相同地址处理，不能跨 AppID，也不能称作平台保证 |
| 官方最小 Markdown 提及与正文固定分两条 | 当前消息转换组织提及与正文，转义编号及 #，保留 URL 片段；历史实测不作当前消息数承诺 |
| 未知 TOML 字段一律阻止启动 | 未知／已删除字段告警忽略；已知字段类型、值及引用错误仍拒绝 |
| Watchtower 执行升级，镜像相同即可清理 | 独立监督器验证启动与稳定运行后清理，失败恢复；历史字段不当作现行修复方案 |
| 私有扩展只有一个游戏登录 | 复用公共账号池，无独立登录或服务，不限制池只有一个账号 |
| 样例只给 owner all 即能收管理通知 | 样例显式加 admin_notice，其他超管不自动订阅 |

## 逐段去向

旧行号仅用于定位改写前版本；“迁入”表示保留规则、示例与限制，允许为可读性调整表述和合并重复。

| 段 | 旧行号 | 原内容摘要 | 处理 | 当前去向 |
| --- | --- | --- | --- | --- |
| 001 | 1–3 | p align="center"   img src="icon.png" width="128" alt="IronsBot icon" | 合并重复／原地保留 | [对应内容](../README.md) |
| 002 | 5–5 | # IronsBot | 合并重复／原地保留 | [对应内容](../README.md) |
| 003 | 7–7 | IronsBot 是一个面向 OneBot v11 与 QQ 官方机器人的赛尔号机器人，基于 NoneBot2 构建，主要服务于自部署、Unra | 合并重复／原地保留 | [对应内容](../README.md) |
| 004 | 9–9 | 当前主线已经转为显式插件架构：通用功能位于 ironsbot/plugins，部署者自行维护的扩展位于 ironsbot/custom_plug | 合并重复／原地保留 | [对应内容](../README.md) |
| 005 | 11–11 | ## OneBot 自发指令与回复 | 合并重复／原地保留 | [对应内容](../README.md) |
| 006 | 13–13 | 可选配置（默认关闭，不使用时无需修改现有 TOML）： | 合并重复／原地保留 | [对应内容](../README.md) |
| 007 | 15–19 |  bot.onebot.self_commands enabled = false prefixes = "演示 ", "示范 "  | 合并重复／原地保留 | [对应内容](../README.md) |
| 008 | 21–25 | NapCat 需开启 reportSelfMessage。启用后，机器人 QQ 本人在群内发送 演示 帮助 可执行命令，菜单续接和退出也必须带前 | 合并重复／原地保留 | [对应内容](../README.md) |
| 009 | 27–28 | 旧 runtime.self_commands 移到 bot.onebot.self_commands，旧 prefix 改为 pref | 合并重复／原地保留 | [对应内容](../README.md) |
| 010 | 30–32 | OneBot 文本命令回复统一引用原消息，并以 @发起者 加换行开头；纯图片不另发 空提及，自发指令不提及自己。当前消息包含 @全体成员 时一律 | 合并重复／原地保留 | [对应内容](../README.md) |
| 011 | 34–34 | ## 功能 | 合并重复／原地保留 | [对应内容](../README.md) |
| 012 | 36–46 | - 米米号查询与 QQ 用户绑定：未绑定时，独立查询指定米米号会询问是否绑定；绑定后可直接使用玩家快捷查询。 - 战队资源订阅：群内发送“战队” | 合并重复／原地保留 | [对应内容](../README.md) |
| 013 | 48–48 | ## 镜像 | 合并重复／原地保留 | [对应内容](../README.md) |
| 014 | 50–53 |  docker.io/murmansk5000/ironsbot:latest ghcr.io/murmansk5000/ironsbot:la | 合并重复／原地保留 | [对应内容](../README.md) |
| 015 | 55–55 | latest 指向 main 的最新构建。构建还会发布精确版本 tag： | 合并重复／原地保留 | [对应内容](../README.md) |
| 016 | 57–58 | - base-version.revision：例如 0.6.0.3 - sha-xxxxxxx：精确到 Git commit | 合并重复／原地保留 | [对应内容](../README.md) |
| 017 | 60–60 | ## 快速部署 | 合并重复／原地保留 | [对应内容](../README.md) |
| 018 | 62–62 | ### Unraid | 合并重复／原地保留 | [对应内容](../README.md) |
| 019 | 64–64 | 在 Community Applications 中搜索 ironsbot 并安装，至少确认： | 合并重复／原地保留 | [对应内容](../README.md) |
| 020 | 66–73 | - Repository: murmansk5000/ironsbot:latest - WebSocket Port: 8085 - Iron | 合并重复／原地保留 | [对应内容](../README.md) |
| 021 | 75–75 | NapCat 反向 WebSocket： | 合并重复／原地保留 | [对应内容](../README.md) |
| 022 | 77–79 |  ws://UNRAID_SERVER_IP:8085/onebot/v11/ws  | 合并重复／原地保留 | [对应内容](../README.md) |
| 023 | 81–81 | 如果 NapCat 和 IronsBot 在同一个 Docker 自定义网络里，也可以使用： | 合并重复／原地保留 | [对应内容](../README.md) |
| 024 | 83–85 |  ws://ironsbot:8080/onebot/v11/ws  | 合并重复／原地保留 | [对应内容](../README.md) |
| 025 | 87–89 | 多个 QQ 机器人可以分别运行 NapCat，并把每个 NapCat 的 OneBot v11 反向 WebSocket 都连接到同一个 Iro | 合并重复／原地保留 | [对应内容](../README.md) |
| 026 | 91–107 |  messaging.bot_routing enabled = true default_bot = "main_bot" messag | 合并重复／原地保留 | [对应内容](../README.md) |
| 027 | 109–113 | group_a/group_b 和 owner/user_a 统一引用 identities.groups、 identities.use | 合并重复／原地保留；修正过期部分 | [对应内容](../README.md) |
| 028 | 115–115 | ### Docker Compose | 合并重复／原地保留 | [对应内容](../README.md) |
| 029 | 117–134 |  services:   ironsbot:     image: murmansk5000/ironsbot:latest     conta | 合并重复／原地保留 | [对应内容](../README.md) |
| 030 | 136–140 | 启动前先根据 config.example.tomlconfig.example.toml 创建 ./ironsbot-config/i | 合并重复／原地保留 | [对应内容](../README.md) |
| 031 | 142–142 | ### QQ 官方机器人 | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 032 | 144–149 | QQ 官方机器人与 OneBot 可在同一个 IronsBot 进程中运行。 NoneBot2 只托管 OneBot V11/NapCat，QQ | 迁入专题；修正过期部分 | [对应内容](qq-platform-guide.md) |
| 033 | 151–167 | 官方端支持群聊 @机器人 与 C2C 被动消息，开放基础说明、米米号、赛尔数据、战队、精灵/立绘、刻印/宝石、 套装/部件/称号、属性/异常状态 | 迁入专题；修正过期部分 | [对应内容](qq-platform-guide.md) |
| 034 | 169–172 | 学习力、巅峰姬、必先、技能石和伪随机表的八个固定图片口令默认启用， 五张图片随程序发布，不再需要额外挂载。可在 固定图片配置说明docs/ | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 035 | 174–188 | 主动发送默认开启；只有明确不应承担任何主动投递的专用账号才需要设置 proactive_messages = false。开启 team_res | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 036 | 190–190 | 在 ironsbot.toml 中启用： | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 037 | 192–219 |  bot.onebot enabled = true send_messages = true identity_verification  | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 038 | 221–250 | 每个 bot.qq_official.accounts.别名 都是独立机器人账号；别名只能使用字母、 数字和下划线。可继续增加 exam | 迁入专题；修正过期部分 | [对应内容](qq-platform-guide.md) |
| 039 | 252–257 | 跨平台使用同一个真实群或用户时，只在 identities.groups / identities.users 声明一次 QQ 端点与各 | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 040 | 259–263 | custom_keyboards 默认关闭。只有腾讯后台已为该应用开通内邀的“自定义按钮”能力时 才能设为 true。启用后，有限选项会附加最多 | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 041 | 265–267 | 远程图片通过 SDK URL 上传，本地渲染结果通过 SDK 分片上传，不再整体 Base64 编码。 SDK 未公开 file_info 的有 | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 042 | 269–269 | 公开 AppID 写入 TOML，只有 AppSecret 放入环境变量： | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 043 | 271–273 |  APP_SECRET_10001=你的 AppSecret  | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 044 | 275–279 | 腾讯旧版静态 Token 已弃用，不要把 AccessToken 写入配置。程序使用 AppID 与 AppSecret 获取短期 Access | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 045 | 281–286 | 多个账号的连接、AccessToken、OpenID、权限和主动消息路由按 AppID 隔离。同一个 OpenID 不能跨机器人账号复用，所有官 | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 046 | 288–292 | 官方身份 只是排障工具，不再是建立群映射的必经步骤。需要查看平台原始标识时， 可临时在目标账号的 features 中加入 qq_officia | 迁入专题；修正过期部分 | [对应内容](qq-platform-guide.md) |
| 047 | 294–307 | 当前使用 WebSocket 连接，不要求部署额外的公网回调地址。平台下发的是 OpenID， 不是普通 QQ 号。静态 owner 等身份在  | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 048 | 309–314 | B站私聊推送在 OneBot 出站关闭时，会使用该 QQ 已验证的官方**私聊用户**绑定， 并保留原有账号列表、推送模式和退订偏好。优先选择默 | 迁入专题；修正过期部分 | [对应内容](qq-platform-guide.md) |
| 049 | 316–322 | QQ 官方群回复同时引用用户的原始消息，并提及发令成员。腾讯群接口的普通 TEXT payload 不会解析成员 OpenID 提及，而自定义  | 迁入专题；修正过期部分 | [对应内容](qq-platform-guide.md) |
| 050 | 324–326 | 依赖数字 QQ 账号配置的个人幸运橱窗也使用这条已验证关联。完成关联后，QQ 官方端可查询 当天橱窗、查看皮肤详情以及管理关注列表；未关联身份不 | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 051 | 328–328 | 腾讯官方 qqbot-agent-sdk 是可选运行组件。直接运行源码时使用： | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 052 | 330–333 |  uv sync --extra qq-official uv run --no-sync python -m ironsbot  | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 053 | 335–339 | 源码启动会先读取项目根目录的 .env，再读取 .env.ENVIRONMENT（未设置时为 .env.prod）。系统、终端或容器中已经存 | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 054 | 341–344 | 源码的默认依赖集不包含该 SDK，因此从源码运行时必须使用上述 qq-official extra。 正式发布的 Docker 镜像已经同时包含 | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 055 | 346–351 | 在目标群为机器人开启“接收所有消息”后，腾讯会下发 GROUP_MESSAGE_CREATEhttps://bot.q.qq.com/wi | 迁入专题 | [对应内容](qq-platform-guide.md) |
| 056 | 353–353 | ## 常用赛尔查询 | 迁入专题；首页保留常用示例 | [对应内容](player-query-guide.md) |
| 057 | 355–364 | - 未绑定用户独立查询指定米米号或使用玩家详情快捷查询时，机器人会询问是否设为默认米米号；按提示回复 是/y 或 否/n。跳过后，下次独立查询仍 | 迁入专题；首页保留常用示例 | [对应内容](player-query-guide.md) |
| 058 | 366–366 | ## 插件架构 | 迁入专题并核对当前契约 | [对应内容](operations-guide.md#插件架构) |
| 059 | 368–373 | 通用用户功能位于 ironsbot/plugins，部署者自行维护的扩展位于 ironsbot/custom_plugins。当前版本仍由 py | 迁入专题并核对当前契约 | [对应内容](operations-guide.md#插件架构) |
| 060 | 375–378 | MatcherFactory 只负责构造 matcher、挂入命令权限与冷却，并执行启动校验。私有扩展也通过 自身标准 NoneBot 清单加载 | 迁入专题并核对当前契约 | [对应内容](operations-guide.md#插件架构) |
| 061 | 380–384 | - 赛尔查询：玩家、战队、精灵、刻印、装备、属性、巅峰、群星牌和榜单。 - 消息与内容：固定文本、定时消息、固定图片、腾讯会议和帮助。 - 推送 | 迁入专题并核对当前契约 | [对应内容](operations-guide.md#插件架构) |
| 062 | 386–386 | ## 配置方式 | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 063 | 388–388 | 行为与部署配置默认写在 TOML 文件里，并通过 APP_CONFIG_PATH 指向它。环境变量包含： | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 064 | 390–396 | - 配置位置：APP_CONFIG_PATH - 密钥：ONEBOT_ACCESS_TOKEN、每个官方账号的 APP_SECRET_AppI | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 065 | 398–400 | 示例配置按用户可见功能和运行依赖排列，而不是按 Python 模块名排列。新增功能或配置项前，先参照 配置布局与新增功能指南docs/co | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 066 | 402–402 | 示例环境变量： | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 067 | 404–423 |  APP_CONFIG_PATH=/config/ironsbot.toml ONEBOT_ACCESS_TOKEN=change-me ONE | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 068 | 425–425 | 每个赛尔账号在 seer.player_accounts 中声明米米号、可读名称、可选别名和 public。 | 迁入专题 | [对应内容](player-query-guide.md) |
| 069 | 427–455 | 绑定米米号部分名称 支持在可见账号中查找：精确匹配优先，一个候选直接进入 绑定流程，多个候选显示共享选择菜单，发送序号或使用已开通的官方按钮 | 迁入专题；修正过期部分 | [对应内容](player-query-guide.md) |
| 070 | 457–478 | 玩家详情扩展通过 PlayerDetailExtensionAction 提供动作、别名和查询回调，配合 同一 command_help_id  | 迁入专题 | [对应内容](player-query-guide.md) |
| 071 | 480–480 | ### 幸运橱窗 | 迁入专题 | [对应内容](player-query-guide.md) |
| 072 | 482–482 | 券名和单券抵扣钻石数读取 SeerAPI 发布数据，不在机器人内写死道具或面额。只有发布数据提供明确抵扣规则时才计算最低价；没有依据的道具只显示 | 迁入专题 | [对应内容](player-query-guide.md) |
| 073 | 484–484 | 超级管理员为群成员代绑米米号时，会清除该成员原有换绑冷却；即使重设为同一米米号也会清除。该成员随后仍可自行换绑，普通用户自行换绑的冷却规则不变。 | 迁入专题 | [对应内容](player-query-guide.md) |
| 074 | 486–486 | 迁移核对范围和未完成项见原版命令迁移核对表docs/specs/2026-09-15-command-parity.md。 | 迁入专题 | [对应内容](player-query-guide.md) |
| 075 | 488–488 | 个人橱窗及关注管理向 TOML 明确配置、且已绑定对应米米号的用户开放。需要： | 迁入专题 | [对应内容](player-query-guide.md) |
| 076 | 490–494 | 1. 在 seer.player_accounts 创建账号，填写 player_id、name 和可选 aliases。 2. 在  | 迁入专题 | [对应内容](player-query-guide.md) |
| 077 | 496–496 | 每天配置的 time 到达时，机器人会逐个使用专用账号读取当天四个皮肤，并向未在 TD 退订的对应用户私聊通知。手动发送“橱窗”时，有当天缓存则 | 迁入专题 | [对应内容](player-query-guide.md) |
| 078 | 498–498 | 超级管理员可用“橱窗123456”“橱窗账号别名”或“橱窗 @成员”查询指定账号的现有缓存，但目标必须列在 seer.lucky_skin_ | 迁入专题 | [对应内容](player-query-guide.md) |
| 079 | 500–502 | APP_CONFIG_PATH 是容器内路径。Docker/Unraid 常用值是 /config/ironsbot.toml； 宿主机上的真实 | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 080 | 504–506 |  你的 Windows 配置目录\ironsbot.toml - /config/ironsbot.toml  | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 081 | 508–512 | 该文件必须在启动前存在，可直接以 config.example.tomlconfig.example.toml 为模板。 程序只读配置， | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 082 | 514–515 | 改动 TOML 或环境变量后，可以只执行配置校验，不启动 NoneBot、QQ 官方连接、 调度器、数据库或其他网络客户端： | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 083 | 517–519 |  python -m ironsbot.config_check --config /config/ironsbot.toml  | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 084 | 521–524 | 源码环境可将 python 换成 uv run python。命令默认按正常启动顺序读取 .env 和 .env.ENVIRONMENT；容 | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 085 | 526–530 | 如果没有设置 APP_CONFIG_PATH，IronsBot 会默认读取当前工作目录的 config/ironsbot.toml；文件不存在会 | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 086 | 532–532 | 示例 TOML： | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 087 | 534–592 |  identities.groups admin = { qq = 123456789, official = { local_bot =  | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 088 | 594–600 | B站推送只补发明确未提交成功的内容，失败后按 2、5、10 秒重试，最多四轮。 补发按上一轮失败会话数二分批执行，并遵守 max_paralle | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 089 | 602–608 | B站推送诊断默认以 INFO 写入主日志，可按 dynamic=动态ID 筛选同一条推送。 日志包含轮次、批次并发、目标摘要、排队与执行耗时 | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 090 | 610–623 | 配置字段、默认值、中英文说明和示例集中维护在 config.example.tomlconfig.example.toml。查询权限和推 | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 091 | 625–630 | features.bundles 可以定义 standard、lite 等可复用组合；组合之间可以引用， 最终按并集展开。all = "m | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 092 | 632–635 | TOML 对已识别字段严格加载：既非内置也未被消息动作声明的 feature、未知 B站账号引用、 未知 Seer 展示区块和残缺 AI act | 迁入专题；修正过期部分 | [对应内容](configuration-and-subscriptions.md) |
| 093 | 637–661 | 在 group_policy 或 user_policy 的目标项中写入 blacklist，可永远静默忽略该 群或用户；超级管理员也不会绕过黑 | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 094 | 663–667 | 群消息发送额度默认关闭；显式设置 messaging.outbound_rate_limit.enabled = true 后，使用 me | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 095 | 669–669 | 行为配置只属于 ironsbot.toml；.env 和 Unraid 模板只保存部署参数与密钥。 | 迁入专题 | [对应内容](configuration-and-subscriptions.md) |
| 096 | 671–671 | ### Feature 对照表 | 合并重复；保留功能语义 | [对应内容](../README.md#feature-对照表) |
| 097 | 673–715 | ／ feature ／ 作用 ／ ／ --- ／ --- ／ ／ all ／ 除 admin_notice 外的大多数功能总开关；不包含管理通知 | 合并重复；保留功能语义 | [对应内容](../README.md#feature-对照表) |
| 098 | 717–717 | ### 通用主题推送与抛精灵 | 合并到专题 | [对应内容](player-query-guide.md#抛精灵) |
| 099 | 719–722 | 两项功能共用 OneBot 与 QQ 官方的权限和业务实现。all 包含 push_topics、pet_flip；自定义功能组合需自行加入，s | 合并到专题 | [对应内容](player-query-guide.md#抛精灵) |
| 100 | 724–725 | 主题由超级管理员创建、启停和广播；群主、群管理员及超级管理员管理本群订阅， 私聊用户管理自己的订阅。例如： | 合并到专题 | [对应内容](push-topics.md) |
| 101 | 727–734 |  推送新建 公告 群公告 订阅公告 我的订阅 推送 公告 本次公告内容 退订公告 推送停用 公告  | 合并到专题 | [对应内容](push-topics.md) |
| 102 | 736–741 | 其他入口包括 推送列表、推送启用 公告、推送删除 公告、 推送订阅者 公告 和 推送直发 公告 群:群别名 内容。 直发仍需目标权限与当前机器人 | 合并到专题 | [对应内容](push-topics.md) |
| 103 | 743–744 | 没有新增环境变量；主题数据保存在既有运行状态库，继续持久化 /app/data。 SDK 主动消息能力与接收方设置仍由现有投递层检查。 | 合并到专题 | [对应内容](push-topics.md) |
| 104 | 746–746 | ## 数据与缓存 | 迁入专题 | [对应内容](operations-guide.md) |
| 105 | 748–748 | 建议把 /app/data 持久化。这里会保存： | 迁入专题 | [对应内容](operations-guide.md) |
| 106 | 750–756 | - SeerAPI / alias SQLite 缓存 - B站 Cookie 与动态状态 - 米米号样本排行 SQLite - data/st | 迁入专题 | [对应内容](operations-guide.md) |
| 107 | 758–759 | 大型缓存按生命周期保持独立；不会为了减少文件数量而把榜单事实、阵容图片 Blob 或 AI 对话历史塞进共享状态库。 | 迁入专题 | [对应内容](operations-guide.md) |
| 108 | 761–761 | ### 状态库迁移 | 迁入专题 | [对应内容](operations-guide.md) |
| 109 | 763–765 | 已有部署升级后，先停掉机器人，再用新镜像把旧的小型 SQLite 一次性迁移到两个共享状态库。 命令默认只预览；确认输出后再加 --apply。 | 迁入专题 | [对应内容](operations-guide.md) |
| 110 | 767–767 | Unraid 默认数据挂载为 /mnt/user/appdata/ironsbot/data： | 迁入专题 | [对应内容](operations-guide.md) |
| 111 | 769–786 |  docker pull murmansk5000/ironsbot:latest docker stop ironsbot # 预览，不修改文 | 迁入专题 | [对应内容](operations-guide.md) |
| 112 | 788–790 | 备份默认位于 data/state-migration-backups/UTC时间/。稳定运行 7 天后可手动删除对应备份。 若 TOML  | 迁入专题 | [对应内容](operations-guide.md) |
| 113 | 792–792 | 迁移后从 TOML 删除以下旧字段；新版本不再读取它们： | 迁入专题 | [对应内容](operations-guide.md) |
| 114 | 794–800 | - activity.cache_path - messaging.push_unsubscribe.data_path - messaging | 迁入专题 | [对应内容](operations-guide.md) |
| 115 | 802–802 | seer.player.lineup.cache_path 不在收口范围内，阵容图片缓存仍保持独立。 | 迁入专题 | [对应内容](operations-guide.md) |
| 116 | 804–805 | 主数据发布文件现使用 data/seerapi-data.sqlite。确认新版本已成功下载并能查询最新数据后， 旧的 data/ironsbo | 迁入专题 | [对应内容](operations-guide.md) |
| 117 | 807–807 | 超级管理员发送 /更新数据（别名 /数据更新、/同步数据）时，IronsBot 会先只读比较本地与已发布数据的指纹，再显示后续选项： | 迁入专题 | [对应内容](operations-guide.md) |
| 118 | 809–810 | 1. 同步已发布数据，不触发远程构建。 2. 检查上游、依次构建并同步数据。 | 迁入专题 | [对应内容](operations-guide.md) |
| 119 | 812–813 | /强制更新数据（别名 /强制数据更新、/强制同步数据）只会让第 2 项向支持的工作流传入强制构建参数。第 2 项使用 operations.d | 迁入专题 | [对应内容](operations-guide.md) |
| 120 | 815–819 | 1. Murmansk-Seer/data-update-workflows：检查淘米官方资源包，更新 Unity 资源和完整配置源。 2. M | 迁入专题 | [对应内容](operations-guide.md) |
| 121 | 821–823 | 启用远程构建时，环境变量需要填写 GITHUB_WORKFLOW_TOKEN。默认情况下，启动同步和定时同步只下载 已有 release，不触发 | 迁入专题 | [对应内容](operations-guide.md) |
| 122 | 825–828 |  operations.data_sync on_startup = false  | 迁入专题 | [对应内容](operations-guide.md) |
| 123 | 830–830 | 若希望开机时近似执行一次 /更新数据，可同时设置： | 迁入专题 | [对应内容](operations-guide.md) |
| 124 | 832–836 |  operations.data_sync on_startup = true startup_trigger_remote_build = | 迁入专题 | [对应内容](operations-guide.md) |
| 125 | 838–838 | 开机同步的成功、失败、无需更新状态会追加到“机器人已开启。”通知中。 | 迁入专题 | [对应内容](operations-guide.md) |
| 126 | 840–840 | ## Docker 自更新与重启 | 迁入专题 | [对应内容](operations-guide.md) |
| 127 | 842–847 | 超级管理员发送 /重启机器人、/机器人重启、/更新镜像 或 /更新Docker 会打开 统一维护菜单。选择 1 只重启当前容器或进程，不检查镜像 | 迁入专题；修正过期部分 | [对应内容](operations-guide.md) |
| 128 | 849–849 | 这个能力需要把宿主机 Docker socket 挂进容器： | 迁入专题 | [对应内容](operations-guide.md) |
| 129 | 851–853 |  /var/run/docker.sock - /var/run/docker.sock  | 迁入专题 | [对应内容](operations-guide.md) |
| 130 | 855–855 | TOML 可调整检查时机、容器名、目标镜像和 Watchtower 镜像： | 迁入专题 | [对应内容](operations-guide.md) |
| 131 | 857–865 |  operations.docker_update check_on_startup = true image = "murmansk500 | 迁入专题 | [对应内容](operations-guide.md) |
| 132 | 867–867 | ### 私有扩展包 | 迁入专题 | [对应内容](operations-guide.md) |
| 133 | 869–870 | 公共镜像不包含阵容命令、协议解析、缓存或渲染实现。只有已安装且已验证的私有扩展包才会 注册该功能，并复用主机器人的精灵数据、头像资源和渲染器。 | 迁入专题 | [对应内容](operations-guide.md) |
| 134 | 872–876 | 真实阵容来自可选私有扩展包 murmansk5000/ironsbot-private:latest。它不是机器人 覆盖镜像：Unraid 的  | 迁入专题 | [对应内容](operations-guide.md) |
| 135 | 878–880 | 阵容是第一个扩展；以后可在同一个私有包中增加新的、由公开主程序显式支持的扩展。整个 部署仍只有一个 IronsBot 进程和一个无头米米号登录。 | 迁入专题；修正过期部分 | [对应内容](operations-guide.md) |
| 136 | 882–882 | 在 TOML 中启用私有扩展包： | 迁入专题 | [对应内容](operations-guide.md) |
| 137 | 884–888 |  operations.private_extensions enabled = true image = "murmansk5000/ir | 迁入专题 | [对应内容](operations-guide.md) |
| 138 | 890–890 | 再在 Unraid 容器变量或 .env.prod 中设置 Docker Hub 的最小拉取凭据；不要写进 TOML： | 迁入专题 | [对应内容](operations-guide.md) |
| 139 | 892–895 |  DOCKER_REGISTRY_USERNAME=murmansk5000 DOCKER_REGISTRY_TOKEN=private-ima | 迁入专题 | [对应内容](operations-guide.md) |
| 140 | 897–899 | 私有扩展包在公开主镜像启动前通过已挂载的 Docker socket 拉取，因此 Unraid 的 Repository 不需要改成私有镜像。D | 迁入专题 | [对应内容](operations-guide.md) |
| 141 | 901–904 | 凭据缺失或私有镜像没有安装时，主机器人仍会正常启动，阵容 不会响应。 公共无头账号由 operations.headless.account | 迁入专题 | [对应内容](operations-guide.md) |
| 142 | 906–906 | 如果不想让机器人自然启动时检查镜像，可改为： | 迁入专题 | [对应内容](operations-guide.md) |
| 143 | 908–911 |  operations.docker_update check_on_startup = false  | 迁入专题 | [对应内容](operations-guide.md) |
| 144 | 913–921 | 自然启动检查任务注册在数据同步之前；如果发现新镜像，Watchtower 会重建容器， 本轮启动会被新容器替换。镜像通知会显示当前/最新镜像短号 | 迁入专题；修正过期部分 | [对应内容](operations-guide.md) |
| 145 | 923–925 | 没有挂载 Docker socket 时，镜像检查会被跳过；Windows 源码运行可把启动检查关闭。 新版 Unraid / Docker E | 迁入专题 | [对应内容](operations-guide.md) |
| 146 | 927–930 | 推送通知会按订阅项拆分，例如机器人启动、Docker 镜像检查、启动数据同步、 AI 聊天异常、B站登录、无头赛尔号、精灵渲染崩溃、红包提醒、按 | 迁入专题 | [对应内容](operations-guide.md) |
| 147 | 932–935 | 游戏和别名数据更新成功后，仅向已开启通知的超级管理员私聊发送简短通知， 不向管理群发送。通知显示数据生产方的生成时间（北京时间）；缺少可靠时间时 | 迁入专题 | [对应内容](operations-guide.md) |
| 148 | 937–939 | SeerAPI 模型依赖跟踪 Murmansk-Seer/seerapi 的 main，实际版本由 uv.lock 记录的提交固定。更新时运行  | 迁入专题 | [对应内容](operations-guide.md) |
| 149 | 941–941 | .env、.env.dev、.env.prod 和真实运行数据不应提交到 Git。 | 迁入专题 | [对应内容](operations-guide.md) |
| 150 | 943–943 | ## 鸣谢 | 原地保留 | [对应内容](../README.md#鸣谢) |
| 151 | 945–945 | 本项目独立维护，并感谢以下上游项目、作者与社区贡献者提供的基础、数据工具和参考实现。 | 原地保留 | [对应内容](../README.md#鸣谢) |
| 152 | 947–952 | - Nattsu39https://github.com/Nattsu39 的 IronsBothttps://github.co | 原地保留 | [对应内容](../README.md#鸣谢) |
| 153 | 954–954 | Murmansk-Seer 组织维护的 SeerAPI 数据链会在保留原项目署名与许可证的前提下持续演进。 | 原地保留 | [对应内容](../README.md#鸣谢) |
| 154 | 956–956 | ## 上游更新策略 | 迁入专题；首页保留摘要 | [对应内容](operations-guide.md#上游更新策略) |
| 155 | 958–967 | 本仓库已经是独立维护线，不再直接 merge 或 rebase Nattsu39/IronsBothttps://github.com/N | 迁入专题；首页保留摘要 | [对应内容](operations-guide.md#上游更新策略) |
| 156 | 969–969 | 处理上游更新时按类型选择性吸收： | 迁入专题；首页保留摘要 | [对应内容](operations-guide.md#上游更新策略) |
| 157 | 971–974 | - 小型 bug 修复：手动 port 到当前架构，或在确认冲突范围后单独 cherry-pick。 - 数据和别名更新：进入 SeerAPI  | 迁入专题；首页保留摘要 | [对应内容](operations-guide.md#上游更新策略) |
| 158 | 976–976 | 也就是说，上游现在是参考源和补丁来源，不是可以直接同步的主线。 | 迁入专题；首页保留摘要 | [对应内容](operations-guide.md#上游更新策略) |
| 159 | 978–978 | ## 本地开发 | 迁入专题；首页保留启动命令 | [对应内容](operations-guide.md#本地开发与终端) |
| 160 | 980–984 |  uv sync --group dev uv run python scripts/check_repo.py uv run python - | 迁入专题；首页保留启动命令 | [对应内容](operations-guide.md#本地开发与终端) |
| 161 | 986–986 | 如果 Windows 终端中文显示异常，可以在当前 PowerShell 会话里先执行： | 迁入专题；首页保留启动命令 | [对应内容](operations-guide.md#本地开发与终端) |
| 162 | 988–992 |  $env:PYTHONUTF8 = "1" $env:PYTHONIOENCODING = "utf-8" Console::Output | 迁入专题；首页保留启动命令 | [对应内容](operations-guide.md#本地开发与终端) |
| 163 | 994–994 | 快速只检查配置文件语法和 UTF-8/乱码扫描： | 迁入专题；首页保留启动命令 | [对应内容](operations-guide.md#本地开发与终端) |
| 164 | 996–998 |  uv run python scripts/check_repo.py --static  | 迁入专题；首页保留启动命令 | [对应内容](operations-guide.md#本地开发与终端) |
| 165 | 1000–1000 | ## 许可证 | 原地保留 | [对应内容](../README.md#许可证) |
| 166 | 1002–1002 | 本仓库采用多许可证结构，详见 LICENSING.mdLICENSING.md。 | 原地保留 | [对应内容](../README.md#许可证) |
| 167 | 1004–1005 | - 包含 GPL 插件/代码的完整仓库和 Docker 镜像整体按 GPL-3.0-or-later 分发。 - 可独立复用的自定义插件与工具代 | 原地保留 | [对应内容](../README.md#许可证) |

## 验收方法

核对原段连续覆盖，无未归类段落；检查迁入文本、过期修正和重复合并的独有信息。
校验首页及专题本地链接／锚点、代码围栏、TOML 示例及配置模型；shell 命令只核对现有入口，
不执行登录、迁移、镜像更新或生产操作。本文整理不代表新版本已部署。

本轮验证：167 个来源段落／代码块已登记；9 份相关 Markdown 的本地链接、锚点和围栏检查通过，
17 段 TOML 均通过语法及合并到示例配置后的模型校验，Compose YAML 解析和 git diff --check 通过。
仅文档变更，未重跑完整业务 pytest，也未执行文中部署／迁移命令。
