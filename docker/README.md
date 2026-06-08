<p align="center">
  <img src="https://raw.githubusercontent.com/Murmansk5000/IronsBot/main/icon.png" width="128" alt="IronsBot icon">
</p>

# IronsBot Custom Docker Image

Custom Docker image for [IronsBot](https://github.com/Murmansk5000/IronsBot), a NoneBot2 / OneBot v11 QQ bot focused on Seer game information queries, with personal custom plugins and Unraid deployment templates.

This image is built from [Murmansk5000/IronsBot](https://github.com/Murmansk5000/IronsBot). User-facing features are provided by custom plugins, while upstream IronsBot code is retained only where it is needed as data, rendering, protocol, or infrastructure code.

## Images

```text
docker.io/murmansk5000/ironsbot:latest
docker.io/murmansk5000/ironsbot:<base-version>.<custom-revision>
docker.io/murmansk5000/ironsbot:sha-xxxxxxx
ghcr.io/murmansk5000/ironsbot:latest
ghcr.io/murmansk5000/ironsbot:<base-version>.<custom-revision>
ghcr.io/murmansk5000/ironsbot:sha-xxxxxxx
```

`latest` tracks the `main` branch of this repository.

## Version Tags And Changelog

This repository keeps Docker `latest` available, and also publishes extra tags so you can see exactly which custom build you are running.

- `latest`: the newest `main` build, suitable for normal Unraid updates.
- `<base-version>.<custom-revision>`: IronsBot base version plus this repository's custom revision.
- `sha-xxxxxxx`: the exact Git commit used to build the image.

For example, `0.6.0.3` means the image is based on IronsBot `0.6.0` with the 3rd custom revision after that base version.

Recent changes are tracked in the GitHub commit history and in the Unraid template notes. On Docker Hub, check the tag list for the newest upstream-based version tag and `sha-xxxxxxx` tag.

## Included Custom Plugins

- `ai_chat`: chat with DeepSeek through mentions or authorized private messages.
- `custom_sendpic`: reply with fixed local images by command keywords.
- `custom_help`: show only features enabled for the current group or private user.
- `custom_about`: show the current IronsBot project information.
- `meeting_reply`: reply with Tencent Meeting information from environment variables.
- `message_actions`: generic private/group command replies and scheduled messages.
- `bilibili_monitor`: monitor Bilibili dynamic updates and send them to configured groups/users.
- `pet_config_reply`: reply when users ask for pet configuration queries that are not supported by this bot.
- `startup_notice`: notify superusers when the bot starts and connects.
- `team_shortcut`: trigger preconfigured team queries from a short command, intended for team/guild groups.
- `scheduled_restart`: restart the bot container at configured daily times through environment variables.

All group IDs, user IDs, team IDs, tokens, meeting numbers, and private reply text should be configured at runtime through environment variables or an Unraid template. They are intentionally not baked into the image.

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
    environment:
      ENVIRONMENT: "prod"
      HOST: "0.0.0.0"
      PORT: "8080"
      ONEBOT_ACCESS_TOKEN: "change-me"
      SUPERUSERS: '["123456789"]'
      DB_SYNC_ON_STARTUP: "false"
      DB_SYNC_INTERVAL_ENABLED: "true"
      SEERAPI_SYNC_URL: "https://github.com/SeerAPI/api-data/releases/download/latest/seerapi-data.sqlite"
      SEERAPI_FINGERPRINT_URL: "https://github.com/SeerAPI/api-data/releases/download/latest/seerapi-data.sqlite.sha256"
      SEERAPI_LOCAL_PATH: "data/seerapi-data.sqlite"
      ALIAS_SYNC_URL: "https://github.com/Nattsu39/ironsbot/releases/download/alias-db-latest/aliases-data.sqlite"
      ALIAS_FINGERPRINT_URL: "https://github.com/Nattsu39/ironsbot/releases/download/alias-db-latest/aliases-data.sqlite.sha256"
      ALIAS_LOCAL_PATH: "data/aliases-data.sqlite"
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

The bot needs a OneBot v11 client such as NapCat. If NapCat and IronsBot are in the same Compose network, configure NapCat reverse WebSocket to:

```text
ws://ironsbot:8080/onebot/v11/ws
```

If NapCat is created separately in Unraid bridge mode, use the Unraid host IP and mapped port instead:

```text
ws://UNRAID_SERVER_IP:8085/onebot/v11/ws
```

The reverse WebSocket token must match `ONEBOT_ACCESS_TOKEN`.

## Common Environment Variables

| Variable | Description |
| --- | --- |
| `ONEBOT_ACCESS_TOKEN` | Token used by NapCat / OneBot client to connect to IronsBot. |
| `SUPERUSERS` | NoneBot superuser QQ list, for example `["123456789"]`. |
| `GROUP_ALIASES` | JSON object mapping friendly group names to QQ group IDs. |
| `USER_ALIASES` | JSON object mapping friendly user names to QQ IDs. |
| `FEATURE_GROUP_POLICY` | JSON object mapping group aliases or numeric group IDs to enabled features. |
| `FEATURE_USER_POLICY` | JSON object mapping user aliases or numeric QQ IDs to enabled private/push features. |
| `FEATURE_SUPERUSER_BYPASS` | Set `true` to let superusers use group features in groups not listed in policy. Default `false`. |
| `AI_ACTION_TEMPLATES` | Optional reusable AI action templates. Built-ins include `join_team` and `keyword_info`. |
| `AI_INTENT_ACTIONS` | AI-gated actions. Each item can use `template`, `keywords`, `intent`, and an action such as `team_shortcut`, `message`, or `ai_reply`. |

Common feature names include `all`, `custom`, `seer`, `image`, `rank`, `meeting`, `text`, `text_push`, `bili_query`, `bili_push`, `activity_query`, `activity_push`, `server_status_query`, `server_status_push`, `team`, `ai`, `ai_intent`, and `admin_notice`. `admin_notice` is only for startup and error notices, and is intentionally not included by `all`. Message actions may use custom feature names such as `activity_link`, `activity_link_push`, or `seerinfo`.

```env
SUPERUSERS=["123456789"]
GROUP_ALIASES={"admin":686376929,"main":123456789}
USER_ALIASES={"owner":123456789}
FEATURE_GROUP_POLICY={"admin":["admin_notice"],"main":["seer","meeting","activity_link","bili_query","bili_push","ai"]}
FEATURE_USER_POLICY={"owner":["all"]}
FEATURE_SUPERUSER_BYPASS=false
BILI_UIDS=[1310714247]
MSG_GROUP_COMMANDS=[{"id":"notice","feature":"activity_link","commands":["link"],"message":"activity link"}]
MSG_GROUP_SCHEDULES=[{"id":"night","feature":"activity_link_push","hour":23,"minute":0,"message":"good night"}]
AI_INTENT_ACTIONS=[{"template":"join_team"},{"id":"event_help","template":"keyword_info","keywords":["event","activity"],"intent":"The user is asking about Seer events or activity links."}]
```

## Team Group Shortcut

If you use this Docker image for a Seer team/guild QQ group, you can enable a short group command that expands to one or more fixed team queries.

Example behavior:

```text
User sends: 战队
Bot replies: team info for each configured team ID
```

This is the same kind of output as the built-in `战队<team_id>` query, but the group member does not need to remember the team IDs.

Configure it at runtime:

```env
FEATURE_GROUP_POLICY={"team_group":["team"]}
GROUP_ALIASES={"team_group":123456789}
TEAM_IDS=[1234567,7654321]
TEAM_COMMANDS=["战队"]
TEAM_RESOURCE_USERS=[123456789]
TEAM_RESOURCE_MESSAGE=出来买资源，别逼我求你😡
```

Keep real QQ group IDs and team IDs in Docker Compose, Unraid variables, or an ignored `.env.prod` file. Do not commit them to GitHub.

## Unraid

This repository includes a Community Applications-ready Unraid template:

- IronsBot template: `templates/ironsbot.xml`
- CA profile: `ca_profile.xml`

Template URLs:

```text
https://raw.githubusercontent.com/Murmansk5000/IronsBot/main/templates/ironsbot.xml
```

The Unraid template exposes the runtime variables as editable fields, including group IDs, team shortcut IDs, meeting number, OneBot token, and Bilibili monitor settings.

## Privacy Notes

Do not put private QQ IDs, group IDs, team IDs, meeting links, meeting numbers, account passwords, or tokens into files committed to GitHub.

Use one of these instead:

- Docker Compose environment variables
- Unraid container variables
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
