<p align="center">
  <img src="icon.png" width="128" alt="IronsBot icon">
</p>

# IronsBot

IronsBot 是一个面向 QQ / OneBot v11 的赛尔号机器人，基于 NoneBot2 构建，主要服务于自部署、Unraid 和 Docker 使用场景。

当前主线已经转为显式插件架构：通用功能位于 `ironsbot/plugins`，部署者自行维护的扩展位于 `ironsbot/custom_plugins`；二者都由统一注册表安装。原版查询代码仅作为数据、渲染和协议能力的来源或基础设施依赖保留。

## 功能

- 米米号查询与 QQ 用户绑定：首次成功查询可设置默认米米号，之后可直接查询米米号、收集、巅峰和群星牌。
- 战队资源订阅：群内发送“战队”查询订阅战队，低资源时定时 @ 提醒。
- 精灵、技能、魂印、皮肤、刻印、套装、部件、称号、属性、异常状态查询，以及本地精灵配置图查询。
- 全服榜、样本榜、巅峰榜、刻印数值榜与缓存状态查询。
- 群星牌公开资料查询。
- B站动态监控与历史动态点播，支持按账号退订、按账号设置全文/链接推送。
- 超级管理员当前活动查询、快结束活动查询和活动结束提醒。
- 固定图片、固定文本、会议回复、通用指令回复和定时消息。
- AI 聊天与 AI 意图动作。
- 无头赛尔号登录状态检查、重连、启动通知和管理员开服查询。
- Unraid Community Applications 模板与 Docker 镜像。

## 镜像

```text
docker.io/murmansk5000/ironsbot:latest
ghcr.io/murmansk5000/ironsbot:latest
```

`latest` 指向 `main` 的最新构建。构建还会发布精确版本 tag：

- `<base-version>.<revision>`：例如 `0.6.0.3`
- `sha-xxxxxxx`：精确到 Git commit

## 快速部署

### Unraid

在 Community Applications 中搜索 `ironsbot` 并安装，至少确认：

- `Repository`: `murmansk5000/ironsbot:latest`
- `WebSocket Port`: `8085`
- `IronsBot Config`: `/mnt/user/appdata/ironsbot/config` -> `/config`
- `IronsBot Data`: `/mnt/user/appdata/ironsbot/data` -> `/app/data`
- `IronsBot Logs`: `/mnt/user/appdata/ironsbot/logs` -> `/app/logs`
- `Docker Socket`: `/var/run/docker.sock` -> `/var/run/docker.sock`，用于镜像检查、容器重启和自更新
- `ONEBOT_ACCESS_TOKEN`: 与 NapCat 反向 WebSocket token 一致
- `[bot].superusers`: 在 `/config/ironsbot.toml` 中填写超级管理员 QQ 列表

NapCat 反向 WebSocket：

```text
ws://UNRAID_SERVER_IP:8085/onebot/v11/ws
```

如果 NapCat 和 IronsBot 在同一个 Docker 自定义网络里，也可以使用：

```text
ws://ironsbot:8080/onebot/v11/ws
```

多个 QQ 机器人可以分别运行 NapCat，并把每个 NapCat 的 OneBot v11 反向
WebSocket 都连接到同一个 IronsBot 地址。普通查询由收到事件的机器人回复；
B站、活动、定时消息、开服与管理通知等主动推送可以按群或用户选择发送机器人：

```toml
[messaging.bot_routing]
enabled = true
default_bot = "main_bot"

[messaging.bot_routing.bot_aliases]
main_bot = 111111111
backup_bot = 222222222

[messaging.bot_routing.groups]
group_a = "main_bot"
group_b = "backup_bot"

[messaging.bot_routing.users]
owner = "main_bot"
user_a = "backup_bot"
```

`group_a/group_b` 和 `owner/user_a` 分别引用 `[features.group_aliases]`、
`[features.user_aliases]`；也可以直接写群号或 QQ 号。目标机器人未连接时会先回退
到 `default_bot`，再回退到任意在线 OneBot 机器人，并记录 warning。第一版只控制
主动发送，不过滤接收事件；同一个群放入多个机器人时，它们仍可能同时收到并响应。

### Docker Compose

