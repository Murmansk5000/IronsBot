# IronsBot Custom Docker Image

Custom Docker image for [IronsBot](https://github.com/Murmansk5000/IronsBot), a NoneBot2 / OneBot v11 QQ bot focused on Seer game information queries, with personal custom plugins and Unraid deployment templates.

This image is based on the upstream project [Nattsu39/IronsBot](https://github.com/Nattsu39/IronsBot). The fork keeps upstream updates while adding local custom plugins and deployment conveniences.

## Images

```text
docker.io/murmansk5000/ironsbot:latest
ghcr.io/murmansk5000/ironsbot:latest
```

`latest` tracks the `main` branch of this fork.

## Included Custom Plugins

- `sendpic_custom`: reply with fixed local images by command keywords.
- `meeting_reply`: reply with Tencent Meeting information from environment variables.
- `event_link`: reply or schedule-send event links to configured groups/users.
- `bilibili_monitor`: monitor Bilibili dynamic updates and send them to configured groups/users.
- `pet_config_reply`: reply when users ask for pet configuration queries that are not supported by this bot.

All group IDs, user IDs, tokens, meeting numbers, and private reply text should be configured at runtime through environment variables or an Unraid template. They are intentionally not baked into the image.

## Quick Start With Docker Compose

Create a `docker-compose.yml` and adjust the values for your own environment:

```yaml
services:
  ironsbot:
    image: murmansk5000/ironsbot:latest
    container_name: ironsbot
    ports:
      - "8085:8080"
    environment:
      ENVIRONMENT: "prod"
      HOST: "0.0.0.0"
      PORT: "8080"
      ONEBOT_ACCESS_TOKEN: "change-me"
      SUPERUSERS: '["123456789"]'
      SEERAPI_SYNC_URL: "https://github.com/SeerAPI/api-data/releases/download/latest/seerapi-data.sqlite"
      SEERAPI_FINGERPRINT_URL: "https://github.com/SeerAPI/api-data/releases/download/latest/seerapi-data.sqlite.sha256"
      ALIAS_SYNC_URL: "https://github.com/Nattsu39/ironsbot/releases/download/alias-db-latest/aliases-data.sqlite"
      ALIAS_FINGERPRINT_URL: "https://github.com/Nattsu39/ironsbot/releases/download/alias-db-latest/aliases-data.sqlite.sha256"
    restart: always
```

The bot needs a OneBot v11 client such as NapCat. Configure NapCat reverse WebSocket to:

```text
ws://ironsbot:8080/onebot/v11/ws
```

The token must match `ONEBOT_ACCESS_TOKEN`.

## Common Environment Variables

| Variable | Description |
| --- | --- |
| `ONEBOT_ACCESS_TOKEN` | Token used by NapCat / OneBot client to connect to IronsBot. |
| `SUPERUSERS` | NoneBot superuser QQ list, for example `["123456789"]`. |
| `SEERAPI_SYNC_URL` | Remote SeerAPI database URL. |
| `SEERAPI_FINGERPRINT_URL` | SHA256 fingerprint URL for SeerAPI database updates. |
| `ALIAS_SYNC_URL` | Remote alias database URL. |
| `ALIAS_FINGERPRINT_URL` | SHA256 fingerprint URL for alias database updates. |
| `HEADLESS_SEER_USER_ID` | Optional Seer account ID for features that require login. |
| `HEADLESS_SEER_PASSWORD` | Optional MD5 password for the headless Seer client. |
| `MEETING_REPLY_NUMBER` | Tencent Meeting number. The plugin generates the meeting link automatically. |
| `MEETING_REPLY_TEMPLATE` | Reply template. Supports `{meeting_number}`, `{meeting_digits}`, `{meeting_url}`. |
| `MEETING_REPLY_GROUPS` | QQ groups allowed to trigger meeting replies. |
| `EVENT_LINK_REPLY_GROUPS` | QQ groups allowed to query event links. |
| `EVENT_LINK_SEND_GROUPS` | QQ groups receiving scheduled event links. |
| `BILIBILI_MONITOR_TARGET_GROUP_IDS` | QQ groups receiving Bilibili dynamic updates. |
| `BILIBILI_MONITOR_ADMIN_UIDS` | QQ users allowed to run Bilibili monitor admin commands. |

List values should use JSON-like syntax, for example:

```env
SUPERUSERS=["123456789"]
MEETING_REPLY_GROUPS=[123456789]
BILIBILI_MONITOR_TARGET_GROUP_IDS=[123456789,987654321]
```

## Unraid

This fork includes a Community Applications-ready Unraid template:

- IronsBot template: `templates/ironsbot.xml`
- CA profile: `ca_profile.xml`
- Optional NapCat example: `unraid/examples/napcat.xml.example`

Template URLs:

```text
https://raw.githubusercontent.com/Murmansk5000/IronsBot/main/templates/ironsbot.xml
```

The Unraid template exposes the runtime variables as editable fields, including group IDs, meeting number, OneBot token, and Bilibili monitor settings.

## Privacy Notes

Do not put private QQ IDs, group IDs, meeting links, meeting numbers, account passwords, or tokens into files committed to GitHub.

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
