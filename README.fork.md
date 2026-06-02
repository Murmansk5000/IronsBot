<p align="center">
  <img src="icon.png" width="128" alt="IronsBot icon">
</p>

# IronsBot Fork Notes

IronsBot 是一个基于 NoneBot2 / OneBot v11 的赛尔号信息查询机器人。本仓库是
[Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot) 的个人 fork，保留上游查询能力，同时加入一些适合 QQ 群、Docker 和 Unraid 使用的自定义插件与部署模板。

## 这个 Fork 做了什么

- 提供 Docker Hub / GHCR 镜像，方便 Unraid 和 Docker Compose 部署。
- 提供 Unraid Community Applications 模板。
- 保留赛尔号精灵、技能、魂印、巅峰、战队等查询能力。
- 增加本地自定义图片回复、B站动态监控、AI 聊天、活动链接、会议回复、启动通知、定时私聊和战队群快捷查询。
- 将 B站 Cookie、数据库缓存等运行数据放到 `/app/data`，便于容器重建后保留状态。

## 镜像

```text
docker.io/murmansk5000/ironsbot:latest
ghcr.io/murmansk5000/ironsbot:latest
```

`latest` 始终指向本 fork 的最新 `main` 构建。构建还会发布额外 tag：

- `<upstream-version>.<fork-revision>`：例如 `0.5.1.26`，表示基于上游 `0.5.1` 的第 26 个 fork 修订版。
- `sha-xxxxxxx`：精确到 Git commit 的镜像。

正常使用 Unraid 更新时可以继续使用 `murmansk5000/ironsbot:latest`。需要追踪具体版本时再看版本 tag 或 commit tag。

## 快速部署

### Unraid

在 Community Applications 中搜索 `ironsbot` 并安装。

建议至少确认这些配置：

- `Repository`: `murmansk5000/ironsbot:latest`
- `WebSocket Port`: `8085`
- `IronsBot Data`: `/mnt/user/appdata/ironsbot/data` -> `/app/data`
- `ONEBOT_ACCESS_TOKEN`: 与 NapCat 反向 WebSocket token 保持一致
- `SUPERUSERS`: 机器人超级管理员 QQ，例如 `["123456789"]`

NapCat 反向 WebSocket 地址：

```text
ws://UNRAID_SERVER_IP:8085/onebot/v11/ws
```

如果 NapCat 和 IronsBot 在同一个 Docker 自定义网络中，也可以使用：

```text
ws://ironsbot:8080/onebot/v11/ws
```

### Docker Compose

最小示例：

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

更完整的 Docker Compose 和变量说明见 [docker/README.md](docker/README.md)。

## 常用插件

| 插件 | 作用 |
| --- | --- |
| `get_seer_info` | 上游赛尔号资料查询插件。 |
| `headless_seer` | 可选的无头赛尔号登录客户端，用于需要登录的功能。 |
| `sendpic_custom` | 本地固定关键词发图。 |
| `bilibili_monitor` | 监控指定 B站账号动态，支持 Cookie 失效后给管理员发登录二维码。 |
| `ai_chat` | 接入 DeepSeek / OpenAI-compatible API，群聊通过 @ 触发。 |
| `event_link` | 回复或定时推送活动链接。 |
| `meeting_reply` | 根据环境变量回复腾讯会议信息。 |
| `scheduled_private_message` | 定时给指定用户发送私聊消息。 |
| `startup_notice` | 机器人连接后通知超级管理员。 |
| `team_shortcut` | 战队群快捷查询固定战队，并可在资源过低时 @ 指定用户。 |

自定义插件说明见 [ironsbot/custom_plugins/README.md](ironsbot/custom_plugins/README.md)。

## 重要变量

完整示例在 [.env.example](.env.example)。下面是部署时最常用的几类：

### 基础连接

```env
ONEBOT_ACCESS_TOKEN=change-me
SUPERUSERS=["123456789"]
```