```yaml
services:
  ironsbot:
    image: murmansk5000/ironsbot:latest
    container_name: ironsbot
    ports:
      - "8085:8080"
    volumes:
      - ./ironsbot-data:/app/data
      - ./ironsbot-config:/config
      - ./ironsbot-logs:/app/logs
      # 可选但推荐：默认会检查镜像；挂载后 /重启机器人 和 /更新镜像 可重启/更新容器。
      # - /var/run/docker.sock:/var/run/docker.sock
    environment:
      APP_CONFIG_PATH: "/config/ironsbot.toml"
      ONEBOT_ACCESS_TOKEN: "change-me"
    restart: always
```

启动前先根据 [config.example.toml](config.example.toml) 创建
`./ironsbot-config/ironsbot.toml`。配置文件会在启动时严格校验。
完整部署说明见
[docker/README.md](docker/README.md) 和 [.env.example](.env.example)。

## 常用赛尔查询

- 首次发送 `米米号123456` 并成功查到玩家后，按提示回复 `是`/`y` 或 `否`/`n`；完成选择后才会发送玩家详情。
- 首次成功查询米米号后，按提示回复 `是`/`y` 可设为默认米米号；发送 `解绑米米号` 可解除绑定。绑定是快捷查询设置，不验证游戏账号所有权。
- 查询指定米米号后，回复数字 `1`、`2`、`3`、`4` 查看收集、巅峰、群星牌和阵容，回复 `0` 退出；已绑定用户可直接发送 `米米号`、`收集`、`巅峰`、`群星牌`、`阵容`。
- `米米号` 默认只读取基础资料；收集、巅峰、群星牌和阵容只会在用户明确发送对应口令时再请求。`[seer.player.background_refresh]` 默认关闭，按需开启后才会预热扩展数据。
- `雷伊配置`、`配置雷伊` 或 `4923配置` 会按精灵名称、别名或序号发送本地配置图；将图片命名为 `data/pet_configs/<精灵序号>.png` 即可收录。该目录不存在时会在启动时自动创建。
- `群星牌地葬` 按名称查询卡牌，`群星牌卡98` 按卡牌 ID 查询；玩家群星牌排名通过米米号详情菜单或已绑定用户发送 `群星牌` 查询。
- 全服榜后面的纯数字统一按米米号处理，例如 `成就榜123456`。名次必须写 `成就榜200名`，分数必须写 `成就榜5000点`；页码和范围仍可写 `第2页`、`50-100`。
- 自定义刻印系列维护在 `tables_custom/mintmark_series_members.csv`。当前支持 `刻印十年`、`十年01`、`刻印V10`、`V10物速`；同步并构建 alias SQLite 后生效。
- `[seer.mintmark].merge_connected = true` 会把关联刻印合并并显示全部 ID；设为 `false` 会保留原始记录并标注关联 ID，适合排查上游数据。

## 插件架构

通用用户功能位于 `ironsbot/plugins`，部署者自行维护的扩展位于
`ironsbot/custom_plugins`。仓库不会扫描目录或维护平行 manifest；`python -m
ironsbot` 通过 `ironsbot/app/bootstrap.py` 启动，并按
`ironsbot/app/registry.py` 中唯一的 `PluginDefinition` 注册表安装命令入口、
外部依赖和生命周期钩子。

- 赛尔查询：玩家、战队、精灵、刻印、装备、属性、巅峰、群星牌和榜单。
- 消息与内容：固定文本、定时消息、固定图片、腾讯会议和帮助。
- 推送：B站动态、游戏活动、开服状态和战队资源。
- AI：聊天、提及保护、意图识别和模板动作。
- 运维：数据同步、无头登录、启动通知、定时重启和 Docker 更新。

## 配置方式

行为与部署配置都写在 TOML 文件里，并通过 `APP_CONFIG_PATH` 指向它。环境变量只保留：

- 配置位置：`APP_CONFIG_PATH`
- 密钥：`ONEBOT_ACCESS_TOKEN`、`AI_KEY`、`HEADLESS_SEER_USER_ID`、
  `HEADLESS_SEER_PASSWORD`、`SENDPIC_CNB_TOKEN`、`GITHUB_WORKFLOW_TOKEN`

示例环境变量：

```env
APP_CONFIG_PATH=/config/ironsbot.toml
ONEBOT_ACCESS_TOKEN=change-me
AI_KEY=
HEADLESS_SEER_USER_ID=
HEADLESS_SEER_PASSWORD=
SENDPIC_CNB_TOKEN=
GITHUB_WORKFLOW_TOKEN=
```

