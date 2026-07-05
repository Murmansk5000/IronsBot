<p align="center">
  <img src="https://raw.githubusercontent.com/Murmansk5000/IronsBot/main/icon.png" width="128" alt="IronsBot icon">
</p>

# IronsBot Docker Image

Docker image for [IronsBot](https://github.com/Murmansk5000/IronsBot), a NoneBot2 / OneBot v11 QQ bot focused on Seer game information queries, with explicit plugin loading and Unraid deployment templates.

This image is built from [Murmansk5000/IronsBot](https://github.com/Murmansk5000/IronsBot). User-facing features are loaded from the manifest, while upstream-derived code is retained only where it is needed as data, rendering, protocol, or infrastructure code.

## Images

```text
docker.io/murmansk5000/ironsbot:latest
docker.io/murmansk5000/ironsbot:<base-version>.<revision>
docker.io/murmansk5000/ironsbot:sha-xxxxxxx
ghcr.io/murmansk5000/ironsbot:latest
ghcr.io/murmansk5000/ironsbot:<base-version>.<revision>
ghcr.io/murmansk5000/ironsbot:sha-xxxxxxx
```

`latest` tracks the `main` branch of this repository.

## Version Tags And Changelog

This repository keeps Docker `latest` available, and also publishes extra tags so you can see exactly which build you are running.

- `latest`: the newest `main` build, suitable for normal Unraid updates.
- `<base-version>.<revision>`: IronsBot base version plus this repository's revision.
- `sha-xxxxxxx`: the exact Git commit used to build the image.

For example, `0.6.0.3` means the image is based on IronsBot `0.6.0` with the 3rd revision after that base version.

Recent changes are tracked in the GitHub commit history and in the Unraid template notes. On Docker Hub, check the tag list for the newest project-version tag and `sha-xxxxxxx` tag.

## Included Plugins

- `ai_chat`: chat with DeepSeek through mentions or authorized private messages.
- `sendpic`: reply with fixed local images by command keywords.
- `help`: show only features enabled for the current group or private user.
- `about`: show the current IronsBot project information.
- `meeting`: reply with Tencent Meeting information from APP_CONFIG.
- `messaging`: generic private/group command replies and scheduled messages.
- `bilibili`: monitor Bilibili dynamic updates and send them to configured groups/users.
- `pet_config_reply`: reply when users ask for pet configuration queries that are not supported by this bot.
- `startup_notice`: notify superusers when the bot starts and connects.
- `team_resource_subscription`: query subscribed teams from a short command and remind configured users when resources are low.
- `scheduled_restart`: restart the bot container at configured daily times from APP_CONFIG.

Behavior values such as group IDs, user IDs, team IDs, meeting numbers, feature policies, Bilibili subscriptions, and private reply text belong in a mounted TOML config file. Environment variables are reserved for secrets, credentials, and deployment runtime knobs. They are intentionally not baked into the image.

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
      # Optional: required only when Docker image checks are enabled.
      # - /var/run/docker.sock:/var/run/docker.sock
    environment:
      ENVIRONMENT: "prod"
      HOST: "0.0.0.0"
      PORT: "8080"
      APP_CONFIG_PATH: "/config/ironsbot.toml"
      ONEBOT_ACCESS_TOKEN: "change-me"
      SUPERUSERS: '["1234567890"]'
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

On first startup, if `./ironsbot-config/ironsbot.toml` does not exist, IronsBot
copies `/app/config.example.toml` to that path automatically. Edit the generated
file before production use. Existing config files are never overwritten.

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
  -e SUPERUSERS='["1234567890"]' `
  murmansk5000/ironsbot:latest
```

In this example, `/config/ironsbot.toml` inside the container is
`D:\DockerData\ironsbot\config\ironsbot.toml` on Windows.

Optional Docker image check/update: superusers can send `/重启机器人`;
`/更新镜像` and `/更新Docker` are compatible aliases for the same restart flow.
By default the bot only restarts its process and does not access the Docker
socket. If `check_on_restart` is enabled, the bot checks the target image first;
when a new image exists it starts a one-shot Watchtower updater that pulls the
latest image and recreates the current container. This requires mounting the
Docker Engine socket into the IronsBot container, for example on Unraid/Linux:

```text
/var/run/docker.sock:/var/run/docker.sock
```

Without that socket mount, image checks are skipped and the bot continues to run
normally.

To check for a new image before other startup tasks such as data sync, or before
manual restart commands, enable the explicit switches you need:

```toml
[runtime.docker_update]
check_on_startup = true
check_on_restart = true
watchtower_docker_api_version = "1.40"
```

Both switches are disabled by default. Keep them disabled when running directly
from source on Windows/macOS/Linux without Docker socket access.
Keep `watchtower_docker_api_version = "1.40"` on recent Unraid/Docker Engine
versions if Watchtower reports that client API version 1.25 is too old.

The bot needs a OneBot v11 client such as NapCat. If NapCat and IronsBot are in the same Compose network, configure NapCat reverse WebSocket to:

```text
ws://ironsbot:8080/onebot/v11/ws
```

If NapCat is created separately in Unraid bridge mode, use the Unraid host IP and mapped port instead:

```text
ws://UNRAID_SERVER_IP:8085/onebot/v11/ws
```

The reverse WebSocket token must match `ONEBOT_ACCESS_TOKEN`.

## Configuration

Behavior config is file-based:

- Mount a writable directory to `/config` for first startup, or pre-create
  `ironsbot.toml` before using a read-only mount.
- Set `APP_CONFIG_PATH=/config/ironsbot.toml`.
- Use `config.example.toml` for all fields, defaults, English descriptions, Chinese descriptions, and examples.

When IronsBot creates a missing `ironsbot.toml`, it also writes
`ironsbot.env.example` next to it. This is only a sample for secrets and
runtime environment variables. Real env files such as `ironsbot.env.prod` are
not created automatically; copy the example, fill your token / superusers /
keys, and reference it from Compose if you use `env_file`.

If `APP_CONFIG_PATH` is not set, IronsBot falls back to
`config/ironsbot.toml` in the current working directory. Missing config files
are created from `config.example.toml` automatically on any operating system,
as long as the target directory is writable. Relative `data/` and `logs/`
paths also live under the current working directory.

```env
APP_CONFIG_PATH=/config/ironsbot.toml
ONEBOT_ACCESS_TOKEN=change-me
SUPERUSERS=["1234567890"]
AI_KEY=
HEADLESS_SEER_USER_ID=
HEADLESS_SEER_PASSWORD=
SENDPIC_CNB_TOKEN=
```

| Variable | Description |
| --- | --- |
| `APP_CONFIG_PATH` | Path to the mounted behavior config file, usually `/config/ironsbot.toml`. |
| `ONEBOT_ACCESS_TOKEN` | Token used by NapCat / OneBot client to connect to IronsBot. |
| `SUPERUSERS` | NoneBot superuser QQ list, for example `["1234567890"]`. |
| `AI_KEY` | AI chat API key. |
| `HEADLESS_SEER_USER_ID` | Optional Seer account ID for headless login. |
| `HEADLESS_SEER_PASSWORD` | Optional Seer account password as an MD5 value. |
| `SENDPIC_CNB_TOKEN` | Optional CNB backend token for configured sendpic repositories. |
| `ENVIRONMENT`, `DRIVER`, `HOST`, `PORT`, `LOG_LEVEL`, `COMMAND_START` | Deployment runtime knobs. |

Feature names are used in `[feature.group_policy]` and
`[feature.user_policy]`:

| feature | Meaning |
| --- | --- |
| `all` | Most features except `admin_notice`; admin notices are explicit. |
| `query` | Common query bundle: Seer queries, image, rank, Bilibili query, activity query, server status query. |
| `seer` | All Seer query sub-features. |
| `seer_player` | Mimi ID/player info, collection/peak/Autocard follow-up replies. |
| `seer_team` | Team ID query. |
| `seer_pet` | Pet, skill, soul mark, illustration, and skin queries. |
| `seer_mintmark` | Mintmark, mintmark series, gem, and mintmark stat ranks. |
| `seer_equipment` | Suit, equipment part, and title queries. |
| `seer_type` | Type matchup and abnormal status queries. |
| `seer_peak` | Peak pools, votes, peak ranks, and pet usage ranks. |
| `seer_autocard` | Autocard data and Autocard global rank. |
| `seer_rank` / `rank` | Global ranks, sample ranks, rank/sample status, and rank cache commands. |
| `seer_data` | Weekly preview, data version, and data tools. |
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
| `ai_intent` | AI intent dispatch for team recommendation, Fire manual, and similar actions. |
| `fire_manual` | "手册" AI intent and Fire manual links appended to proactive pushes. |
| `admin_notice` | Startup/error/admin notices; not included by `all`. |

Message actions may also use feature names such as `web_activity_link`,
`web_activity_push`, or `seerinfo`.

```toml
[feature]
superuser_bypass = true

[feature.group_aliases]
admin = 123456789
main = 987654321

[feature.user_aliases]
owner = 1234567890

[feature.group_policy]
admin = ["admin_notice"]
main = ["seer", "meeting", "web_activity_link", "bili_query", "bili_push", "ai_chat", "fire_manual"]

[feature.user_policy]
owner = ["all"]

[bilibili.push]

[bilibili.push.groups.main]
uids = [1310714247]
mode = "full"
```

## Team Resource Subscription

If you use this Docker image for a Seer team/guild QQ group, you can subscribe that group to one or more teams. The same subscription lets members query those teams with a short command and lets the bot remind configured users when team resources are low.

Example behavior:

```text
User sends: 战队
Bot replies: team info for each configured team ID
```

This is the same kind of output as the built-in `战队<team_id>` query, but the group member does not need to remember the team IDs.

Configure it in `ironsbot.toml`:

```toml
[feature]

[feature.group_aliases]
example = 987654321

[feature.user_aliases]
owner = 1234567890

[feature.group_policy]
example = ["team_resource_subscription"]

[seer.team_resource]
times = ["23:00"]
commands = ["战队"]
query_timeout_seconds = 20
resource_line = "查到了战队 {team_name}（{team_id}）资源是 {resource}，低于阈值 {threshold}。"
resource_message = "出来买资源，别逼我求你😡"

[[seer.team_resource.subscriptions]]
group = "example"
team_ids = [1234567, 7654321]
threshold = 1000
at_users = ["owner"]
```

Keep real QQ group IDs and team IDs in a mounted config file outside the repository, such as an Unraid appdata directory. Do not commit them to GitHub.

## Unraid

This repository includes a Community Applications-ready Unraid template:

- IronsBot template: `templates/ironsbot.xml`
- CA profile: `ca_profile.xml`

Template URLs:

```text
https://raw.githubusercontent.com/Murmansk5000/IronsBot/main/templates/ironsbot.xml
```

The Unraid template exposes a minimal variable set and mounts a config directory. Put behavior settings in `/config/ironsbot.toml`; keep only tokens, credentials, and deployment runtime knobs as environment variables.

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
- Docker Hub image: [murmansk5000/ironsbot](https://hub.docker.com/r/murmansk5000/ironsbot)
- GHCR image: `ghcr.io/murmansk5000/ironsbot`

## License

This image follows the licensing terms of the repository. See `LICENSING.md` in the source repository for details.