### 数据库缓存与同步

```env
DB_SYNC_ON_STARTUP=false
DB_SYNC_INTERVAL_ENABLED=true
SEERAPI_LOCAL_PATH=data/seerapi-data.sqlite
ALIAS_LOCAL_PATH=data/aliases-data.sqlite
```

超级管理员可以发送 `更新数据` 或 `数据更新` 手动同步数据库。

### B站动态监控

```env
BILIBILI_MONITOR_UID=1310714247
BILIBILI_MONITOR_TARGET_GROUP_IDS=[]
BILIBILI_MONITOR_TARGET_USER_IDS=[]
BILIBILI_MONITOR_ADMIN_UIDS=[]
BILIBILI_MONITOR_DATA_DIR=data/bilibili_monitor
```

`SUPERUSERS` 会自动拥有 B站监控管理权限。Cookie 登录二维码会私聊发送给管理员，`/app/data` 持久化后重建容器不容易丢失 Cookie。

### AI 聊天

```env
AI_CHAT_API_KEY=sk-...
AI_CHAT_BASE_URL=https://api.deepseek.com
AI_CHAT_MODEL=deepseek-v4-flash
AI_CHAT_ALLOWED_GROUP_IDS=[]
AI_CHAT_ALLOWED_USER_IDS=[]
AI_CHAT_ADMIN_UIDS=[]
```

规则：

- `SUPERUSERS` 全局可用。
- 群聊中，只有 `AI_CHAT_ALLOWED_GROUP_IDS` 里的群允许群成员 @ 机器人聊天。
- 私聊中，用户需要在 `AI_CHAT_ALLOWED_USER_IDS`、`AI_CHAT_ADMIN_UIDS` 或 `SUPERUSERS` 中。
- 群聊回复会自动 @ 提问者，避免多人同时提问时混乱。

### 战队群快捷查询

```env
TEAM_SHORTCUT_GROUP_IDS=[]
TEAM_SHORTCUT_TEAM_IDS=[]
TEAM_SHORTCUT_COMMANDS=["战队"]
TEAM_SHORTCUT_RESOURCE_NOTICE_USER_IDS=[]
TEAM_SHORTCUT_RESOURCE_NOTICE_MESSAGE=该买战队资源啦
```

当配置群内有人发送 `战队` 时，机器人会依次查询配置的战队 ID。任一战队资源低于 1000 时，可额外 @ 指定用户提醒购买资源。

## 本地开发

```powershell
uv run python -B -m py_compile bot.py
uv run python bot.py
```

本地开发使用 `.env.dev`，生产部署使用 `.env.prod`、Docker Compose 环境变量或 Unraid 模板变量。不要把真实 token、QQ 号、群号、账号密码、Cookie 或会议链接提交到 GitHub。

## 隐私与安全

- 真实 QQ 号、群号、战队 ID、会议号、账号密码、API Key、Cookie 都应放在运行环境变量中。
- `.env.dev` 和 `.env.prod` 已被 `.gitignore` 忽略。
- 如果敏感信息曾经推送到公开仓库，应视为泄露并立即更换。
- B站 Cookie、数据库缓存等运行数据建议挂载到 `/app/data`。

## 鸣谢

- 上游项目：[Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot)
- SeerAPI：[SeerAPI](https://github.com/SeerAPI)
- `headless_seer` 部分登录/会话逻辑参考 [oldml/saixiaoxi](https://github.com/oldml/saixiaoxi)
- 感谢原 IronsBot 和赛尔号玩家社区的维护与贡献。

## 许可证

本仓库采用多许可证结构，详见 [LICENSING.md](LICENSING.md)。

- 包含 GPL 插件的完整仓库和 Docker 镜像整体按 GPL-3.0-or-later 分发。
- `get_seer_info`、`headless_seer` 为 GPL-3.0-or-later。
- 其余可独立复用代码按 MIT 许可。
