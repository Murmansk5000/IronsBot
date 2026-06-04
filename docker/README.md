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
| `ADMIN_GROUPS` | QQ groups treated as enabled test/management groups by custom plugins. |
| `ADMIN_BYPASS_GROUPS` | Set `true` to let superusers use custom group commands outside enabled groups. Default `false`. |
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
| `SEER_LOGIN_NOTICE` | Notify `SUPERUSERS` by private message when the configured headless Seer login is unavailable after startup. Default `true`. |
| `SEER_LOGIN_NOTICE_MESSAGE` | Message template for the headless Seer login failure notice. Supports `{user_id}` and `{reason}`. |
| `SEER_QUERY_PLAYER_SECTIONS` | Sections shown by custom Mimi ID queries. Use JSON list or comma-separated values. Supported: `basic`, `appearance`, `social`, `collection`, `rank`, `local_rank`, `achievement`, `peak`, `titles`, `pets`, `stages`, `battle`, `raw`. |
| `SEER_QUERY_TEAM_SECTIONS` | Sections shown by custom team queries. Use JSON list or comma-separated values. Supported: `basic`, `resource`, `facilities`, `status`, `logo`, `text`. |
| `SEER_QUERY_RANK_LIMIT` | When querying a Mimi ID, scan this many top entries in the global book and achievement rankings. Default `10000`; set `0` to disable. |
| `SEER_QUERY_RANK_PAGE_SIZE` | Ranking entries fetched per request for Mimi ID rank lookup. Default `100`; the 4481 ranking API should stay at 100 or less. |
| `SEER_QUERY_PEAK_SUBKEY` | Optional peak season ranking subkey for custom Mimi ID queries. Leave empty to read the current season from SeerAPI data; set `YYYYMMDD` manually if season data is unavailable. |
| `SEER_QUERY_LOCAL_RANK` | Enable local rankings among Mimi IDs queried by this bot. Defaults to `true`; tied scores are shown as tied ranks. |
| `SEER_QUERY_LOCAL_RANK_PATH` | SQLite cache file for local queried-player rankings. Defaults to `data/custom_get_seer_info/player_query_cache.sqlite`; peak season metrics are compared only within the same season subkey. |
| `MEETING_NUMBER` | Tencent Meeting number. The plugin generates the meeting link automatically. |
| `MEETING_TEMPLATE` | Reply template. Supports `{meeting_number}`, `{meeting_digits}`, `{meeting_url}`. |
| `MEETING_GROUPS` | QQ groups allowed to trigger meeting replies; `ADMIN_GROUPS` are included automatically. |
| `BILI_GROUPS` | QQ groups receiving Bilibili dynamic updates; `ADMIN_GROUPS` are included automatically. |
| `BILI_DATA_DIR` | Directory for Bilibili cookies and dynamic timestamp cache. Mount `/app/data` for persistence. |
| `STARTUP_NOTICE` | Whether to notify superusers after bot startup. |
| `MSG_AT_TRIGGER` | Whether group text replies triggered by a user should start by mentioning that user. Default `false`. |
| `MSG_PRIVATE_COMMANDS` | Generic private command replies; empty `allowed_user_ids` means `SUPERUSERS` only. |
| `MSG_PRIVATE_SCHEDULES` | Generic scheduled private messages; empty `user_ids` sends to `SUPERUSERS`. |
| `MSG_GROUP_COMMANDS` | Generic group command replies; empty `group_ids` means `ADMIN_GROUPS` only. |
| `MSG_GROUP_SCHEDULES` | Generic scheduled group messages; empty `group_ids` sends to `ADMIN_GROUPS`. |
| `TEAM_GROUPS` | QQ team/guild groups where team shortcut commands are enabled; `ADMIN_GROUPS` are included automatically. |
| `TEAM_IDS` | Team IDs queried by the team group shortcut command. |
| `TEAM_COMMANDS` | Exact team group shortcut commands, default `["战队"]`. |
| `TEAM_RESOURCE_USERS` | QQ users to mention when any configured team resource is below 1000. Use `[123456789]` or `123456789`. |
| `TEAM_RESOURCE_MESSAGE` | Message sent after the mention when team resources are low. |
| `AI_KEY` | DeepSeek API key. Keep it private. |
| `AI_BASE_URL` | OpenAI-compatible API base URL. For relay/NewAPI services, usually use the `/v1` endpoint. |
| `AI_MODEL` | Model name used by the configured AI chat provider. |
| `AI_USERS` | QQ users allowed to use AI chat outside group-wide allowlists. Private chats require this or SUPERUSERS. |
| `AI_GROUPS` | QQ groups whose members may use AI chat by mentioning the bot; `ADMIN_GROUPS` are included automatically. |

List values should use JSON-like syntax, for example:

```env
SUPERUSERS=["123456789"]
ADMIN_GROUPS=[686376929]
ADMIN_BYPASS_GROUPS=false
SEER_LOGIN_NOTICE=true
SEER_LOGIN_NOTICE_MESSAGE="Headless Seer login did not complete.\nMimi ID: {user_id}\nStatus: {reason}\nFeatures that require Mimi login may be unavailable."
SEER_QUERY_PLAYER_SECTIONS=["basic","appearance","social","collection","rank","local_rank","achievement","peak","titles","pets","stages","battle","raw"]
SEER_QUERY_TEAM_SECTIONS=["basic","resource","facilities","status","logo","text"]
SEER_QUERY_RANK_LIMIT=10000
SEER_QUERY_RANK_PAGE_SIZE=100
SEER_QUERY_PEAK_SUBKEY=
SEER_QUERY_LOCAL_RANK=true
SEER_QUERY_LOCAL_RANK_PATH=data/custom_get_seer_info/player_query_cache.sqlite
MEETING_GROUPS=[123456789]
BILI_GROUPS=[123456789,987654321]
MSG_PRIVATE_SCHEDULES=[{"id":"morning","user_ids":[123456789],"hour":8,"minute":30,"message":"早上好"}]
MSG_GROUP_COMMANDS=[{"id":"notice","group_ids":[123456789],"commands":["买资源"],"at_user_ids":[987654321],"message":"出来买资源"},{"id":"seerinfo","group_ids":[123456789],"commands":["xm","xrym","雷小伊","重聚"],"message":"https://seerinfo.yuyuqaq.cn/"}]
TEAM_GROUPS=[123456789]
TEAM_IDS=[1234567,7654321]
TEAM_COMMANDS=["战队"]
TEAM_RESOURCE_USERS=[123456789]
TEAM_RESOURCE_MESSAGE=出来买资源，别逼我求你😡
AI_USERS=[123456789]
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
TEAM_GROUPS=[123456789]
TEAM_IDS=[1234567,7654321]
TEAM_COMMANDS=["战队"]
TEAM_RESOURCE_USERS=[123456789]
TEAM_RESOURCE_MESSAGE=出来买资源，别逼我求你😡
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