`APP_CONFIG_PATH` 是容器内路径。Docker/Unraid 常用值是 `/config/ironsbot.toml`；
宿主机上的真实位置取决于你把哪个目录挂载到了 `/config`。例如 Windows Docker
Desktop 可以把任意可写目录挂载到 `/config`：

```text
<你的 Windows 配置目录>\ironsbot.toml -> /config/ironsbot.toml
```

该文件必须在启动前存在，可直接以 [config.example.toml](config.example.toml) 为模板。
程序只读并严格校验配置，不会修改磁盘上的 TOML。真实 env 文件包含密钥，不纳入仓库；
使用 Docker Compose 时可参考 [.env.example](.env.example) 手动创建。

如果没有设置 `APP_CONFIG_PATH`，IronsBot 会默认读取当前工作目录的
`config/ironsbot.toml`；文件不存在会立即报错。日志默认写入当前工作目录的 `logs/`，
运行数据默认写入 `data/`。Docker/Unraid 推荐额外挂载
`/app/logs`，启用文件日志后完整日志和错误日志都能在宿主机上直接查看。
默认按本地时间每天 `00:00` 轮转，保留 30 天且不压缩；可在 `[bot.logging]` 按磁盘空间调整。

示例 TOML：

```toml
[features]
superuser_bypass = true

[features.group_aliases]
admin = 123456789
example = 987654321

[features.user_aliases]
owner = 1234567890

[features.bundles]
standard = ["seer", "player_lineup_private", "image", "seerinfo_link", "bili_query", "bili_push", "seer_activity_query", "seer_activity_push", "server_status_query", "ai_intent"]
lite = ["seer_pet", "seer_player", "player_lineup_private", "seer_team", "seer_equipment", "seer_type", "seer_peak", "seer_autocard", "seer_rank", "seer_data"]

[features.group_policy]
admin = ["admin_notice"]
example = ["standard", "meeting", "team_resource_subscription"]

[features.user_policy]
owner = ["all"]

[[messaging.commands]]
id = "seerinfo_page"
commands = ["xm", "xrym", "雷小伊", "重聚"]
message = "https://seerinfo.yuyuqaq.cn/"
feature = "seerinfo_link"

[bilibili.accounts.seer]
uid = 1310714247

[bilibili.push]
accounts = ["seer"]
mode = "link"
modes = { seer = "full" }

[bilibili.push.groups.example]
accounts = []
mode = "link"

# 群主/管理员可在群里发送：
# B站账号
# B站推送模式 seer 链接
# 也可使用 B站公开昵称或 UID；QQ 展示只使用公开昵称

[seer.team_resource]
times = ["23:00"]
default_threshold = 1000
default_at_users = ["owner"]

# 群主/管理员在启用 feature 的群里发送：
# 订阅战队123456
# 订阅战队123456 1000 @提醒人
# 战队订阅
# 取消订阅战队123456
```

配置字段、默认值、中英文说明和示例集中维护在
[config.example.toml](config.example.toml)。查询权限和推送权限是分开的功能名，
例如 `bili_query` 和 `bili_push`；`admin_notice` 只用于管理员通知，不包含在
`all` 里。游戏内每周活动使用 `seer_activity_query` / `seer_activity_push`；
游戏外活动链接使用 `web_activity_link` / `web_activity_push`。消息动作可以
声明自己的 feature 名：`[[messaging.commands]]` 和 `[[messaging.schedules]]`
中的 `feature` 会注册为原子权限，随后可在 `[features.bundles]`、
`group_policy` 和 `user_policy` 中引用，不需要修改 Python 枚举。动作的 `id`
只负责唯一标识动作，不会自动成为权限名。未被内置功能或消息动作声明的权限仍会
阻止启动；动态命令权限会进入 `all`、`text`、`message`，动态定时权限会进入
`all`、`text_push`、`message`。`admin_notice` 仍不会被组合间接授予。
`fire_manual_ad`
只控制主动推送末尾的火火手册链接；`ai_intent_fire_manual`
控制用户明确索要手册链接时的 AI 意图动作。

`[features.bundles]` 可以定义 `standard`、`lite` 等可复用组合；组合之间可以引用，
最终按并集展开。自定义名称不能覆盖内置 feature/组合，未知引用、空组合和循环引用
都会阻止启动。为避免管理异常被普通群间接获得，`admin_notice` 不能放入组合，必须在
`group_policy` 或 `user_policy` 的目标项中显式写出。

