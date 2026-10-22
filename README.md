<p align="center">
  <img src="icon.png" width="128" alt="IronsBot icon">
</p>

# IronsBot

赛尔号信息查询机器人，支持 **QQ 官方机器人**与 **OneBot v11 / NapCat** 两种接入方式。
提供精灵资料、玩家与榜单查询、B站动态、订阅提醒和可选扩展，支持 Docker、Unraid 和源码运行。

[![Python](https://img.shields.io/badge/Python-%3E%3D3.11-blue)](https://python.org/)
[![License](https://img.shields.io/badge/License-GPL--3.0--or--later-blue)](LICENSING.md)
[![SeerAPI](https://img.shields.io/badge/SeerAPI-Murmansk--Seer-blue)](https://github.com/Murmansk-Seer/seerapi)

> 本项目原作是 [@火火](https://github.com/Yogurt114514) 开发的西塔伦Bot，
> 谨以此项目向 @火火 致敬，感谢他为赛尔号玩家社区所做的贡献，愿火种永存。
>
> 本项目在 [Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot) 基础上独立维护。
> 西塔伦Bot 的配置投稿／推荐服务请参阅外部项目
> [火火手册](https://seerinfo.yuyuqaq.cn/firedict)；本项目的本地配置图查询是另一项功能。

本项目不提供托管服务，需要自行部署。

可选私有扩展采用显式 Python 工厂入口；升级主程序时须使用配对验证过的扩展版本，
旧 NoneBot 私有插件清单不再加载，详见[私有扩展说明](docs/operations-guide.md#私有扩展包)。

进程由应用直接持有 FastAPI/Uvicorn，OneBot 不再通过 NoneBot 驱动运行。
原 `bot.driver` 已移除；监听地址、端口和 OneBot 连接路径不变，见[运行宿主](docs/operations-guide.md#运行宿主)。

## 文档导航

| 内容 | 阅读入口 |
| --- | --- |
| 两种接入与运行环境 | [选择接入方式](#选择接入方式)、[Docker／Unraid／源码](#运行环境) |
| 常用查询、绑定、额度、预热与橱窗 | [玩家查询与绑定指南](docs/player-query-guide.md) |
| AI、B站、战队、会议、定时消息与权限示例 | [配置与订阅指南](docs/configuration-and-subscriptions.md) |
| 身份关联、免 @、按钮、上传和回执 | [QQ 平台接入细节](docs/qq-platform-guide.md) |
| 数据缓存、迁移、同步、重启、扩展及 Windows | [数据与运维指南](docs/operations-guide.md) |
| 固定图、文本匹配、主题推送 | [固定图片](docs/examples/fixed-images.md)、[匹配](docs/text-matching.md)、[主题](docs/push-topics.md) |
| 本次文档整理的逐段去向和过期修正 | [内容迁移核对表](docs/readme-content-map.md) |

## 选择接入方式

| 项目 | QQ 官方机器人 | OneBot / NapCat |
| --- | --- | --- |
| 账号要求 | QQ 开放平台机器人应用、AppID 和 AppSecret | 能登录 NapCat 的 QQ 账号及 OneBot v11 服务 |
| 群聊与私聊 | 官方群消息与 C2C 消息，受应用能力和平台权限限制 | 使用登录 QQ 的群聊与私聊 |
| 主动推送 | 需要本 AppID 下的可信目标地址、主动消息许可及平台额度 | 通过已连接的 OneBot 账号发送 |
| 特有能力 | 官方富媒体、Markdown；自定义按钮需另行开通 | 戳一戳、红包识别、群角色及昵称补查等 |
| 配置入口 | `bot.qq_official` | `bot.onebot`、`bot.onebot.routing` |

先选择下面的一种接入方式，再按[运行环境](#运行环境)启动程序。两种方式共用业务配置，
可用功能还取决于群／用户授权、数据和扩展是否就绪，平台不支持的能力不会模拟实现。

**当前混合部署规则：** 只要 TOML 中声明的官方账号有完整的 `APP_SECRET_<AppID>`，
QQ 官方就成为唯一出站平台，NapCat 不回复业务指令、不主动推送，也不在官方端失败时接管。
NapCat 可继续作为身份辅助采集端，详见[混合模式与身份关联](#混合模式与身份关联)。

## 方式一：QQ 官方机器人

1. 准备 QQ 机器人应用，取得 AppID 和 AppSecret，并按平台要求完成群聊／私聊能力配置。
2. 从 [config.example.toml](config.example.toml) 创建自己的 TOML，合并以下相关表。
   已存在的表应原地修改，不要重复声明；示例中的数字和 OpenID 都是占位值。

```toml
[bot]
superusers = ["owner"]
use_default_for_unconfigured_targets = false

[bot.onebot]
enabled = false
send_messages = false
identity_verification = false

[bot.qq_official]
default_account = "example_bot"

[bot.qq_official.accounts.example_bot]
app_id = "10001"
required = false
proactive_messages = true
custom_keyboards = false

[identities.groups]
group_a = { qq = 987654321, official = { example_bot = "verified-group-openid" } }

[identities.users]
owner = { qq = 1234567890, official = { example_bot = "verified-user-openid" } }

[bot.qq_official.group_routes]
group_a = "example_bot"

[bot.qq_official.private_routes]
owner = "example_bot"

[features.group_policy]
group_a = ["seer", "bili_query"]

[features.user_policy]
owner = ["all", "admin_notice"]
```

3. 在进程或容器环境中设置 `APP_SECRET_10001`，值为该应用的真实 AppSecret。
   Secret 不写入 TOML；没有完整凭据的账号不会被激活。不要为未声明的 AppID 设置 Secret。
4. 按下面的 Docker、Unraid 或源码方式启动，核对账号连接状态，再在群中 `@机器人 帮助`
   或私聊发送 `帮助`。

OpenID 必须来自对应 AppID 的可信记录，不能填写 QQ 号或复制其他应用的 OpenID。
尚未取得地址时不要照抄占位符，可先仅声明 QQ 身份，按下一节配置辅助关联；
取得并核实地址后再补入对应端点。

`group_routes` 指定群的服务机器人，`private_routes` 指定用户的主动私聊推送机器人。
普通私聊查询仍由收到消息的账号回复。默认路由开关关闭时，未分配目标不会自动使用默认账号；
显式选定账号不可用时也不改用其他账号。若群只有一个已激活官方账号端点，可自动确定归属；
多个端点时应显式指定。多账号部署必须明确 `default_account`。

官方主动推送还受腾讯的目标许可、交互和频率限制，配置 `proactive_messages = true`
不代表平台保证送达。`custom_keyboards` 只在应用已获相应能力时开启，文字菜单始终可用。

## 方式二：OneBot / NapCat

1. 部署 [NapCat](https://github.com/NapNeko/NapCatQQ) 并登录自己的 QQ。
2. 在 IronsBot TOML 中合并以下配置；不配置完整的官方账号凭据。

```toml
[bot]
superusers = ["owner"]
use_default_for_unconfigured_targets = false

[bot.onebot]
enabled = true
send_messages = true
identity_verification = false

[identities.groups]
group_a = { qq = 987654321 }

[identities.users]
owner = { qq = 1234567890 }

[bot.onebot.routing]
enabled = true
default_bot = "main_bot"

[bot.onebot.routing.bot_aliases]
main_bot = 111111111

[bot.onebot.routing.groups]
group_a = "main_bot"

[bot.onebot.routing.users]
owner = "main_bot"

[features.group_policy]
group_a = ["seer", "bili_query"]

[features.user_policy]
owner = ["all", "admin_notice"]
```

`main_bot` 填写 NapCat 实际登录的 QQ 号。多账号可增加机器人别名和目标路由；
选定账号离线时不会回退至其他账号。未指定目标仅在
`bot.use_default_for_unconfigured_targets = true` 时尝试 `default_bot`。

3. 设置 IronsBot 环境变量 `ONEBOT_ACCESS_TOKEN`，在 NapCat 配置相同令牌及反向 WebSocket：

```text
ws://IRONSBOT_HOST:8085/onebot/v11/ws
```

同一 Docker 网络中可使用 `ws://ironsbot:8080/onebot/v11/ws`。
这里 `8085` 是下面示例映射的主机端口，`8080` 是容器内端口。
启动后确认 OneBot 已连接，在已配置群或已授权私聊中发送 `帮助`。

OneBot 接入参数统一在 `[bot.onebot]`：`ws_urls` 为正向 WS 地址，`api_roots`
为数字机器人账号对应的 HTTP API 地址，`api_timeout` 默认 30 秒，`nicknames`
默认留空。只使用反向 WS 时无须填写前两个字段。HTTP 上报签名使用加密环境变量
`ONEBOT_SECRET`，不写 TOML；既有 `ONEBOT_ACCESS_TOKEN` 名称不变。
可选部署覆盖仍使用 `ONEBOT_WS_URLS`、`ONEBOT_API_ROOTS`、`API_TIMEOUT`、`NICKNAME`，
其中数组和字典必须为 JSON。不再读取 SDK 的 `ONEBOT_V11_*` 别名，发现非空旧变量会
明确报错，避免误以为已启用鉴权。完整示例见 [.env.example](.env.example)。

### 混合模式与身份关联

官方机器人服务业务、NapCat 只做身份辅助时，保留完整官方凭据，并配置：

```toml
[bot.onebot]
enabled = true
send_messages = false
identity_verification = true

[bot.onebot.trusted_official_bots]
example_bot = 222222222
```

可信名单的键应对应已声明官方账号，值是 NapCat 看到的该官方机器人的 QQ 号。
保留 OneBot 连接与 Token，预先在 `identities.groups` 声明待核对群的 QQ 号。
系统使用两端可核对的消息、提及和引用关联群及成员身份，存在歧义或冲突时不猜测覆盖。
不要按昵称或跨 AppID 复制地址。关联成功不自动授予业务权限。
身份与迁移细节见[多平台说明](docs/multiplatform-refactor.md)。

OneBot 自发指令可选开启 `[bot.onebot.self_commands]`，并在 NapCat 开启 `reportSelfMessage`：

```toml
[bot.onebot.self_commands]
enabled = true
prefixes = ["演示 ", "示范 "]
```

登录 QQ 本人可发送 `演示 帮助`、`演示 1`、`演示 0`，沿用该 QQ 已有权限。
官方接管或 OneBot 发送关闭时仍保持业务静默，身份辅助观察独立于该开关。
自发指令同样受公共消息 ID 判重和权限控制；失败后需发送新消息重试。
出站口令和代绑文本的回声会被拦截，不会因机器人自己的回复再次执行业务。

自发指令接受范围、旧字段迁移及官方“接收所有消息”下的免 @ 行为，见
[平台接入细节](docs/qq-platform-guide.md)。

## 运行环境

### Docker Compose

创建 `ironsbot-config/ironsbot.toml`，以完整示例为基础配置所选接入方式。
以下仅启动 IronsBot；选择 NapCat 时需另外部署并登录 OneBot 服务。

```yaml
services:
  ironsbot:
    image: murmansk5000/ironsbot:latest
    container_name: ironsbot
    ports:
      - "8085:8080"
    volumes:
      - ./ironsbot-config:/config
      - ./ironsbot-data:/app/data
      - ./ironsbot-logs:/app/logs
      # 仅使用容器自更新或私有扩展包加载时按需挂载：
      # - /var/run/docker.sock:/var/run/docker.sock
    environment:
      APP_CONFIG_PATH: /config/ironsbot.toml
      # 官方方式：取消下一行注释，并在主机 .env 中提供真实 Secret。
      # APP_SECRET_10001: ${APP_SECRET_10001:?set APP_SECRET_10001}
      # NapCat 或混合模式：取消下一行注释，在主机 .env 中提供相同 Token。
      # ONEBOT_ACCESS_TOKEN: ${ONEBOT_ACCESS_TOKEN:?set ONEBOT_ACCESS_TOKEN}
    restart: unless-stopped
```

```bash
docker compose up -d
docker compose logs --tail=100 -f ironsbot
```

挂载目录必须对容器可读写。不要把 `.env`、真实 TOML、数据库或密钥提交到 Git。
环境变量及额外部署示例见 [.env.example](.env.example) 和 [Docker 说明](docker/README.md)。

### Unraid

在 Community Applications 搜索 `ironsbot`，或使用自己的容器模板，设置：

| 项目 | 示例 |
| --- | --- |
| Repository | `murmansk5000/ironsbot:latest` |
| 端口 | 主机 `8085` → 容器 `8080/TCP` |
| 配置 | `/mnt/user/appdata/ironsbot/config` → `/config` |
| 数据 | `/mnt/user/appdata/ironsbot/data` → `/app/data` |
| 日志 | `/mnt/user/appdata/ironsbot/logs` → `/app/logs` |
| 配置路径变量 | `APP_CONFIG_PATH=/config/ironsbot.toml` |
| 接入凭据 | 官方设置 `APP_SECRET_<AppID>`；NapCat 设置 `ONEBOT_ACCESS_TOKEN` |

混合模式需要两类凭据。按需挂载 `/var/run/docker.sock`，用于容器更新或私有扩展加载。
配置目录中的 TOML 与 Compose 部署相同；修改容器环境变量后需重建容器。

### 源码运行与本地开发

需要 Python 3.11 或更高版本（低于 4.0）及 [uv](https://docs.astral.sh/uv/)。
从示例建立 `config/ironsbot.toml`，在本机 `.env` 或进程环境中设置
`APP_CONFIG_PATH=config/ironsbot.toml` 及所选接入凭据，然后执行：

```bash
uv sync --group dev --extra qq-official
uv run python -m ironsbot
```

只使用 OneBot 时可以省略 `--extra qq-official`。本地变量加载优先级为
进程环境 > `.env.<ENVIRONMENT>` > `.env`，默认 `ENVIRONMENT=prod`。
Linux 容器还包含图片渲染所需依赖，源码环境需自行满足对应渲染依赖。

开发检查：

```bash
uv run python scripts/check_repo.py --static
uv run python scripts/check_repo.py
```

Windows 中文终端、启动 env 加载和纯 OneBot 镜像构建说明见
[源码与终端](docs/operations-guide.md#本地开发与终端)、[平台运行组件](docs/qq-platform-guide.md)。

## 功能与权限

主要功能包括玩家绑定、收集与巅峰、全服／样本榜、玄武榜、精灵／皮肤／技能／魂印、
刻印与装备、群星牌、巅峰池与投票、预告和新增内容、开服查询、战队订阅、幸运橱窗、
B站动态、定时文本／图片、会议回复及 AI。部分能力需要无头游戏账号、远程数据或私有扩展。

发送 `帮助` 查看当前会话实际可用功能。子菜单 `0` 返回上级，顶层 `0` 退出；
引用有效菜单可按实际操作者权限建立独立会话。包含 `@全体成员` 的消息不触发命令。
命令、菜单及两端公共业务的验收情况见[入口核对清单](docs/onebot-menu-parity.md)。

- 群聊按 `features.group_policy` 授权，私聊按 `features.user_policy` 授权；机器人账号不授予业务功能。
- `identities.groups` 中已声明且未拉黑的群默认具有 `help`、`about`，其他功能需明确配置。
- `bot.superusers` 是管理身份，`all` 是功能组合。`features.superuser_bypass = true`
  允许超管主动使用功能时绕过功能限制，但不绕过黑名单、目标安全限制或平台能力。
- 管理通知须显式授予 `admin_notice`，`all` 和超管身份均不自动产生通知资格或业务订阅。
- 私聊 `TD` 管理本人当前发送路由的推送；群主／管理员在群里发送 `TD` 管理群订阅。
  `推送时间` 只调整支持修改时间的任务。

### 常用赛尔查询

图片素材获取失败时，管理员通知会汇总失败资源，并在可用时标明实际执行账号；显示名仅用于诊断，不作为权限身份。


| 示例 | 用途 |
| --- | --- |
| `米米号123456`、`米米号示例账号` | 按数字或可见名称／别名查询玩家 |
| `绑定米米号123456`、`解绑米米号` | 设置或解除默认查询目标，不验证游戏账号所有权 |
| `收集`、`巅峰`、`群星牌` | 已绑定用户的默认目标查询；也可追加数字或可见别名 |
| `米米号 @成员` | 查询被提及成员绑定的目标，仍受访问开关限制 |
| `成就榜123456`、`成就榜200名`、`成就榜50-100` | 分别定位玩家、查名次、查范围；纯数字不当作名次 |
| `玄武榜`、`玄武榜2-1`、`玄武榜2-2` | 默认范围、反向范围及单名次范围 |
| `群星牌地葬`、`群星牌卡98` | 查询卡牌资料；不同于玩家的群星牌排名 |
| `雷伊配置`、`配置雷伊`、`4923配置` | 发送本地配置图，需 `pet_config` 授权及对应素材 |
| `橱窗`、`橱窗示例账号` | 查缓存或按本人资格确认登录，不能借查询获取他人登录权限 |
| `动态`、`战队订阅`、`TD` | 动态历史、当前战队订阅及推送设置 |

未绑定者的独立查询需先回答绑定建议，`是/y` 确认、`否/n` 跳过；查询详情不代表绑定已成功。
各类来源权限、冷却、样本、默认额度及配置图目录详见
[查询与绑定指南](docs/player-query-guide.md)。无候选静默及匹配规则见[文本匹配](docs/text-matching.md)。

### Feature 对照表

| feature | 作用 |
| --- | --- |
| `all` | 常用业务功能组合；不含 `admin_notice`、`blacklist`、官方身份管理等受保护项。 |
| `query` | 常用查询组合：赛尔查询、精灵配置图、图片、榜单、B站查询、活动查询、开服查询。 |
| `seer` | 全部赛尔查询子功能总开关。 |
| `seer_player` | 米米号绑定、玩家基础信息及收集/巅峰/群星牌快捷查询。 |
| `lucky_skin_window` | 查询每日四个皮肤；已有公共缓存可供其他用户查看，无缓存时仅 TOML 授权且绑定一致的本人或超级管理员可登录。超级管理员也只能代查幸运橱窗授权表中的账号；TD 可退订每日提醒。 |
| `player_lineup_private` | 查询公开阵容；群聊和私聊都使用这个独立权限。 |
| `seer_team` | 战队 ID 查询。 |
| `seer_pet` | 精灵、技能、魂印、立绘、皮肤查询。 |
| `pet_config` | 本地精灵配置图查询；独立于 `seer` 功能包，图片文件名使用精灵序号。 |
| `pet_flip` | 抛精灵：提及两名不同群成员，随机分配精灵并按属性倍率比较。 |
| `push_topics` | 通用主题推送管理和订阅；开启功能不会自动订阅。 |
| `seer_mintmark` | 刻印、刻印系列、宝石、刻印数值榜。 |
| `seer_equipment` | 套装、部件、称号查询。 |
| `seer_type` | 属性克制、异常状态查询。 |
| `seer_peak` | 巅峰池、票选、巅峰榜、精灵／套装／称号统计。 |
| `seer_autocard` | 群星牌资料和群星之巅榜。 |
| `seer_rank` | 全服榜、样本榜、榜单情况、样本情况、缓存/刷新榜单。 |
| `seer_data` | 下周预告、新增成就、数据版本等数据工具。 |
| `image` | TOML 配置的本地/CNB 单图与编号图库发送。 |
| `meeting` | 腾讯会议回复。 |
| `text` | 通用文本口令回复。 |
| `text_push` | 通用定时文本推送。 |
| `web_activity_link` | 游戏外活动链接口令，例如签到/活动/链接。 |
| `web_activity_push` | 游戏外活动链接定时推送。 |
| `seerinfo` | seerinfo/火火手册等自定义文本入口。 |
| `bili_query` | B站动态手动查询、刷新、历史点播。 |
| `bili_push` | B站动态自动推送；TD 菜单会按 B站 UID 拆分退订项。 |
| `bili` | `bili_query` + `bili_push`。 |
| `seer_activity_query` | 游戏内快结束活动手动查询；`/当前活动` 为超级管理员专用。 |
| `seer_activity_push` | 游戏内活动结束提醒推送。 |
| `seer_activity` | `seer_activity_query` + `seer_activity_push`。 |
| `server_status_query` | 开服查询、服务器状态查询。 |
| `server_status` | `server_status_query`。 |
| `team_resource_subscription` | 战队资源订阅：群内 `战队` 查询订阅战队，低资源定时 @ 提醒。 |
| `team_audit` | 战队审核群入群提示和 24 小时 follow-up。 |
| `ai_chat` | @ 机器人或私聊触发 AI 聊天。 |
| `ai_intent` | AI 意图分析总开关；具体动作还需要对应 feature。 |
| `ai_intent_team_recommend` | AI 判定用户想加入战队后发送战队推荐/审核群信息。 |
| `fire_manual_ad` | 主动推送末尾追加火火手册链接。 |
| `ai_intent_fire_manual` | 用户明确索要火火手册链接时的 AI 意图动作。 |
| `admin_notice` | 管理通知目标权限；启动、AI异常、B站登录、无头赛尔号、渲染崩溃、红包提醒等具体推送可在 TD 菜单中单独退订。 |
| `blacklist` | 用户或群完全静默，超级管理员也不绕过。 |

## 指定用户提及回复

`[[messaging.mention_replies]]` 为指定身份配置群内提及机器人的回复序列。`id` 为必填规则标识，`name` 为可选名称，`enabled` 默认为 `true`。`users` 引用 `[identities.users]` 中的用户别名，启用时不能为空；不是直接填写平台账号。匹配使用已有身份绑定与 principal 解析，不新增身份关联或权限。

仅在群消息提及机器人、且未被消息黑名单阻止时匹配；普通命令和进行中的交互优先，提及回复在 AI 聊天之前处理。按配置顺序使用首个启用且匹配的规则，`messages` 为至少一条非空文本，按顺序逐条发送。私聊或其他用户的提及不会触发该回复。

## 配置入口

以 [config.example.toml](config.example.toml) 为完整字段参考，按[配置布局](docs/configuration-layout.md)
组织配置。README 中的片段只演示相关表，不能替代完整配置文件。

| 配置 | 用途 |
| --- | --- |
| `identities.groups` / `identities.users` | 集中声明逻辑群／用户及可信平台端点 |
| `features.bundles` / `group_policy` / `user_policy` | 功能组合、群授权、用户授权 |
| `bot.qq_official` / `bot.onebot` | 机器人接入及账号配置 |
| `bilibili` / `messaging` | 动态、文本、图片、定时任务及投递行为 |
| `seer.player.binding` | 未绑定查询、超管账号快捷访问及换绑冷却 |
| `seer.player_accounts` / `operations.headless` | 游戏账号库及公共无头查询池 |
| `seer.lucky_skin_window` | 橱窗账号、查询和提醒时间 |
| `ai` | 提供商、模型顺序及聊天行为 |
| `operations` / `paths` | 数据同步、容器更新、扩展、路径及运维配置 |

密钥使用 [.env.example](.env.example) 中的专用变量：官方 `APP_SECRET_<AppID>`、
OneBot `ONEBOT_ACCESS_TOKEN`、AI `AI_KEY_<提供商别名大写>`、游戏 `SEER_PASSWORD_<米米号>`。
游戏密码配置为明文环境变量，登录 MD5 在内存中计算。行为配置放 TOML，真实凭据不放文档或 Git。
已知字段的类型、取值和引用错误会阻止启动；未知或已删除字段记录告警后忽略，不代表继续兼容。

修改配置后可先离线校验，不建立机器人连接或启动业务调度：

```bash
python -m ironsbot.config_check --config /config/ironsbot.toml --no-dotenv
```

源码环境可用 `uv run python`；需要正常加载本机 `.env` 时省略 `--no-dotenv`。
完整环境覆盖项、TOML 权限组合、AI／会议／定时消息示例及投递诊断见
[配置与订阅指南](docs/configuration-and-subscriptions.md)。

专题说明：[文本匹配](docs/text-matching.md)、[重复指令分类](docs/command-duplicate-categories.md)、
[固定图片](docs/examples/fixed-images.md)、[通用主题推送](docs/push-topics.md)。


### 按榜单设置玩家排名查询范围

`[seer.rank]` 的 `lookup_limits` 是按榜单名称设置的玩家排名查询范围映射，默认 `{}`。
合法键为：图鉴积分、成就点数、精灵图鉴、皮肤图鉴、套装图鉴、部件图鉴、座驾图鉴、刻印图鉴、群星牌、竞技段位、狂野段位、专家段位、大师段位；使用这些规范名称，不使用榜单标题或别名。值为非负整数，未知键或负数会被拒绝。
未单独设置的榜单，在已有正分数的排名查找中使用 `limit`（默认 10000），否则使用 `online_limit`（默认 2000）；已设置的榜单使用自己的值覆盖对应默认范围。调用方显式请求更小范围时仍取较小值。
`0` 将该榜的查找范围上限设为零，不是无限制。它不是功能开关；缓存及结果核验另有路径，不能据此保证零网络请求。
例如，在现有 `[seer.rank]` 表内添加 `lookup_limits = { "群星牌" = 10000 }`，只为群星牌设置范围；不添加该行则保持默认空映射。
此项不设置全服榜展示行数，不调整后台 `page_refresh` 预热范围，也不改变群开关或权限。全服榜展示行数仍由 `display_limit`、`display_limits`、`max_display_limit` 等展示配置控制。

## 更新维护

公开镜像提供 Docker Hub 与 GHCR 两个仓库：

```text
docker.io/murmansk5000/ironsbot:latest
ghcr.io/murmansk5000/ironsbot:latest
```

`latest` 对应主线构建，`sha-xxxxxxx` 用于定位具体提交；同时发布项目版本标签。
Compose 可执行 `docker compose pull ironsbot` 后重新 `docker compose up -d`，
Unraid 可使用容器更新入口。机器人内 `/更新镜像` 等维护命令仅限超级管理员，
并需要 Docker socket 及相应运维配置。

配置变更通常需要重启；新增／修改容器环境变量需要重建。升级前检查配置与扩展契约，
不要让旧版本读取只由新版本支持的配置。部署验证与残留清理规则见
[部署监督说明](docs/specs/2026-10-08-docker-verified-deployment.md)，仅清理确认属于本项目的资源。

数据同步使用 `/同步数据`，`/更新数据` 为别名；实时游戏查询依赖无头账号，
静态资料依赖已发布 SeerAPI 数据，两者不互相替代。数据、偏好和业务缓存应持久挂载，
不要在更新镜像时清空数据目录。

同步选项、远程构建流水线、启动同步开关、数据目录及更新通知见
[数据与运维指南](docs/operations-guide.md)。

### 消息重放与重试

OneBot 与 QQ 官方命令共用消息 ID 防重放账本，按平台、机器人账号、群聊/私聊和会话隔离，保留 24 小时。它不是业务成功记录：同一条消息的网关重放不会重做绑定、订阅或查询；业务或投递失败后，可发送一条新消息重试，仍遵守权限、冷却和额度。

账本沿用 `cache_root/qq_official/inbound.sqlite`，升级时自动迁移旧官方记录，不需要新增 TOML/env 字段。请随缓存目录持久化；删除该文件会丢失近期防重放记录。数据库故障时停止处理并告警，不回退到内存或盲目重发；不承诺跨崩溃 exactly-once。

### 状态库迁移

从旧版升级时，按[状态库迁移说明](docs/platform-state-migration.md)停机操作并先执行 dry-run；
不要手工拼接或搬移 SQLite 表。本文更新本身不要求迁移数据库。

### 上游更新策略

本项目独立维护，选择性吸收 [Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot)
的修复与能力，不直接整体 merge 或 rebase。上游检查工作流每天北京时间 12:00 巡检，
发现未跟进提交时通过 GitHub Issue 报告；不自动覆盖现有架构或部署。

SeerAPI 模型依赖跟踪本项目维护分支，实际提交固定在 `uv.lock`。
依赖更新必须经过测试，运行容器不会在启动时自行升级 Python 依赖。

## 扩展开发

内置功能通过插件贡献及公共命令契约注册。自有扩展使用公共扩展动作和窄接口，
复用目标解析、权限、菜单、查询额度和投递；平台事件和发送协议留在适配器。
任务调度由应用直接持有 APScheduler，不依赖 NoneBot 调度插件或全局实例。
服务注册完成后才启动调度；关闭时先等待运行中作业退出，再释放业务资源。
当前架构及验收边界见[入口核对清单](docs/onebot-menu-parity.md)、
[工程约定](docs/engineering-workflow.md)。不要将尚未完成的统一入口改造视为已发布能力。

### 私有扩展包

私有阵容等可选能力从扩展包镜像加载，主机器人镜像仍使用公开仓库：

```toml
[operations.private_extensions]
enabled = true
image = "murmansk5000/ironsbot-private:latest"
```

加载私有包需要 Docker socket，以及 `DOCKER_REGISTRY_USERNAME`、`DOCKER_REGISTRY_TOKEN`
拉取凭据。扩展复用主进程、数据与无头账号池，不另启机器人服务。
没有可用扩展包时，相应命令不会注册；主程序仍可运行。已有包的更新失败沿用安装器的保留规则。
扩展必须与公共程序版本契约匹配，源码分支通过测试不等于已发布镜像兼容。

私有包缓存保留、公共无头账号池、详细阵容契约和版本配对见
[扩展与运维](docs/operations-guide.md#扩展动作与详细阵容)；
工程架构要求见 [ARCHITECTURE.md](ARCHITECTURE.md)，当前验收状态以入口清单为准。

## 鸣谢

- [Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot)：上游项目，提供查询、渲染及协议基础。
- [@火火 / Yogurt114514](https://github.com/Yogurt114514) 的西塔伦Bot：项目早期来源与社区贡献。
- [SeerAPI](https://github.com/SeerAPI/seerapi)：数据模型、构建工具及数据生态。
- [HurryWang / WhY15w](https://github.com/WhY15w) 的
  [Unity 配置解析](https://github.com/WhY15w/seer-unity-config-parser)及
  [预告图片导出](https://github.com/WhY15w/seer-unity-preview-img-dumper)：解析与资源提取参考。
- [SeerRadar/Sequ](https://github.com/SeerRadar/Sequ)：部分赛尔号数据参考。
- [oldml/saixiaoxi](https://github.com/oldml/saixiaoxi)：无头登录 session 获取与登录数据包构建参考。

本项目维护的 [Murmansk-Seer](https://github.com/Murmansk-Seer) 数据项目继续保留原作者署名和许可证。

## 许可证

完整仓库及 Docker 镜像按 **GPL-3.0-or-later** 分发；可独立复用部分按文件 SPDX 标识执行。
完整授权范围、第三方来源和字体许可见 [LICENSING.md](LICENSING.md)。

### 新功能推荐日期

戳一戳推荐按功能首次可用时间增加新功能权重，修复、改名、搬目录或重新注册不算新功能。
`docs/command-first-use.json` 保存经过行为核对的新增日期；构建脚本只为当前注册的命令生成运行清单，
不依赖私有归档或本机旧 Git 对象。基线已有功能不重复促销；配置图片口令不作为新增功能。
新增功能时同步维护该记录、帮助与 README；生成文件不能替代或覆盖来源记录。

## 大师个人巅峰数据

玩家“巅峰”详情与快捷查询共用四模式个人统计：当前段位、历史最高、场次、胜率及赛季排名。
大师个人字段采用 `408302`、`408303`、`408306`、`408307`；不使用奖励进度作为胜场，
也不把赛季最高显示为历史最高。零场次不计算胜率，缺失或异常计数不补零、不写入胜率样本。
四模式数据均完整有效时才采集巅峰总场次；排行榜失败不覆盖已经取得的个人资料。
