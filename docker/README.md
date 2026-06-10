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
      DATA_SYNC_CONFIG: '{"on_startup":false,"interval_enabled":true,"sources":{"seerapi":{"url":"https://github.com/Murmansk5000/seerapi/releases/download/ironsbot-data-latest/ironsbot-data.sqlite","fingerprint_url":"https://github.com/Murmansk5000/seerapi/releases/download/ironsbot-data-latest/ironsbot-data.sqlite.sha256","interval_minutes":60,"local_path":"data/ironsbot-data.sqlite"},"aliases":{"url":"https://github.com/Murmansk5000/seerapi/releases/download/alias-db-latest/aliases-data.sqlite","fingerprint_url":"https://github.com/Murmansk5000/seerapi/releases/download/alias-db-latest/aliases-data.sqlite.sha256","interval_minutes":60,"local_path":"data/aliases-data.sqlite"}}}'
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
| `FEATURE_SUPERUSER_BYPASS` | Set `true` to let superusers use group features in groups not listed in policy. Default `true`. |
| `BILI_CONFIG` | Bilibili monitor JSON config: monitored UIDs, data directory, history size, default interval, and special interval windows. |
| `MSG_CONFIG` | Generic text reply and scheduled text JSON config: reply line limits, private/group commands, and private/group schedules. |
| `ACTIVITY_CONFIG` | Activity reminder JSON config: enable switch, lead hours, grace minutes, visible-only filter, cache path, and message template. |
| `STARTUP_CONFIG` | Startup notice JSON config: enable switch, message, and extra delay after services are ready. |
| `BOT_RESTART_CONFIG` | Scheduled restart JSON config: enable switch, daily times, grace seconds, and parent-process signaling. |
| `HEADLESS_NOTICE_CONFIG` | Headless Seer login/state notice JSON config: login failure notice, online/offline state notices, and daily reconnect-check times. |
| `SERVER_STATUS_CONFIG` | Server-status broadcast JSON config: broadcast switch, message, and cooldown. |
| `AI_CONFIG` | AI chat and AI intent-action JSON config. `AI_KEY` remains separate and masked. |

Common feature names include `all`, `custom`, `seer`, `image`, `rank`, `meeting`, `text`, `text_push`, `bili_query`, `bili_push`, `activity_query`, `activity_push`, `server_status_query`, `server_status_push`, `team`, `ai_chat`, `ai_intent`, and `admin_notice`. `admin_notice` is only for startup and error notices, and is intentionally not included by `all`. Message actions may use custom feature names such as `activity_link`, `activity_link_push`, or `seerinfo`.

```env
SUPERUSERS=["123456789"]
GROUP_ALIASES={"admin":686376929,"main":123456789}
USER_ALIASES={"owner":123456789}
FEATURE_GROUP_POLICY={"admin":["admin_notice"],"main":["seer","meeting","activity_link","bili_query","bili_push","ai_chat"]}
FEATURE_USER_POLICY={"owner":["all"]}
FEATURE_SUPERUSER_BYPASS=true
BILI_CONFIG={"uids":[1310714247],"storage":{"data_dir":"data/bilibili_monitor","history_max_items":1000},"polling":{"default_minutes":30,"windows":[{"start":"07:00","end":"23:00","minutes":5}]},"push":{"default_mode":"full","link_only_groups":[],"link_only_users":[]},"filters":{"suppress_push_patterns":["恭喜.*获得","记得及时查看私信通知","中奖","抽奖结果"]}}
MSG_CONFIG={"reply":{"default_lines":-1,"min_lines":5,"max_lines":80,"limit_path":"data/message_actions/reply_limits.sqlite"},"group_commands":[{"id":"notice","feature":"activity_link","commands":["link"],"message":"activity link"}],"group_schedules":[{"id":"night","feature":"activity_link_push","hour":23,"minute":0,"message":"good night"}]}
ACTIVITY_CONFIG={"enabled":true,"lead_hours":[11,1],"grace_minutes":15,"only_shown":true,"cache_path":"data/activity_reminder/sent.sqlite","message":"⏰ 本周活动将在约 {lead_hours} 小时后结束\n{activity_list}"}
STARTUP_CONFIG={"enabled":true,"message":"机器人已开启。","delay":0}
BOT_RESTART_CONFIG={"enabled":false,"times":"04:30","grace_seconds":10,"signal_parent":true}
HEADLESS_NOTICE_CONFIG={"login_notice":true,"state_notice":true,"reconnect_check_times":"00:01,00:02"}
SERVER_STATUS_CONFIG={"broadcast":false,"broadcast_message":"赛尔号已经开服了。","broadcast_cooldown_minutes":1440}
AI_CONFIG={"base_url":"https://api.deepseek.com","model":"deepseek-v4-pro","intent_actions_enabled":true,"action_templates":{},"intent_actions":[{"template":"join_team"},{"id":"event_help","template":"keyword_info","keywords":["event","activity"],"intent":"The user is asking about Seer events or activity links."}]}
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
TEAM_RESOURCE_USERS=[123456789]
TEAM_CONFIG={"commands":["战队"],"resource_threshold":1000,"query_timeout_seconds":20,"resource_message":"出来买资源，别逼我求你😡"}
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
