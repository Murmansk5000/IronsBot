<p align="center">
  <img src="icon.png" width="128" alt="IronsBot icon">
</p>

# IronsBot

IronsBot 是一个面向 QQ / OneBot v11 的赛尔号机器人，基于 NoneBot2 构建，主要服务于自部署、Unraid 和 Docker 使用场景。

当前主线已经转为显式插件架构：用户可触发的功能集中在 `ironsbot/plugins`；原版查询代码仅作为数据、渲染和协议能力的来源或基础设施依赖保留。

## 功能

- 自定义米米号查询：基础信息先返回，收集与巅峰通过二级回复查看。
- 自定义战队查询：支持快捷战队、资源不足提醒和战队详情展示。
- 精灵、技能、魂印、皮肤、刻印、套装、部件、称号、属性、异常状态查询。
- 全服榜、样本榜、巅峰榜、刻印数值榜与缓存状态查询。
- 群星牌公开资料查询。
- B站动态监控与历史动态点播。
- 当前活动、快结束活动和活动结束提醒。
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
- `IronsBot Data`: `/mnt/user/appdata/ironsbot/data` -> `/app/data`
- `ONEBOT_ACCESS_TOKEN`: 与 NapCat 反向 WebSocket token 一致
- `SUPERUSERS`: 超级管理员 QQ，例如 `["1234567890"]`

NapCat 反向 WebSocket：

```text
ws://UNRAID_SERVER_IP:8085/onebot/v11/ws
```

如果 NapCat 和 IronsBot 在同一个 Docker 自定义网络里，也可以使用：

```text
ws://ironsbot:8080/onebot/v11/ws
```

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
    environment:
      ENVIRONMENT: "prod"
      HOST: "0.0.0.0"
      PORT: "8080"
      APP_CONFIG_PATH: "/config/ironsbot.toml"
      ONEBOT_ACCESS_TOKEN: "change-me"
      SUPERUSERS: '["1234567890"]'
    restart: always
```

首次启动时，如果 `./ironsbot-config/ironsbot.toml` 不存在，IronsBot 会自动从镜像内的
`/app/config.example.toml` 复制一份示例配置。启动后请先修改这份 TOML，再正式使用。
完整部署说明见
[docker/README.md](docker/README.md) 和 [.env.example](.env.example)。

## 插件架构

用户功能集中在 `ironsbot/plugins`，并由 manifest 显式加载：

| 插件 | 作用 |
| --- | --- |
| `seer.query` | 自定义赛尔号查询、榜单、群星牌、活动相关入口。 |
| `help` | 按当前群/私聊权限显示可用功能。 |
| `about` | 新版关于页。 |
| `sendpic` | 固定关键词发图。 |
| `messaging` | 通用文本回复、定时消息、事件回复和批量发送。 |
| `bilibili` | B站动态监控与点播。 |
| `meeting` | 腾讯会议回复。 |
| `team_resource_subscription` | 战队资源订阅、群内订阅战队查询与低资源提醒。 |
| `activity` | 当前活动、快结束活动和活动结束提醒。 |
| `server_status` | 开服查询与管理员服务器状态指令。 |
| `headless_seer_notice` | 无头登录状态检查、重连和通知。 |
| `ai_chat` | AI 聊天。 |
| `ai_intent` | AI 意图分析，并把命中的意图分发给对应功能。 |
| `team_recommend` | AI 判定用户想加入战队后发送战队推荐/审核群信息。 |
| `scheduled_restart` | 每日定时重启机器人进程。 |

仓库不会扫描插件目录整目录加载；`bot.py` 委托 `ironsbot/app/bootstrap.py`，并按 `ironsbot/app/plugin_manifest.py` 显式加载用户适配器、数据库同步、无头登录、HTTP 客户端和赛尔号数据等基础设施。

## 配置方式

行为配置写在 TOML 文件里，并通过 `APP_CONFIG_PATH` 指向它。环境变量只保留：

- secrets：`ONEBOT_ACCESS_TOKEN`、`AI_KEY`、可选 `SENDPIC_CNB_TOKEN`
- credentials：`HEADLESS_SEER_USER_ID`、`HEADLESS_SEER_PASSWORD`
- deployment runtime：`ENVIRONMENT`、`DRIVER`、`HOST`、`PORT`、`LOG_LEVEL`、`COMMAND_START`、`SUPERUSERS`、`APP_CONFIG_PATH`

示例环境变量：

```env
APP_CONFIG_PATH=/config/ironsbot.toml
ONEBOT_ACCESS_TOKEN=change-me
SUPERUSERS=["1234567890"]
AI_KEY=
HEADLESS_SEER_USER_ID=
HEADLESS_SEER_PASSWORD=
```

`APP_CONFIG_PATH` 是容器内路径。Docker/Unraid 常用值是 `/config/ironsbot.toml`；
宿主机上的真实位置取决于你把哪个目录挂载到了 `/config`。例如 Windows Docker
Desktop 可以把 `C:\ironsbot\config` 挂载到 `/config`，那么实际配置文件就是：

```text
C:\ironsbot\config\ironsbot.toml
```

如果这个文件不存在，首次启动会自动按 [config.example.toml](config.example.toml)
创建一份。已有文件不会被覆盖。若你把 `/config` 挂成只读，需要先手动创建
`ironsbot.toml`，或首次启动时改成可写挂载。

示例 TOML：

```toml
[feature]
superuser_bypass = true

