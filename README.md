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
- `SUPERUSERS`: 超级管理员 QQ，例如 `["123456789"]`

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
      - ./ironsbot-config:/config:ro
    environment:
      ENVIRONMENT: "prod"
      HOST: "0.0.0.0"
      PORT: "8080"
      APP_CONFIG_PATH: "/config/ironsbot.toml"
      ONEBOT_ACCESS_TOKEN: "change-me"
      SUPERUSERS: '["123456789"]'
    restart: always
```

把 [config.prod.toml](config.prod.toml) 或 [config.example.toml](config.example.toml)
复制为 `./ironsbot-config/ironsbot.toml` 后按需修改。完整部署说明见
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
| `team_shortcut` | 战队群快捷查询与资源提醒。 |
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
SUPERUSERS=["123456789"]
AI_KEY=
HEADLESS_SEER_USER_ID=
HEADLESS_SEER_PASSWORD=
```

示例 TOML：

```toml
[feature]
group_aliases = { admin = 686376929, main = 123456789 }
user_aliases = { owner = 123456789 }
group_policy = { admin = ["admin_notice"], main = ["seer", "image", "rank", "meeting", "bili_query", "bili_push", "activity_query", "activity_push", "server_status_query", "server_status_push", "team", "ai_chat", "ai_intent"] }
user_policy = { owner = ["all"] }
superuser_bypass = true

[bilibili.push]
groups = { main = { uids = [1310714247], mode = "full" } }

[seer.team_shortcut]
team_ids = [1234567]
resource_users = [123456789]
```

配置字段、默认值、中英文说明和示例集中维护在
[config.example.toml](config.example.toml)。查询权限和推送权限是分开的功能名，
例如 `bili_query` 和 `bili_push`；`admin_notice` 只用于管理员通知，不包含在
`all` 里。消息动作可以使用自己的 feature 名，例如 `activity_link` 或
`seerinfo`。

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
