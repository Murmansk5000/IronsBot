<p align="center">
  <img src="https://raw.githubusercontent.com/Murmansk5000/IronsBot/main/icon.png" width="128" alt="IronsBot icon">
</p>

# IronsBot Docker Image

Docker image for [IronsBot](https://github.com/Murmansk5000/IronsBot), a NoneBot2 / OneBot v11 QQ bot focused on Seer queries and Unraid deployment.

The single `PluginDefinition` registry installs user features and lifecycle hooks. Upstream-derived code is retained only where it is still required for data, rendering, or protocol support.

## Images

```text
docker.io/murmansk5000/ironsbot:latest
docker.io/murmansk5000/ironsbot:<base-version>.<revision>
docker.io/murmansk5000/ironsbot:sha-xxxxxxx
ghcr.io/murmansk5000/ironsbot:latest
ghcr.io/murmansk5000/ironsbot:<base-version>.<revision>
ghcr.io/murmansk5000/ironsbot:sha-xxxxxxx
```

`阵容` 的渲染始终由 IronsBot 主进程完成。公开镜像没有私有协议解析器时会发送标注过的
12 格空白示意图；私有 `murmansk5000/ironsbot-private:latest` 是一个扩展包镜像，不是
机器人覆盖镜像。公开主镜像在启动前从其中读取受控扩展，并复用主机器人已经登录的无头
米米号。它不启动第二个容器、第二个 API 或第二个无头登录。

私有镜像需要 Docker Hub 拉取凭据。把 `DOCKER_REGISTRY_USERNAME` 和
`DOCKER_REGISTRY_TOKEN` 设为容器环境变量，并在 TOML 启用
`[operations.private_extensions]`。Unraid 的 Repository 和
`[operations.docker_update].image` 保持公开主镜像。凭据缺失或私有包未安装时，主机器人
仍会启动，阵容查询只显示空白示意图。

容器变量用于已经运行的机器人通过 Docker API 拉取私有扩展包，也可用于 Watchtower 拉取
私有主镜像。当前扩展包方案不要求把 Unraid Repository 改成私有镜像。

`latest` tracks the `main` branch of this repository.

## Version Tags And Changelog

This repository keeps Docker `latest` available, and also publishes extra tags so you can see exactly which build you are running.

- `latest`: the newest `main` build, suitable for normal Unraid updates.
- `<base-version>.<revision>`: IronsBot base version plus this repository's revision.
- `sha-xxxxxxx`: the exact Git commit used to build the image.

For example, `0.6.0.3` means the image is based on IronsBot `0.6.0` with the 3rd revision after that base version.

Recent changes are tracked in the GitHub commit history and in the Unraid template notes. On Docker Hub, check the tag list for the newest project-version tag and `sha-xxxxxxx` tag.

## Included Plugins

- Seer player, team, pet, mintmark, equipment, type, peak, Autocard, and rank queries.
- Fixed and scheduled messages, fixed images, meeting replies, help, and push controls.
- Bilibili monitoring, activity reminders, open-server notices, and team workflows.
- AI chat, mention protection, intent recognition, and configured template actions.
- Data sync, headless login, startup notices, scheduled restarts, and Docker updates.

Behavior and runtime values belong in a mounted TOML config file. Environment
variables are reserved for the config path and secrets. They are intentionally
not baked into the image.

## Quick Start With Docker Compose

Create a `docker-compose.yml` and adjust the values for your own environment:

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
      # Optional but recommended: default config checks the image and can
      # restart/update the current container when this socket is mounted.
      # - /var/run/docker.sock:/var/run/docker.sock
    environment:
      APP_CONFIG_PATH: "/config/ironsbot.toml"
      ONEBOT_ACCESS_TOKEN: "change-me"
    restart: always

  napcat:
    image: mlikiowa/napcat-docker:latest
    container_name: napcat
    mac_address: 02:42:ac:11:00:02
    ports:
      - "6099:6099"
    volumes:
      - ./napcat/config:/app/napcat/config
      - ./ntqq:/app/.config/QQ
    environment:
      NAPCAT_UID: "1000"
      NAPCAT_GID: "1000"
      NAPCAT_WEB_TOKEN: "change-me"
      NAPCAT_REVERSE_WS_POST: "ws://ironsbot:8080/onebot/v11/ws"
      NAPCAT_REVERSE_WS_TOKEN: "change-me"
    restart: always
```

Before starting the container, create
`./ironsbot-config/ironsbot.toml` from
[`config.example.toml`](../config.example.toml) and set
`[bot].superusers`. IronsBot strictly validates this file at startup. It never
creates or rewrites the file.

On Windows Docker Desktop, the left side of the volume is a Windows directory.
Choose any writable directory on any drive. For example:

```powershell
$IRONSBOT_HOME = "D:\DockerData\ironsbot"
New-Item -ItemType Directory -Force `
  "$IRONSBOT_HOME\config", "$IRONSBOT_HOME\data", "$IRONSBOT_HOME\logs"
docker run --name ironsbot `
  -p 8085:8080 `
  -v "${IRONSBOT_HOME}\config:/config" `
  -v "${IRONSBOT_HOME}\data:/app/data" `
  -v "${IRONSBOT_HOME}\logs:/app/logs" `
  -e APP_CONFIG_PATH=/config/ironsbot.toml `
  -e ONEBOT_ACCESS_TOKEN=change-me `
  murmansk5000/ironsbot:latest
```

In this example, `/config/ironsbot.toml` inside the container is
`D:\DockerData\ironsbot\config\ironsbot.toml` on Windows.

Optional Docker image check/update: superusers can send `/重启机器人`;
`/更新镜像` and `/更新Docker` are equivalent commands for the same restart flow.
By default `config.example.toml` checks the target image on startup and before
manual restart/update commands. When a new image exists, IronsBot starts a
one-shot Watchtower updater and keeps the old container from starting the bot.
The recreated container verifies that it is running the expected image before
it starts NoneBot, data sync, or startup notifications. If Watchtower fails,
the old container stays in the handoff state and its Watchtower container is
kept for log inspection. When the image is already current and Docker socket is
mounted, `/重启机器人` restarts the current Docker container through the Docker
API instead of relying on container restart policy. This requires mounting the
Docker Engine socket into the IronsBot container, for example on Unraid/Linux:

```text
/var/run/docker.sock:/var/run/docker.sock
```

Without that socket mount, image checks are skipped and the bot continues to run
normally; manual restart falls back to process restart.

The example TOML includes explicit switches for checking the image before
other startup tasks such as data sync and before manual restart commands:

```toml
[operations.docker_update]
check_on_startup = true
check_on_restart = true
watchtower_docker_api_version = "1.40"
```

Both switches are enabled by default so operators can see where to disable
them. Set one or both to `false` when running directly from source on
Windows/macOS/Linux without Docker socket access, or when you prefer manual
image updates.
Keep `watchtower_docker_api_version = "1.40"` on recent Unraid/Docker Engine
versions if Watchtower reports that client API version 1.25 is too old.

Push notices are split into separate subscriptions, such as bot startup,
Docker image check, startup data sync, AI chat errors, Bilibili login notices,
headless Seer notices, render crash notices, red packet notices, Bilibili pushes, activity
reminders, and open-server pushes. Private users can send `TD`; group owners
or admins can send `TD` in a group to unsubscribe from each push category
independently.

User command limits are configured under `[messaging.command_cooldown]`.
The key is the QQ user plus a stable semantic command ID, so aliases and
different parameters of the same operation share exact sliding-window quotas
while unrelated operations remain independent. Command limits are disabled by default;
set `enabled = true` to use the built-in three requests per 60 seconds and five per
300 seconds windows. Group output limits are also disabled by default and are configured
under `[messaging.outbound_rate_limit]` as multiple sliding windows once enabled. Normal replies are
suppressed immediately after the quota is reached; proactive pushes may wait in
a short per-group FIFO queue. Private messages and groups enabled for
`admin_notice` are not counted.

The bot needs a OneBot v11 client such as NapCat. If NapCat and IronsBot are in the same Compose network, configure NapCat reverse WebSocket to:

```text
ws://ironsbot:8080/onebot/v11/ws
```

If NapCat is created separately in Unraid bridge mode, use the Unraid host IP and mapped port instead:

```text
ws://UNRAID_SERVER_IP:8085/onebot/v11/ws
```

The reverse WebSocket token must match `ONEBOT_ACCESS_TOKEN`.

Multiple NapCat / OneBot v11 clients may connect to the same IronsBot WebSocket
endpoint. Configure `[messaging.bot_routing]` in `ironsbot.toml` when proactive
messages should use different bot accounts for different groups or users:

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

Group and user aliases come from `[features.group_aliases]` and
`[features.user_aliases]`; numeric IDs are also accepted. Replies to incoming
commands keep using the bot that received the event. Bilibili, activity,
scheduled-message, server-status, startup, and other proactive deliveries use
the configured route. Routing does not filter incoming events, so avoid placing
multiple responding bots in the same group unless you separately control which
events each OneBot client forwards.

## Configuration

Behavior config is file-based:

- Create `ironsbot.toml` from `config.example.toml`, then mount its directory
  to `/config`.
- Set `APP_CONFIG_PATH=/config/ironsbot.toml`.
- Use `config.example.toml` for all fields, defaults, English descriptions, Chinese descriptions, and examples.

If `APP_CONFIG_PATH` is not set, IronsBot falls back to
`config/ironsbot.toml` in the current working directory. Missing config files
cause startup to fail. IronsBot never mutates the TOML file. Relative `data/`
and `logs/` paths live under the current working directory.

```env
APP_CONFIG_PATH=/config/ironsbot.toml
ONEBOT_ACCESS_TOKEN=change-me
AI_KEY=
HEADLESS_SEER_USER_ID=
HEADLESS_SEER_PASSWORD=
HEADLESS_SEER_USER_ID_2=
HEADLESS_SEER_PASSWORD_2=
HEADLESS_SEER_USER_ID_3=
HEADLESS_SEER_PASSWORD_3=
SENDPIC_CNB_TOKEN=
GITHUB_WORKFLOW_TOKEN=
```

| Variable | Description |
| --- | --- |
| `APP_CONFIG_PATH` | Path to the mounted behavior config file, usually `/config/ironsbot.toml`. |
| `ONEBOT_ACCESS_TOKEN` | Token used by NapCat / OneBot client to connect to IronsBot. |
| `AI_KEY` | AI chat API key. |
| `HEADLESS_SEER_USER_ID` | Optional Seer account ID for headless login. |
| `HEADLESS_SEER_PASSWORD` | Optional Seer account password as an MD5 value. |
| `HEADLESS_SEER_USER_ID_<NAME>` / `HEADLESS_SEER_PASSWORD_<NAME>` | Optional additional headless worker. The template lists `_2` and `_3`; add more matching suffix pairs as needed. The primary worker is intentionally unsuffixed as worker 1. |
| `SENDPIC_CNB_TOKEN` | Optional CNB backend token for configured sendpic repositories. |
| `GITHUB_WORKFLOW_TOKEN` | Optional GitHub token used to trigger configured data-build workflows. |

Set superusers, listen address, port, command prefixes, and logging under
`[bot]` in TOML.
When file logging is enabled, the default logs rotate at local midnight, keep
30 days, and are not compressed; adjust `[bot.logging]` if disk space requires
a different policy.

Feature names are used in `[features.group_policy]` and
`[features.user_policy]`:

| feature | Meaning |
| --- | --- |
| `all` | Most features except `admin_notice`; admin notices are explicit. |
| `query` | Common query bundle: Seer queries, local pet config images, image replies, Seer ranks, Bilibili query, activity query, server status query. |
| `seer` | All Seer query sub-features. |
| `seer_player` | Mimi ID/player info, collection/peak/Autocard follow-up replies. |
| `seer_team` | Team ID query. |
| `seer_pet` | Pet, skill, soul mark, illustration, and skin queries. |
| `pet_config` | Local pet configuration image query by pet name, alias, or ID; independent of the `seer` bundle. |
| `seer_mintmark` | Mintmark, mintmark series, gem, and mintmark stat ranks. |
| `seer_equipment` | Suit, equipment part, and title queries. |
| `seer_type` | Type matchup and abnormal status queries. |
| `seer_peak` | Peak pools, votes, peak ranks, and pet usage ranks. |
| `seer_autocard` | Autocard data and Autocard global rank. |
| `seer_rank` | Global ranks, sample ranks, rank/sample status, and rank cache commands. |
| `seer_data` | Weekly preview, new-achievement comparison, data version, and data tools. |
| `image` | Fixed/local image replies. |
| `meeting` | Tencent Meeting reply. |
| `text` | Generic text command replies. |
| `text_push` | Generic scheduled text pushes. |
| `web_activity_link` | External web activity link commands, such as sign-in links. |
| `web_activity_push` | External web activity link scheduled pushes. |
| `seerinfo` | Custom text entry for seerinfo / Fire manual links. |
| `bili_query` | Manual Bilibili dynamic query, refresh, history, and detail lookup. |
| `bili_push` | Automatic Bilibili dynamic pushes. |
| `bili` | `bili_query` + `bili_push`. |
| `seer_activity_query` | In-game activity and ending-soon activity queries. |
| `seer_activity_push` | In-game activity ending reminders. |
| `activity` / `seer_activity` | `seer_activity_query` + `seer_activity_push`. |
| `server_status_query` | Server status / open-server query. |
| `server_status_push` | Server status broadcast pushes. |
| `server_status` | `server_status_query` + `server_status_push`. |
| `team_resource_subscription` | Subscribed team query and low-resource @ reminders. |
| `team_audit` | Team audit group join prompt and 24-hour follow-up. |
| `ai_chat` | AI chat by bot mention or authorized private chat. |
| `ai_intent` | AI intent dispatch switch; each action also requires its own feature. |
| `ai_intent_team_recommend` | Team recommendation / audit group info triggered by AI intent classification. |
| `fire_manual_ad` | Fire manual link appended to proactive pushes. |
| `ai_intent_fire_manual` | AI intent action for explicit Fire manual link requests. |
| `admin_notice` | Target permission for admin notices, including startup, AI errors, Bilibili login, headless Seer, render crash, red packet, and similar notices. Concrete push categories can be unsubscribed separately through `TD`. |

Message actions may also use feature names such as `web_activity_link`,
`web_activity_push`, or `seerinfo`.

```toml
[features]
superuser_bypass = true

[features.group_aliases]
admin = 123456789
main = 987654321

[features.user_aliases]
owner = 1234567890

[features.group_policy]
admin = ["admin_notice"]
main = ["seer", "meeting", "web_activity_link", "bili_query", "bili_push", "ai_chat", "ai_intent", "ai_intent_team_recommend", "fire_manual_ad", "ai_intent_fire_manual"]

[features.user_policy]
owner = ["all"]

[bilibili.accounts.seer]
uid = 1310714247

[bilibili.push]
accounts = ["seer"]
mode = "link"
modes = { seer = "full" }

[bilibili.push.groups.main]
accounts = []
mode = "link"

# Group owners/admins can inspect and override one subscribed account at runtime:
# B站账号
# B站推送模式 seer 链接
# Public Bilibili names and numeric UIDs are also accepted.
```

### Behavior Config Validation

Behavior settings belong in `/config/ironsbot.toml`. The current `.env` and
Unraid template only contain deployment settings and secrets, so behavior
upgrades do not require adding behavior fields to the container template.
Configuration validates documented fields, references, and values at startup
and reports the TOML path for invalid entries. Use
[config.example.toml](../config.example.toml) as the authoritative
configuration shape.

## Team Resource Subscription

If you use this Docker image for a Seer team/guild QQ group, you can subscribe that group to one or more teams. The same subscription lets members query those teams with a short command and lets the bot remind configured users when team resources are low.

Example behavior:

```text
User sends: 战队
Bot replies: team info for each configured team ID
```

This is the same kind of output as the built-in `战队<team_id>` query, but the group member does not need to remember the team IDs.

Enable the feature and default reminder settings in `ironsbot.toml`:

```toml
[features]

[features.group_aliases]
example = 987654321

[features.user_aliases]
owner = 1234567890

[features.group_policy]
example = ["team_resource_subscription"]

[seer.team_resource]
times = ["23:00"]
commands = ["战队"]
default_threshold = 1000
default_at_users = ["owner"]
query_timeout_seconds = 20
resource_line = "查到了战队 {team_name}（{team_id}）资源是 {resource}，低于阈值 {threshold}。"
resource_message = "出来买资源，别逼我求你😡"
```

Then group owners/admins manage subscriptions in QQ:

```text
订阅战队123456
订阅战队123456 1000 @提醒人
战队订阅
取消订阅战队123456
```

Keep real QQ group IDs in a mounted config file outside the repository, such as an Unraid appdata directory. Runtime team subscriptions are stored in the shared `[paths].qq_state` database; do not commit that database to GitHub.

## Unraid

This repository includes a Community Applications-ready Unraid template:

- IronsBot template: `templates/ironsbot.xml`
- CA profile: `ca_profile.xml`

Template URLs:

```text
https://raw.githubusercontent.com/Murmansk5000/IronsBot/main/templates/ironsbot.xml
```

The Unraid template exposes a minimal variable set and mounts a config
directory. Put behavior and runtime settings in `/config/ironsbot.toml`; keep
only `APP_CONFIG_PATH` and secret values as environment variables.

## Privacy Notes

Do not put private QQ IDs, group IDs, team IDs, meeting links, meeting numbers, account passwords, or tokens into files committed to GitHub.

Use one of these instead:

- a mounted TOML config outside the repository, such as `/config/ironsbot.toml`
- Docker Compose environment variables for secrets and credentials
- Unraid container variables for secrets and credentials
- ignored local files such as `.env.prod`
- Docker / Unraid secret management where available

If a token or meeting link has ever been pushed to a public repository, treat it as exposed and rotate it.

## Links

- Fork repository: [Murmansk5000/IronsBot](https://github.com/Murmansk5000/IronsBot)
- Upstream repository: [Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot)
- Credits and data-tool upstreams: [README acknowledgements](https://github.com/Murmansk5000/IronsBot#%E9%B8%A3%E8%B0%A2)
- Docker Hub image: [murmansk5000/ironsbot](https://hub.docker.com/r/murmansk5000/ironsbot)
- GHCR image: `ghcr.io/murmansk5000/ironsbot`

## License

This image follows the licensing terms of the repository. See `LICENSING.md` in the source repository for details.
