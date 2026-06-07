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
| `ADMIN_GROUPS` | QQ groups treated as enabled test/management groups by custom plugins. |
| `ADMIN_BYPASS_GROUPS` | Set `true` to let superusers use custom group commands outside enabled groups. Default `false`. |
| `CUSTOM_FEATURE_GROUPS` | QQ groups where general custom features are enabled, such as extended Seer queries, rankings, Autocard, fixed images, manual Bilibili dynamic queries, soon-ending activities, and ordinary `开服了吗`. `ADMIN_GROUPS` are included automatically. Meeting, text/link replies, AI chat, Bilibili push targets, team shortcuts, and admin server status use their own variables. |
| `CUSTOM_FEATURE_USERS` | QQ users allowed to use general custom features in private chat. `SUPERUSERS` are included automatically. |
| `CUSTOM_PUSH_GROUPS` | Extra QQ groups receiving custom group broadcasts, separate from command permissions. These are added to feature-specific push targets such as `BILI_GROUPS`, `ACTIVITY_REMINDER_GROUPS`, `SERVER_STATUS_BROADCAST_GROUPS`, and `MSG_GROUP_SCHEDULES`. |
| `CUSTOM_PUSH_EXCLUDE_GROUPS` | QQ groups that must not receive custom group broadcasts, even when listed in feature-specific push targets or `ADMIN_GROUPS`. This does not affect manual commands. |
| `BOT_RESTART_ENABLED` | Enable scheduled bot container restart. The bot exits at the configured time; Docker/Unraid restart policy should start it again. |
| `BOT_RESTART_TIMES` | Daily restart times in Asia/Shanghai time. Use comma-separated `HH:MM` values, for example `04:30,16:10,23:55`. JSON lists like `["04:30","16:10"]` are also accepted. |
| `BOT_RESTART_GRACE_SECONDS` | Seconds to wait after the restart job triggers before terminating the bot process. |
| `BOT_RESTART_SIGNAL_PARENT` | Signal the parent gunicorn process instead of only the worker. Keep `true` in Docker/Unraid so the whole container exits and restarts. |
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
| `HEADLESS_SEER_HEARTBEAT_INTERVAL` | Seconds between headless client heartbeat checks. Lower values detect dropped game connections faster. |
| `HEADLESS_SEER_RECONNECT_RETRIES` | Headless client reconnect retry count. Use `-1` for infinite retries, `0` to disable automatic reconnect, or a positive number for limited retries. |
| `HEADLESS_SEER_RECONNECT_DELAY` | Initial seconds to wait before the headless client reconnects. |
| `HEADLESS_SEER_RECONNECT_DELAY_MAX` | Maximum reconnect backoff seconds for the headless client. |
| `SEER_LOGIN_NOTICE` | Notify `SUPERUSERS` by private message when the configured headless Seer login is unavailable after startup. Default `true`. |
| `SEER_LOGIN_NOTICE_MESSAGE` | Message template for the headless Seer login failure notice. Supports `{user_id}` and `{reason}`. |
| `HEADLESS_STATE_NOTICE` | Notify `SUPERUSERS` when the headless Mimi login changes between online and offline. Normal maintenance windows are muted. |
| `HEADLESS_STATE_OFFLINE_MESSAGE` | Message template for headless offline state changes. Supports `{user_id}`, `{reason}`, and `{source}`. |
| `HEADLESS_STATE_ONLINE_MESSAGE` | Message template for headless online state changes. Supports `{user_id}` and `{source}`. |
| `HEADLESS_RECONNECT_CHECK_TIMES` | Daily Asia/Shanghai times to check headless status and reconnect if offline. Use comma-separated `HH:MM` values or JSON list; default `00:01,00:02`. |
| `SEER_QUERY_PLAYER_SECTIONS` | Sections shown by custom Mimi ID queries. Use JSON list or comma-separated values. Supported: `basic`, `appearance`, `social`, `collection`, `rank`, `local_rank`, `achievement`, `peak`, `titles`, `pets`, `stages`, `battle`, `raw`. |
| `SEER_QUERY_TEAM_SECTIONS` | Sections shown by custom team queries. Use JSON list or comma-separated values. Supported: `basic`, `resource`, `facilities`, `status`, `logo`, `text`. |
| `SEER_QUERY_PLAYER_RATE_LIMIT_SECONDS` | Seconds between Mimi ID queries per normal QQ user. `SUPERUSERS` are exempt. Default `60`; set `0` to disable. |
| `SEER_QUERY_PLAYER_FAILURE_RATE_LIMIT_SECONDS` | Seconds a normal QQ user must wait after a failed Mimi ID query. `SUPERUSERS` are exempt. Default `10`; set `0` to disable. |
| `SEER_QUERY_RANK_LIMIT` | When querying a Mimi ID, scan this many top entries in the global book and achievement rankings. Default `10000`; set `0` to disable. |
| `SEER_QUERY_RANK_PAGE_SIZE` | Ranking entries fetched per request for Mimi ID rank lookup. Default `100`; the 4481 ranking API should stay at 100 or less. |
| `SEER_QUERY_PEAK_SUBKEY` | Optional peak season ranking subkey for custom Mimi ID queries. Leave empty to read the current season from SeerAPI data; set `YYYYMMDD` manually if season data is unavailable. |
| `SEER_QUERY_LOCAL_RANK` | Enable local rankings among Mimi IDs queried by this bot. Defaults to `true`; tied scores are shown as tied ranks. |
| `SEER_QUERY_LOCAL_RANK_PATH` | SQLite cache file for local queried-player rankings. Defaults to `data/custom_get_seer_info/player_query_cache.sqlite`; peak season metrics are compared only within the same season subkey. |
| `SEER_QUERY_SKIN_PRICE` | Append official skin diamond price data to custom skin/illustration queries. Defaults to `true`. |
| `SEER_QUERY_SKIN_PRICE_CACHE_TTL_SECONDS` | Seconds before the downloaded skin price config cache is considered stale. Defaults to `86400`. |
| `SEER_QUERY_SKIN_PRICE_CACHE_PATH` | JSON cache file for parsed official skin price data. Defaults to `data/custom_get_seer_info/skin_price_cache.json`. |
| `SEER_QUERY_MINTMARK_QUALITY_PATH` | Optional parsed official `mintmark.json` path. When set, custom countermark stat rankings use its `Quality` field as the angle count; otherwise they infer angles from base attributes. |
| `SEER_QUERY_CONFIG_PACKAGE_BASE_URL` | Official Unity ConfigPackage base URL used for skin prices and other custom config parsing. |
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
| `AI_INTENT_ACTIONS_ENABLED` | Enable AI-gated message actions. Messages are first filtered by keywords, then AI decides whether to run the configured action. |
| `AI_INTENT_ACTIONS` | JSON list of AI intent actions. Supported actions: `message`, `team_shortcut`. The default `join_team` action watches for `战队`, asks AI whether the sender wants to join a team, and sends the configured `TEAM_IDS` team info when matched. |
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
CUSTOM_FEATURE_GROUPS=[686376929]
CUSTOM_FEATURE_USERS=[]
CUSTOM_PUSH_GROUPS=[]
CUSTOM_PUSH_EXCLUDE_GROUPS=[]
BOT_RESTART_ENABLED=false
BOT_RESTART_TIMES=04:30
BOT_RESTART_GRACE_SECONDS=10
BOT_RESTART_SIGNAL_PARENT=true
SEER_LOGIN_NOTICE=true
SEER_LOGIN_NOTICE_MESSAGE="Headless Seer login did not complete.\nMimi ID: {user_id}\nStatus: {reason}\nFeatures that require Mimi login may be unavailable."
HEADLESS_STATE_NOTICE=true
HEADLESS_STATE_OFFLINE_MESSAGE="Headless Mimi login went offline.\nMimi ID: {user_id}\nStatus: {reason}\nSource: {source}"
HEADLESS_STATE_ONLINE_MESSAGE="Headless Mimi login recovered.\nMimi ID: {user_id}\nSource: {source}"
HEADLESS_RECONNECT_CHECK_TIMES=00:01,00:02
SEER_QUERY_PLAYER_RATE_LIMIT_SECONDS=60
SEER_QUERY_PLAYER_FAILURE_RATE_LIMIT_SECONDS=10
SEER_QUERY_PLAYER_SECTIONS=["basic","appearance","social","collection","rank","local_rank","achievement","peak","titles","pets","stages","battle","raw"]
SEER_QUERY_TEAM_SECTIONS=["basic","resource","facilities","status","logo","text"]
SEER_QUERY_RANK_LIMIT=10000
SEER_QUERY_RANK_PAGE_SIZE=100
SEER_QUERY_PEAK_SUBKEY=
SEER_QUERY_LOCAL_RANK=true
SEER_QUERY_LOCAL_RANK_PATH=data/custom_get_seer_info/player_query_cache.sqlite
SEER_QUERY_SKIN_PRICE=true
SEER_QUERY_SKIN_PRICE_CACHE_TTL_SECONDS=86400
SEER_QUERY_SKIN_PRICE_CACHE_PATH=data/custom_get_seer_info/skin_price_cache.json
SEER_QUERY_MINTMARK_QUALITY_PATH=
SEER_QUERY_CONFIG_PACKAGE_BASE_URL=https://newseer.61.com/Assets/StandaloneWindows64/ConfigPackage/
MEETING_GROUPS=[123456789]
BILI_GROUPS=[123456789,987654321]
MSG_PRIVATE_SCHEDULES=[{"id":"morning","user_ids":[123456789],"hour":8,"minute":30,"message":"早上好"}]
MSG_GROUP_COMMANDS=[{"id":"notice","group_ids":[123456789],"commands":["买资源"],"at_user_ids":[987654321],"message":"出来买资源"},{"id":"seerinfo","group_ids":[123456789],"commands":["xm","xrym","雷小伊","重聚"],"message":"https://seerinfo.yuyuqaq.cn/"}]
TEAM_GROUPS=[123456789]
TEAM_IDS=[1234567,7654321]
TEAM_COMMANDS=["战队"]
TEAM_RESOURCE_USERS=[123456789]
TEAM_RESOURCE_MESSAGE=出来买资源，别逼我求你😡
AI_INTENT_ACTIONS_ENABLED=true
AI_INTENT_ACTIONS=[{"id":"join_team","keywords":["战队"],"action":"team_shortcut","intent":"Judge whether the QQ group message means the sender wants to join, apply for, or find a Seer team/guild. Answer yes only when the sender is asking to join a team, asking whether they can enter the team, or asking for the team info for joining. Answer no when the message only queries team data, discusses team resources, asks someone to buy resources, or casually mentions teams.","include_team_resource_notice":false}]
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