TOML 对已识别字段严格加载：既非内置也未被消息动作声明的 feature、未知 B站账号引用、
未知 Seer 展示区块和残缺 AI action 都会阻止启动，并在校验错误中给出准确路径。
无法识别的多余字段会被忽略，并在启动输出中列出完整路径；
[config.example.toml](config.example.toml) 是当前唯一权威示例。

帮助提示与未开启 AI 群的 @ 提示共用 `[features.help]` 的两项限流配置。
用户命令额度统一放在 `[messaging.command_cooldown]`：同一 QQ 的同一语义命令
跨群、私聊和多个机器人账号共用多个精确滑动窗口，不同语义命令互不影响。
默认关闭；显式设置 `enabled = true` 后，内置窗口是 `60 秒 3 次` 与 `300 秒 5 次`。
成功、失败、超时和异常都会在命令结束后计入相同窗口，超级管理员绕过。玩家基础查询、收集、巅峰、群星牌分别使用
`seer_player`、`seer_player_collection`、`seer_player_peak`、`seer_player_autocard`
四个独立额度，可在 `commands` 中单独覆盖。
常用语义 ID 包括 `seer_player`、`seer_player_collection`、
`seer_player_peak`、`seer_player_autocard`、`seer_team`、
`seer_rank_list`、`seer_rank_player`、`seer_rank_score`、
`server_status_query`、`ai_chat` 和 `data_sync`。动态文本命令使用
`message.<id>`，AI 意图使用
`ai_intent.<action_id>`；对应 `id` 必须稳定且不可为空。

群消息发送额度默认关闭；显式设置 `[messaging.outbound_rate_limit].enabled = true` 后，使用
`[messaging.outbound_rate_limit].windows` 的多个精确滑动窗口。
任一窗口达到上限都会抑制后续普通回复；主动推送与超级管理员触发的群回复会在
每群独立的无上限优先队列中等待，其中超级管理员回复优先。私聊和启用
`admin_notice` 的管理群不计入群额度。

行为配置只属于 `ironsbot.toml`；`.env` 和 Unraid 模板只保存部署参数与密钥。

### Feature 对照表

| feature | 作用 |
| --- | --- |
| `all` | 除 `admin_notice` 外的大多数功能总开关；不包含管理通知。 |
| `query` | 常用查询组合：赛尔查询、精灵配置图、图片、榜单、B站查询、活动查询、开服查询。 |
| `seer` | 全部赛尔查询子功能总开关。 |
| `seer_player` | 米米号绑定、玩家基础信息及收集/巅峰/群星牌快捷查询。 |
| `player_lineup_private` | 查询公开阵容；群聊和私聊都使用这个独立权限。 |
| `seer_team` | 战队 ID 查询。 |
| `seer_pet` | 精灵、技能、魂印、立绘、皮肤查询。 |
| `pet_config` | 本地精灵配置图查询；独立于 `seer` 功能包，图片文件名使用精灵序号。 |
| `seer_mintmark` | 刻印、刻印系列、宝石、刻印数值榜。 |
| `seer_equipment` | 套装、部件、称号查询。 |
| `seer_type` | 属性克制、异常状态查询。 |
| `seer_peak` | 巅峰池、票选、巅峰榜、精灵出场榜。 |
| `seer_autocard` | 群星牌资料和群星之巅榜。 |
| `seer_rank` | 全服榜、样本榜、榜单情况、样本情况、缓存/刷新榜单。 |
| `seer_data` | 下周预告、新增成就、数据版本等数据工具。 |
| `image` | 固定图片/本地图发送。 |
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
| `activity` / `seer_activity` | `seer_activity_query` + `seer_activity_push`。 |
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

## 数据与缓存

建议把 `/app/data` 持久化。这里会保存：

- SeerAPI / alias SQLite 缓存
- B站 Cookie 与动态状态
- 米米号样本排行 SQLite
- QQ 用户默认米米号绑定 SQLite
- 玩家查询每日额度 SQLite
- 全服榜页 SQLite 缓存
- 皮肤价格、渲染缓存等运行数据

超级管理员发送 `/更新数据` 时，IronsBot 会先按
`[operations.data_sync.sources.seerapi.remote_build.steps]` 顺序触发远程
GitHub Actions 流水线，再下载最新 `ironsbot-data.sqlite`。默认示例流水线为：

