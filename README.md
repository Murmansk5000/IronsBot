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
      DB_SYNC_ON_STARTUP: "false"
      DB_SYNC_INTERVAL_ENABLED: "true"
      SEERAPI_LOCAL_PATH: "data/seerapi-data.sqlite"
      ALIAS_LOCAL_PATH: "data/aliases-data.sqlite"
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

## 常用变量

```env
ONEBOT_ACCESS_TOKEN=change-me
SUPERUSERS=["123456789"]
ADMIN_GROUPS=[]
ADMIN_BYPASS_GROUPS=false
CUSTOM_FEATURE_GROUPS=[]
CUSTOM_FEATURE_USERS=[]
CUSTOM_PUSH_GROUPS=[]
CUSTOM_PUSH_EXCLUDE_GROUPS=[]
```

核心规则：

- `SUPERUSERS` 是最高权限用户。
- `ADMIN_GROUPS` 仅供本节点尚未迁移的原生消费者使用：bilibili_monitor、custom_sendpic、pet_config_reply；帮助可见性跟随对应真实消费者，不把旧列表并入新策略。
- `ADMIN_BYPASS_GROUPS=false` 保持旧策略的群限制；新策略单独使用 FEATURE_SUPERUSER_BYPASS，默认 false。
- `CUSTOM_FEATURE_GROUPS` / `CUSTOM_FEATURE_USERS` 仅控制仍调用原生旧策略的查询；已迁移消费者见下列功能策略说明。
- 会议、AI、B站推送、战队快捷、文本回复等功能有自己的细分变量。

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
- Unity 配置解析参考：[WhY15w/seer-unity-config-parser](https://github.com/WhY15w/seer-unity-config-parser)
- 感谢赛尔号玩家社区的资料整理与测试反馈。

## 许可证

本仓库采用多许可证结构，详见 [LICENSING.md](LICENSING.md)。

- 包含 GPL 插件/代码的完整仓库和 Docker 镜像整体按 GPL-3.0-or-later 分发。
- 可独立复用的自定义插件与工具代码按各文件 SPDX 声明执行。


### 本节点功能策略与实际消费边界

新策略消费者：activity_reminder、ai_chat、ai_intent_actions、custom_get_seer_info、headless_seer_notice、meeting_reply、message_actions、rank_help、server_status、startup_notice、superuser_priority、team_shortcut。
旧原生策略消费者：bilibili_monitor、custom_sendpic、pet_config_reply。
帮助按同一节点的真实授权与配置判断；它不授予额外权限，也不保证每条文本都匹配命令。推送资格与查询资格分别计算，能收推送不代表能查询。
GROUP_ALIASES / USER_ALIASES 解析 FEATURE_GROUP_POLICY / FEATURE_USER_POLICY 的键；数字字符串键也可使用。新策略默认空映射，不继承旧 ADMIN_GROUPS 或 CUSTOM_FEATURE_GROUPS/USERS。FEATURE_SUPERUSER_BYPASS 默认 false；群超管默认不绕过新策略，私聊超管按原实现允许。
开服普通查询用 server_status_query，广播用 server_status_push；管理员开服/重启入口仍仅超管，所以超管可以看到该帮助，但普通查询不因此绕过群规则。广播目标仍由原 selector 和触发保护共同约束。
AI聊天读取原 ai_chat.config 的 AI_KEY，并用 ai 权限；AI意图读取本节点原 AI_INTENT_ACTIONS_ENABLED、AI_ACTION_TEMPLATES、AI_INTENT_ACTIONS，经原 get_configured_actions 解析模板后，逐个检查 enabled 与 action.feature。不得用旧 group_ids/user_ids 或固定 ai_intent 替代，全禁用、无动作、无 AI_KEY 时不显示意图帮助；这里只判断可配置入口，不调用分类网络。
榜单入口 rank_help 使用 rank；不提前改变扩展赛尔号查询模块的其他原命令权限。
活动普通查询用 activity_query、推送用 activity_push；原超级管理员当前活动入口仍可见。ACTIVITY_REMINDER_GROUPS/USERS 不再被活动模块消费；推送用户显式合并超管。
图片/配置图在本节点仍按原 custom 谓词授权和显示；34dc 才迁移为 image/seer。
B站直到 cf2 前仍使用原 BILI_GROUPS/BILI_USERS 与原 custom 查询谓词；帮助也只跟随该谓词，不因配置 bili_query/bili_push 就声称可用。更新仍要求超管且满足原目标群规则，私聊超管允许；旧 ADMIN_BYPASS_GROUPS 的显式 opt-in 行为不变。不提前引入 BILI_CONFIG、resolver、UID路由或跨群刷新授权。
原 all 简写实际也匹配 admin_notice；需要通知隔离时逐项列功能。推送仅在真实 consumer 显式调用 users_with_superusers 时合并超管，群目标不隐式继承旧管理员群。

```dotenv
GROUP_ALIASES={}
USER_ALIASES={}
FEATURE_GROUP_POLICY={}
FEATURE_USER_POLICY={}
FEATURE_SUPERUSER_BYPASS=false
```
