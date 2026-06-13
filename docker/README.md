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
- `team_shortcut`: trigger preconfigured team queries from a short command, intended for team/guild groups.
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
      - ./ironsbot-config:/config:ro
    environment:
      ENVIRONMENT: "prod"
      HOST: "0.0.0.0"
      PORT: "8080"
      APP_CONFIG_PATH: "/config/ironsbot.toml"
      ONEBOT_ACCESS_TOKEN: "change-me"
      SUPERUSERS: '["123456789"]'
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

Create `./ironsbot-config/ironsbot.toml` by copying `config.prod.toml` or
`config.example.toml` from the repository, then edit behavior values there.

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

- Mount a directory containing `ironsbot.toml` to `/config`.
- Set `APP_CONFIG_PATH=/config/ironsbot.toml`.
- Use `config.example.toml` for all fields, defaults, English descriptions, Chinese descriptions, and examples.

```env
APP_CONFIG_PATH=/config/ironsbot.toml
ONEBOT_ACCESS_TOKEN=change-me
SUPERUSERS=["123456789"]
AI_KEY=
HEADLESS_SEER_USER_ID=
HEADLESS_SEER_PASSWORD=
SENDPIC_CNB_TOKEN=
```

| Variable | Description |
| --- | --- |
| `APP_CONFIG_PATH` | Path to the mounted behavior config file, usually `/config/ironsbot.toml`. |
| `ONEBOT_ACCESS_TOKEN` | Token used by NapCat / OneBot client to connect to IronsBot. |
| `SUPERUSERS` | NoneBot superuser QQ list, for example `["123456789"]`. |
| `AI_KEY` | AI chat API key. |
| `HEADLESS_SEER_USER_ID` | Optional Seer account ID for headless login. |
| `HEADLESS_SEER_PASSWORD` | Optional Seer account password as an MD5 value. |
| `SENDPIC_CNB_TOKEN` | Optional CNB backend token for configured sendpic repositories. |
| `ENVIRONMENT`, `DRIVER`, `HOST`, `PORT`, `LOG_LEVEL`, `COMMAND_START` | Deployment runtime knobs. |

Common feature names include `all`, `query`, `seer`, `image`, `rank`, `meeting`, `text`, `text_push`, `bili_query`, `bili_push`, `activity_query`, `activity_push`, `server_status_query`, `server_status_push`, `team`, `ai_chat`, `ai_intent`, and `admin_notice`. `admin_notice` is only for startup and error notices, and is intentionally not included by `all`. Message actions may use feature names such as `activity_link`, `activity_link_push`, or `seerinfo`.

```toml
[feature]
group_aliases = { admin = 686376929, main = 123456789 }
user_aliases = { owner = 123456789 }
group_policy = { admin = ["admin_notice"], main = ["seer", "meeting", "activity_link", "bili_query", "bili_push", "ai_chat"] }
user_policy = { owner = ["all"] }
superuser_bypass = true

[bilibili.push]
groups = { main = { uids = [1310714247], mode = "full" } }
```

## Team Group Shortcut

If you use this Docker image for a Seer team/guild QQ group, you can enable a short group command that expands to one or more fixed team queries.

Example behavior:

```text
User sends: 战队
Bot replies: team info for each configured team ID
```

This is the same kind of output as the built-in `战队<team_id>` query, but the group member does not need to remember the team IDs.

Configure it in `ironsbot.toml`:

```toml
[feature]
group_aliases = { team_group = 123456789 }
group_policy = { team_group = ["team"] }

[seer.team_shortcut]
team_ids = [1234567, 7654321]
resource_users = [123456789]
commands = ["战队"]
resource_threshold = 1000
query_timeout_seconds = 20
resource_message = "出来买资源，别逼我求你😡"
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