1. `Murmansk-Seer/data-update-workflows`：检查淘米官方资源包，更新 Unity 资源和完整配置源。
2. `Murmansk-Seer/seer-unity-config-parser`：抓取官方 Unity ConfigPackage 并导出补充 JSON。
3. `Murmansk-Seer/config-sources`：同步上游配置源并检查官方版本。
4. `Murmansk-Seer/api-data`：用 Solaris 构建 SeerAPI 基础 SQLite。
5. `Murmansk-Seer/seerapi`：合并基础库、官方 ConfigPackage 补充表和自定义表，发布 IronsBot 运行库。

启用远程构建时，环境变量需要填写 `GITHUB_WORKFLOW_TOKEN`。默认情况下，启动同步和定时同步只下载
已有 release，不触发 Actions，避免容器启动过慢或频繁消耗 GitHub Actions。启动同步默认开启；
如不希望开机下载 release，可设置：

```toml
[operations.data_sync]
on_startup = false
```

若希望开机时近似执行一次 `/更新数据`，可同时设置：

```toml
[operations.data_sync]
on_startup = true
startup_trigger_remote_build = true
```

开机同步的成功、失败、无需更新状态会追加到“机器人已开启。”通知中。

## Docker 自更新与重启

超级管理员可以发送 `/重启机器人`（同义命令：`/机器人重启`、`/更新镜像`、`/更新Docker`）
进入同一套重启流程。默认会先检查 `murmansk5000/ironsbot:latest` 是否有新镜像；
检测到新镜像时会启动一次性 Watchtower 更新当前容器。镜像已是最新时，如果挂载了
Docker socket，会通过 Docker API 重启当前容器；没有 Docker socket 时才退回普通
进程重启。

这个能力需要把宿主机 Docker socket 挂进容器：

```text
/var/run/docker.sock -> /var/run/docker.sock
```

TOML 可调整检查时机、容器名、目标镜像和 Watchtower 镜像：

```toml
[operations.docker_update]
check_on_startup = true
check_on_restart = true
image = "murmansk5000/ironsbot:latest"
container_name = "ironsbot"
docker_socket_path = "/var/run/docker.sock"
watchtower_image = "containrrr/watchtower:latest"
watchtower_docker_api_version = "1.40"
```

### 私有扩展包

公共镜像不包含阵容命令、协议解析、缓存或渲染实现。只有已安装且已验证的私有扩展包才会
注册该功能，并复用主机器人的精灵数据、头像资源和渲染器。

真实阵容来自可选私有扩展包 `murmansk5000/ironsbot-private:latest`。它不是机器人
覆盖镜像：Unraid 的 Repository 和 `[operations.docker_update].image` 始终保持
`murmansk5000/ironsbot:latest`。容器启动时，公开主镜像通过 Docker socket 拉取私有包、
校验清单并解包到 `/app/data/private_extensions`，再只加载公开代码明确认可的扩展契约。

阵容是第一个扩展；以后可在同一个私有包中增加新的、由公开主程序显式支持的扩展。整个
部署仍只有一个 IronsBot 进程和一个无头米米号登录。扩展直接借用主连接发送封包，不启动
FastAPI、不暴露端口，也不需要第二个米米号或 API Token。

在 TOML 中启用私有扩展包：

```toml
[operations.private_extensions]
enabled = true
image = "murmansk5000/ironsbot-private:latest"
```

再在 Unraid 容器变量或 `.env.prod` 中设置 Docker Hub 的最小拉取凭据；不要写进 TOML：

```text
DOCKER_REGISTRY_USERNAME=murmansk5000
DOCKER_REGISTRY_TOKEN=private-image-pull-token
```

私有扩展包在公开主镜像启动前通过已挂载的 Docker socket 拉取，因此 Unraid 的 Repository
不需要改成私有镜像。Docker socket、上述两个容器变量，以及 `enabled = true` 都是必要条件；
首次拉取失败时会保留上一次成功安装的扩展；没有可用包时，阵容功能不会注册。

凭据缺失或私有镜像没有安装时，主机器人仍会正常启动，`阵容` 不会响应。
主无头账号仍由 `HEADLESS_SEER_USER_ID` 和 `HEADLESS_SEER_PASSWORD` 配置，阵容功能不再
拥有独立账号、密码或重连策略。

如果不想让机器人自然启动时检查镜像，可改为：

```toml
[operations.docker_update]
check_on_startup = false
```

