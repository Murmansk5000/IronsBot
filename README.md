<p align="center">
  <img src="icon.png" width="128" alt="IronsBot icon">
</p>

# IronsBot

IronsBot 是一个面向 QQ / OneBot v11 的赛尔号机器人，基于 NoneBot2 构建，主要服务于自部署、Unraid 和 Docker 使用场景。

当前主线已经转为自定义插件架构：用户可触发的功能由 `ironsbot/custom_plugins` 提供；原版查询代码仅作为数据、渲染和协议能力的来源或基础设施依赖保留。

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
    environment:
      ENVIRONMENT: "prod"
      HOST: "0.0.0.0"
      PORT: "8080"
      ONEBOT_ACCESS_TOKEN: "change-me"
      SUPERUSERS: '["123456789"]'
      DATA_SYNC_CONFIG: '{"on_startup":false,"interval_enabled":true,"sources":{"seerapi":{"url":"https://github.com/Murmansk5000/seerapi/releases/download/ironsbot-data-latest/ironsbot-data.sqlite","fingerprint_url":"https://github.com/Murmansk5000/seerapi/releases/download/ironsbot-data-latest/ironsbot-data.sqlite.sha256","interval_minutes":60,"local_path":"data/ironsbot-data.sqlite"},"aliases":{"url":"https://github.com/Murmansk5000/seerapi/releases/download/alias-db-latest/aliases-data.sqlite","fingerprint_url":"https://github.com/Murmansk5000/seerapi/releases/download/alias-db-latest/aliases-data.sqlite.sha256","interval_minutes":60,"local_path":"data/aliases-data.sqlite"}}}'
    restart: always
```

完整变量说明见 [docker/README.md](docker/README.md) 和 [.env.example](.env.example)。

## 插件架构

用户功能集中在 `ironsbot/custom_plugins`：

| 插件 | 作用 |
| --- | --- |
| `custom_get_seer_info` | 自定义赛尔号查询、榜单、群星牌、活动相关入口。 |
| `custom_help` | 按当前群/私聊权限显示可用功能。 |
| `custom_about` | 新版关于页。 |
| `custom_sendpic` | 固定关键词发图。 |
| `message_actions` | 通用文本回复、定时消息、事件回复和批量发送。 |
| `bilibili_monitor` | B站动态监控与点播。 |
| `meeting_reply` | 腾讯会议回复。 |
| `team_shortcut` | 战队群快捷查询与资源提醒。 |
| `activity_reminder` | 当前活动、快结束活动和活动结束提醒。 |
| `server_status` | 开服查询与管理员服务器状态指令。 |
| `headless_seer_notice` | 无头登录状态检查、重连和通知。 |
| `ai_chat` | AI 聊天。 |
| `ai_intent_actions` | AI 判定后触发文本或战队动作。 |
| `scheduled_restart` | 每日定时重启机器人进程。 |

原版 `ironsbot/plugins` 不作为用户功能目录整目录加载；只显式加载数据库同步、无头登录、HTTP 客户端、赛尔号数据等基础设施。

## Common Variables

```env
ONEBOT_ACCESS_TOKEN=change-me
SUPERUSERS=["123456789"]
GROUP_ALIASES={"admin":686376929,"main":123456789}
USER_ALIASES={"owner":123456789}
FEATURE_GROUP_POLICY={"admin":["admin_notice"],"main":["seer","image","rank","meeting","text","text_push","bili_query","bili_push","activity_query","activity_push","server_status_query","server_status_push","team","ai_chat","ai_intent"]}
FEATURE_USER_POLICY={"owner":["all"]}
FEATURE_SUPERUSER_BYPASS=true
BILI_CONFIG={"uids":[1310714247],"storage":{"data_dir":"data/bilibili_monitor","history_max_items":1000},"polling":{"default_minutes":30,"windows":[{"start":"07:00","end":"23:00","minutes":5}]},"push":{"default_mode":"full","groups":{"main":{"uids":[1310714247],"mode":"full"}},"users":{}},"filters":{"suppress_push_patterns":["恭喜.*获得","记得及时查看私信通知","中奖","抽奖结果"]}}
MSG_CONFIG={"reply":{"default_lines":-1,"min_lines":5,"max_lines":80,"limit_path":"data/message_actions/reply_limits.sqlite"},"group_commands":[{"id":"notice","feature":"activity_link","commands":["link"],"message":"activity link"}],"group_schedules":[{"id":"night","feature":"activity_link_push","hour":23,"minute":0,"message":"good night"}]}
ACTIVITY_CONFIG={"enabled":true,"lead_hours":[11,1],"grace_minutes":15,"only_shown":true,"cache_path":"data/activity_reminder/sent.sqlite","message":"⏰ 本周活动将在约 {lead_hours} 小时后结束\n{activity_list}"}
STARTUP_CONFIG={"enabled":true,"message":"机器人已开启。","delay":0}
BOT_RESTART_CONFIG={"enabled":false,"times":"04:30","grace_seconds":10,"signal_parent":true}
HEADLESS_NOTICE_CONFIG={"login_notice":true,"state_notice":true,"reconnect_check_times":"00:01,00:02"}
SERVER_STATUS_CONFIG={"broadcast":false,"broadcast_message":"赛尔号已经开服了。","broadcast_cooldown_minutes":1440}
AI_CONFIG={"base_url":"https://api.deepseek.com","model":"deepseek-v4-pro","intent_actions_enabled":true,"action_templates":{},"intent_actions":[{"template":"join_team"}]}
```

Group and user IDs are written once in aliases, then features are enabled from `FEATURE_GROUP_POLICY` / `FEATURE_USER_POLICY`. Push and query permissions are separate features, such as `bili_query` and `bili_push`. Bilibili pushes must also be explicitly listed in `BILI_CONFIG.push.groups/users`; each target can subscribe to selected UIDs and choose `full` or `link`. Admin-only notices use `admin_notice`; it is intentionally not included by `all`. Message actions use their own `feature` field, for example `activity_link` or `seerinfo`. Module-level options are grouped into JSON configs such as `BILI_CONFIG`, `MSG_CONFIG`, `ACTIVITY_CONFIG`, `HEADLESS_NOTICE_CONFIG`, `SERVER_STATUS_CONFIG`, and `AI_CONFIG`, so Unraid does not need dozens of one-off variables.

## 数据与缓存

建议把 `/app/data` 持久化。这里会保存：

- SeerAPI / alias SQLite 缓存
- B站 Cookie 与动态状态
- 米米号样本排行 SQLite
- 全服榜页 SQLite 缓存
- 皮肤价格、渲染缓存等运行数据

`.env.dev`、`.env.prod` 和真实运行数据不应提交到 Git。

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