[feature.group_aliases]
admin = 123456789
example = 987654321

[feature.user_aliases]
owner = 1234567890

[feature.group_policy]
admin = ["admin_notice"]
example = ["seer", "image", "rank", "meeting", "bili_query", "bili_push", "seer_activity_query", "seer_activity_push", "server_status_query", "server_status_push", "team_resource_subscription", "ai_chat", "ai_intent", "fire_manual"]

[feature.user_policy]
owner = ["all"]

[bilibili.push]

[bilibili.push.groups.example]
uids = [1310714247]
mode = "full"

[seer.team_resource]
times = ["23:00"]

[[seer.team_resource.subscriptions]]
group = "example"
team_ids = [1234567]
threshold = 1000
at_users = ["owner"]
```

配置字段、默认值、中英文说明和示例集中维护在
[config.example.toml](config.example.toml)。查询权限和推送权限是分开的功能名，
例如 `bili_query` 和 `bili_push`；`admin_notice` 只用于管理员通知，不包含在
`all` 里。游戏内每周活动使用 `seer_activity_query` / `seer_activity_push`；
游戏外活动链接使用 `web_activity_link` / `web_activity_push`。消息动作可以
使用自己的 feature 名，例如 `web_activity_link` 或 `seerinfo`。`fire_manual`
控制“手册”AI 意图识别和主动推送末尾的火火手册链接。

### Feature 对照表

| feature | 作用 |
| --- | --- |
| `all` | 除 `admin_notice` 外的大多数功能总开关；不包含管理通知。 |
| `query` | 常用查询组合：赛尔查询、图片、榜单、B站查询、活动查询、开服查询。 |
| `seer` | 全部赛尔查询子功能总开关。 |
| `seer_player` | 米米号、玩家基础信息、收集/巅峰/群星牌二级回复。 |
| `seer_team` | 战队 ID 查询。 |
| `seer_pet` | 精灵、技能、魂印、立绘、皮肤查询。 |
| `seer_mintmark` | 刻印、刻印系列、宝石、刻印数值榜。 |
| `seer_equipment` | 套装、部件、称号查询。 |
| `seer_type` | 属性克制、异常状态查询。 |
| `seer_peak` | 巅峰池、票选、巅峰榜、精灵出场榜。 |
| `seer_autocard` | 群星牌资料和群星之巅榜。 |
| `seer_rank` / `rank` | 全服榜、样本榜、榜单情况、样本情况、缓存/刷新榜单。 |
| `seer_data` | 下周预告、数据版本等数据工具。 |
| `image` | 固定图片/本地图发送。 |
| `meeting` | 腾讯会议回复。 |
| `text` | 通用文本口令回复。 |
| `text_push` | 通用定时文本推送。 |
| `web_activity_link` | 游戏外活动链接口令，例如签到/活动/链接。 |
| `web_activity_push` | 游戏外活动链接定时推送。 |
| `seerinfo` | seerinfo/火火手册等自定义文本入口。 |
| `bili_query` | B站动态手动查询、刷新、历史点播。 |
| `bili_push` | B站动态自动推送。 |
| `bili` | `bili_query` + `bili_push`。 |
| `seer_activity_query` | 游戏内活动、快结束活动手动查询。 |
| `seer_activity_push` | 游戏内活动结束提醒推送。 |
| `activity` / `seer_activity` | `seer_activity_query` + `seer_activity_push`。 |
| `server_status_query` | 开服查询、服务器状态查询。 |
| `server_status_push` | 开服状态广播推送。 |
| `server_status` | `server_status_query` + `server_status_push`。 |
| `team_resource_subscription` | 战队资源订阅：群内 `战队` 查询订阅战队，低资源定时 @ 提醒。 |
| `team_audit` | 战队审核群入群提示和 24 小时 follow-up。 |
| `ai_chat` | @ 机器人或私聊触发 AI 聊天。 |
| `ai_intent` | AI 意图分析，用于战队推荐、手册等意图动作。 |
| `fire_manual` | “手册”AI 意图识别，以及主动推送末尾追加火火手册链接。 |
| `admin_notice` | 管理通知：开机通知、AI/渲染错误通知等；必须显式配置。 |

## 数据与缓存

建议把 `/app/data` 持久化。这里会保存：

- SeerAPI / alias SQLite 缓存
- B站 Cookie 与动态状态
- 米米号样本排行 SQLite
- 全服榜页 SQLite 缓存
- 皮肤价格、渲染缓存等运行数据

超级管理员发送 `/更新数据` 时，IronsBot 会先按
`[runtime.data_sync.sources.seerapi.remote_build.steps]` 顺序触发远程
GitHub Actions 流水线，再下载最新 `ironsbot-data.sqlite`。默认示例流水线为：

1. `Murmansk5000/seer-unity-config-parser`：抓取官方 Unity ConfigPackage 并导出 JSON。
2. `Murmansk5000/config-sources`：同步上游配置源。
3. `Murmansk5000/seer-data`：构建 SeerAPI 基础 SQLite。
4. `Murmansk5000/seerapi`：合并基础库、官方 ConfigPackage 补充表和自定义表，发布 IronsBot 运行库。

启用远程构建时，环境变量需要填写 `GITHUB_WORKFLOW_TOKEN`。启动同步和定时同步只下载
已有 release，不触发 Actions，避免容器启动过慢或频繁消耗 GitHub Actions。

`.env.dev`、`.env.prod` 和真实运行数据不应提交到 Git。

## 致谢

本项目当前是独立维护的 IronsBot 分支，但仍感谢上游与社区项目提供的基础和灵感：

- [Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot)：原 IronsBot 项目，为本项目提供了核心查询、渲染和协议能力参考。
- 本项目原作是 @火火（[GitHub: Yogurt114514](https://github.com/Yogurt114514)）开发的西塔伦Bot，谨以此项目向 @火火 致敬。感谢他为赛尔号玩家社区所做的贡献，愿火种永存。
- [oldml/saixiaoxi](https://github.com/oldml/saixiaoxi)：无头登录相关实现的参考来源之一。
- [WhY15w](https://github.com/WhY15w)：Unity 配置与预告图等赛尔号数据工具参考。

## 上游更新策略

本仓库已经是独立维护线，不再直接 merge 或 rebase
[Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot) 的 `main`。
GitHub Actions 里的 upstream workflow 只负责定时生成巡检报告，不会自动合并、
提交、推送或发布镜像。

处理上游更新时按类型选择性吸收：

- 小型 bug 修复：手动 port 到当前架构，或在确认冲突范围后单独 cherry-pick。
- 数据和别名更新：进入 SeerAPI / alias SQLite 数据构建流程，不在 bot 仓库恢复旧 CSV。
- 精灵查询、渲染、协议能力：通过 `vendor` 边界或 `services` 层吸收，不恢复原版用户入口。
- 上游结构性重构：默认不跟随，除非它修复了当前项目里的具体问题。

也就是说，上游现在是参考源和补丁来源，不是可以直接同步的主线。

## 本地开发

```powershell
uv sync
uv run ruff check
uv run python -m compileall -q ironsbot
uv run python bot.py
```

## README 说明

原作者/上游叙事版本已保留为 [README.old.md](README.old.md)。当前 `README.md` 只描述本仓库现在维护的 IronsBot 自定义版。

## 鸣谢

- 上游项目：[Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot)
- SeerAPI：[SeerAPI](https://github.com/SeerAPI)
- 无头登录参考：[oldml/saixiaoxi](https://github.com/oldml/saixiaoxi)
- Unity 配置解析源：[Murmansk5000/seer-unity-config-parser](https://github.com/Murmansk5000/seer-unity-config-parser)，感谢原项目 [WhY15w/seer-unity-config-parser](https://github.com/WhY15w/seer-unity-config-parser)
- 感谢赛尔号玩家社区的资料整理与测试反馈。

## 许可证

本仓库采用多许可证结构，详见 [LICENSING.md](LICENSING.md)。

- 包含 GPL 插件/代码的完整仓库和 Docker 镜像整体按 GPL-3.0-or-later 分发。
- 可独立复用的自定义插件与工具代码按各文件 SPDX 声明执行。