如果不想让手动 `/重启机器人` 或 `/更新镜像` 时检查镜像，可改为：

```toml
[operations.docker_update]
check_on_restart = false
```

自然启动检查任务注册在数据同步之前；如果发现新镜像，Watchtower 会重建容器，
本轮启动会被新容器替换。镜像通知会显示当前/最新镜像短号、北京时间构建时间，
并在镜像带有 OCI revision label 时附上对应 Git commit 摘要。

没有挂载 Docker socket 时，镜像检查会被跳过；Windows 源码运行可把两个开关改成 `false`。
新版 Unraid / Docker Engine 如果提示 `client version 1.25 is too old`，保持
`watchtower_docker_api_version = "1.40"` 即可。

推送通知会按订阅项拆分，例如机器人启动、Docker 镜像检查、启动数据同步、
AI 聊天异常、B站登录、无头赛尔号、精灵渲染崩溃、红包提醒、按账号拆分的 B站动态和活动结束提醒。
私聊发送 `TD`，或群主/管理员在群里发送 `TD`，可以分别退订/恢复
这些推送；发送 `推送时间` 可修改本群可编辑推送的提醒时间。

`.env.dev`、`.env.prod` 和真实运行数据不应提交到 Git。

## 鸣谢

本项目独立维护，并感谢以下上游项目、作者与社区贡献者提供的基础、数据工具和参考实现。

- [Nattsu39](https://github.com/Nattsu39) 的 [IronsBot](https://github.com/Nattsu39/IronsBot)：本项目的上游，提供了核心查询、渲染和协议能力参考。
- @火火（[Yogurt114514](https://github.com/Yogurt114514)）的西塔伦Bot：本项目的早期来源，感谢其为赛尔号玩家社区所做的贡献。
- [SeerAPI 开源团队](https://github.com/SeerAPI) 的 [seerapi](https://github.com/SeerAPI/seerapi) 及其数据生态：提供数据模型、构建工具与基础 SQLite 数据链路。
- HurryWang（[WhY15w](https://github.com/WhY15w)）的 [seer-unity-config-parser](https://github.com/WhY15w/seer-unity-config-parser) 与 [seer-unity-preview-img-dumper](https://github.com/WhY15w/seer-unity-preview-img-dumper)：提供 Unity 配置解析和下周预告图提取参考。
- [SeerRadar](https://github.com/SeerRadar) 的 [Sequ](https://github.com/SeerRadar/Sequ)：提供部分赛尔号数据参考。
- [oldml](https://github.com/oldml) 的 [saixiaoxi](https://github.com/oldml/saixiaoxi)：提供无头登录相关实现参考。

`Murmansk-Seer` 组织维护的 SeerAPI 数据链会在保留原项目署名与许可证的前提下持续演进。

## 上游更新策略

本仓库已经是独立维护线，不再直接 merge 或 rebase
[Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot) 的 `main`。
GitHub Actions 里的 upstream workflow 只负责定时生成巡检报告，不会自动合并、
提交、推送或发布镜像。

处理上游更新时按类型选择性吸收：

- 小型 bug 修复：手动 port 到当前架构，或在确认冲突范围后单独 cherry-pick。
- 数据和别名更新：进入 SeerAPI / alias SQLite 数据构建流程，不在 bot 仓库恢复旧 CSV。
- 精灵查询、渲染、协议能力：按 `services` / `integrations` 边界吸收，不恢复原版用户入口。
- 上游结构性重构：默认不跟随，除非它修复了当前项目里的具体问题。

也就是说，上游现在是参考源和补丁来源，不是可以直接同步的主线。

## 本地开发

```powershell
uv sync --group dev
uv run python scripts/check_repo.py
uv run python -m ironsbot
```

如果 Windows 终端中文显示异常，可以在当前 PowerShell 会话里先执行：

```powershell
$env:PYTHONUTF8 = "1"
$env:PYTHONIOENCODING = "utf-8"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

快速只检查配置文件语法和 UTF-8/乱码扫描：

```powershell
uv run python scripts/check_repo.py --static
```

## 许可证

本仓库采用多许可证结构，详见 [LICENSING.md](LICENSING.md)。

- 包含 GPL 插件/代码的完整仓库和 Docker 镜像整体按 GPL-3.0-or-later 分发。
- 可独立复用的自定义插件与工具代码按各文件 SPDX 声明执行。
