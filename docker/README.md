<p align="center">
  <img src="https://raw.githubusercontent.com/Murmansk5000/IronsBot/main/icon.png" width="128" alt="IronsBot icon">
</p>

# IronsBot Custom Docker Image

Custom Docker image for [IronsBot](https://github.com/Murmansk5000/IronsBot), a NoneBot2 / OneBot v11 QQ bot focused on Seer game information queries, with personal custom plugins and Unraid deployment templates.

This image is based on the upstream project [Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot). The fork keeps upstream updates while adding local custom plugins and deployment conveniences.

## Images

```text
docker.io/murmansk5000/ironsbot:latest
docker.io/murmansk5000/ironsbot:<upstream-version>.<fork-revision>
docker.io/murmansk5000/ironsbot:sha-xxxxxxx
ghcr.io/murmansk5000/ironsbot:latest
ghcr.io/murmansk5000/ironsbot:<upstream-version>.<fork-revision>
ghcr.io/murmansk5000/ironsbot:sha-xxxxxxx
```

`latest` tracks the `main` branch of this fork.

## Version Tags And Changelog

This fork keeps Docker `latest` available, and also publishes extra tags so you can see exactly which custom build you are running.

- `latest`: the newest `main` build, suitable for normal Unraid updates.
- `<upstream-version>.<fork-revision>`: upstream IronsBot version plus this fork's custom revision.
- `sha-xxxxxxx`: the exact Git commit used to build the image.

For example, `0.5.1.26` means the image is based on upstream `0.5.1` with the 26th fork revision after upstream tag `v0.5.1`. If upstream later becomes `0.5.2` or `0.6.0`, this fork will publish tags such as `0.5.2.1` or `0.6.0.1`.

Recent changes are tracked in the GitHub commit history and in the Unraid template notes. On Docker Hub, check the tag list for the newest upstream-based version tag and `sha-xxxxxxx` tag.

## Included Custom Plugins

- `ai_chat`: chat with DeepSeek through mentions or authorized private messages.
- `sendpic_custom`: reply with fixed local images by command keywords.
- `meeting_reply`: reply with Tencent Meeting information from environment variables.
- `message_actions`: generic private/group command replies and scheduled messages.
- `bilibili_monitor`: monitor Bilibili dynamic updates and send them to configured groups/users.
- `pet_config_reply`: reply when users ask for pet configuration queries that are not supported by this bot.
- `startup_notice`: notify superusers when the bot starts and connects.
- `team_shortcut`: trigger preconfigured team queries from a short command, intended for team/guild groups.

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
| `DB_SYNC_ON_STARTUP` | Whether to sync registered databases automatically on startup. Default is `false`; superusers can send `更新数据` or `数据更新`. |
| `DB_SYNC_INTERVAL_ENABLED` | Whether to run scheduled database sync jobs. Default is `true`; set `false` for manual-only updates. |
| `SEERAPI_SYNC_URL` | Remote SeerAPI database URL. |
| `SEERAPI_FINGERPRINT_URL` | SHA256 fingerprint URL for SeerAPI database updates. |
| `SEERAPI_LOCAL_PATH` | Local SeerAPI database cache/fallback path. Use `/app/data` persistence for Docker. |
| `ALIAS_SYNC_URL` | Remote alias database URL. |
| `ALIAS_FINGERPRINT_URL` | SHA256 fingerprint URL for alias database updates. |
| `ALIAS_LOCAL_PATH` | Local alias database cache/fallback path. Use `/app/data` persistence for Docker. |
| `HEADLESS_SEER_USER_ID` | Optional Seer account ID for features that require login. |
| `HEADLESS_SEER_PASSWORD` | Optional MD5 password for the headless Seer client. |
| `MEETING_REPLY_NUMBER` | Tencent Meeting number. The plugin generates the meeting link automatically. |
| `MEETING_REPLY_TEMPLATE` | Reply template. Supports `{meeting_number}`, `{meeting_digits}`, `{meeting_url}`. |
| `MEETING_REPLY_GROUPS` | QQ groups allowed to trigger meeting replies. |
| `BILIBILI_MONITOR_TARGET_GROUP_IDS` | QQ groups receiving Bilibili dynamic updates. |
| `BILIBILI_MONITOR_ADMIN_UIDS` | QQ users allowed to run Bilibili monitor admin commands. |
| `BILIBILI_MONITOR_DATA_DIR` | Directory for Bilibili cookies and dynamic timestamp cache. Mount `/app/data` for persistence. |
| `STARTUP_NOTICE_ENABLED` | Whether to notify superusers after bot startup. |
| `STARTUP_NOTICE_USERS` | Extra QQ users receiving startup notices. |
| `MESSAGE_ACTION_MENTION_GROUP_TRIGGER_USER` | Whether group text replies triggered by a user should start by mentioning that user. Default `false`. |
| `MESSAGE_ACTION_PRIVATE_COMMANDS` | Generic private command replies. |
| `MESSAGE_ACTION_PRIVATE_SCHEDULES` | Generic scheduled private messages. |
| `MESSAGE_ACTION_GROUP_COMMANDS` | Generic group command replies, with optional `at_user_ids`. |
| `MESSAGE_ACTION_GROUP_SCHEDULES` | Generic scheduled group messages, with optional `at_user_ids`. |
| `TEAM_SHORTCUT_GROUP_IDS` | QQ team/guild groups where team shortcut commands are enabled. |
| `TEAM_SHORTCUT_TEAM_IDS` | Team IDs queried by the team group shortcut command. |
| `TEAM_SHORTCUT_COMMANDS` | Exact team group shortcut commands, default `["战队"]`. |
| `TEAM_SHORTCUT_RESOURCE_NOTICE_USER_IDS` | QQ users to mention when any configured team resource is below 1000. Use `[123456789]` or `123456789`. |
| `TEAM_SHORTCUT_RESOURCE_NOTICE_MESSAGE` | Message sent after the mention when team resources are low. |
| `AI_CHAT_API_KEY` | DeepSeek API key. Keep it private. |
| `AI_CHAT_BASE_URL` | OpenAI-compatible API base URL. For relay/NewAPI services, usually use the `/v1` endpoint. |
| `AI_CHAT_MODEL` | Model name used by the configured AI chat provider. |
| `AI_CHAT_ALLOWED_USER_IDS` | QQ users allowed to use AI chat outside group-wide allowlists. Private chats require this, admin access, or SUPERUSERS. |
| `AI_CHAT_ALLOWED_GROUP_IDS` | QQ groups whose members may use AI chat by mentioning the bot. Empty means no group-wide access. |

List values should use JSON-like syntax, for example:

```env
SUPERUSERS=["123456789"]
MEETING_REPLY_GROUPS=[123456789]
BILIBILI_MONITOR_TARGET_GROUP_IDS=[123456789,987654321]
MESSAGE_ACTION_PRIVATE_SCHEDULES=[{"id":"morning","user_ids":[123456789],"hour":8,"minute":30,"message":"早上好"}]
MESSAGE_ACTION_GROUP_COMMANDS=[{"id":"notice","group_ids":[123456789],"commands":["买资源"],"at_user_ids":[987654321],"message":"出来买资源"}]
TEAM_SHORTCUT_GROUP_IDS=[123456789]
TEAM_SHORTCUT_TEAM_IDS=[1234567,7654321]
TEAM_SHORTCUT_COMMANDS=["战队"]
TEAM_SHORTCUT_RESOURCE_NOTICE_USER_IDS=[123456789]
TEAM_SHORTCUT_RESOURCE_NOTICE_MESSAGE=出来买资源，别逼我求你😡
AI_CHAT_ALLOWED_USER_IDS=[123456789]
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
TEAM_SHORTCUT_GROUP_IDS=[123456789]
TEAM_SHORTCUT_TEAM_IDS=[1234567,7654321]
TEAM_SHORTCUT_COMMANDS=["战队"]
TEAM_SHORTCUT_RESOURCE_NOTICE_USER_IDS=[123456789]
TEAM_SHORTCUT_RESOURCE_NOTICE_MESSAGE=出来买资源，别逼我求你😡
```

Keep real QQ group IDs and team IDs in Docker Compose, Unraid variables, or an ignored `.env.prod` file. Do not commit them to GitHub.

## Unraid

This fork includes a Community Applications-ready Unraid template:

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
