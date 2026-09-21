# Outbound platform migration

IronsBot selects one outbound platform during configuration loading. It never
fails over between QQ Official and OneBot at runtime.

## NapCat-only deployment

Do not define any `APP_SECRET_*` variables.

```toml
[bot.onebot]
enabled = true
send_messages = true
identity_verification = false
```

With `send_messages = false`, the application may run without a user-facing
outbound transport.

## QQ Official deployment

Declare each account in TOML without an `enabled` field:

```toml
[bot.qq_official]
sandbox = false
startup_timeout_seconds = 15.0
default_account = "local_bot"

[bot.qq_official.accounts.local_bot]
app_id = "10001"
required = true
proactive_messages = true
custom_keyboards = false
features = ["help", "about", "seer_data"]
```

Activate it with the Secret variable whose suffix is the public AppID:

```env
APP_SECRET_10001=
```

Once the Secret is present, QQ Official is the sole outbound platform. OneBot is
silent even when `send_messages = true`. A Secret suffix whose AppID is not
declared in TOML prevents startup. An official
connection or delivery failure never enables OneBot fallback.

### Multiple official accounts

Declare every account alias and public AppID in TOML, then provide one Secret
variable for each AppID. Do not reuse one AppID for two accounts:

```toml
[bot.qq_official]
default_account = "group_bot"

[bot.qq_official.group_routes]
# admin = "private_bot"

[bot.qq_official.accounts.group_bot]
app_id = "10001"
required = false
proactive_messages = true
custom_keyboards = false
features = ["help", "about", "seer_data"]

[bot.qq_official.accounts.private_bot]
app_id = "10002"
required = true
proactive_messages = false
custom_keyboards = false
features = ["help", "about", "seer_data"]
```

```env
APP_SECRET_10001=
APP_SECRET_10002=
```

All accounts with a configured Secret connect independently. `default_account`
owns private messages and groups without a more specific owner. A logical group
with exactly one configured official endpoint is assigned to that account;
`group_routes` selects the responder when a logical group has several endpoints.
`required` only
controls whether that account's startup failure aborts the application; it does
not select a fallback sender. A group feature policy authorizes the logical
group and does not require two official bots to reply there. C2C and group
replies always return through the AppID that received the event, so acceptance
tests for a designated private bot must send the private message to that bot.

In Unraid, add one masked `APP_SECRET_<AppID>` variable for each TOML account.
Adding environment variables
without the matching TOML account, or adding the TOML account without both
environment variables when it is intended to run, is not a complete migration.

## Silent group identity observation

NapCat can remain connected only to verify group member identities:

```toml
[bot.onebot]
enabled = true
send_messages = true
identity_verification = true

[bot.onebot.trusted_official_bots]
local_bot = 123456789
```

The trusted bot table must exactly cover all active official accounts. IronsBot
first learns `(AppID, group_openid) -> numeric group` from any uniquely matched
normal command reply in a numeric group declared by `[identities.groups].qq`.
The mapping is persisted in the QQ state database and restored on restart, so
the diagnostic `官方身份` command and a duplicate TOML OpenID are not required.
It first correlates exact copies of a claimed command or explicit bot mention seen
by both transports. The official event contributes the sender and ordered mentioned
`member_openid` values; NapCat contributes the sender and ordered mentioned QQ
numbers. The logical group, AppID, normalized text, mention count and time window
must agree. NapCat may deliberately send `@官方机器人 @目标用户` to establish the
target link without a command; a self-sent message lacking either mention is
ignored. Trusted official replies remain a fallback observation path. Existing
OneBot player bindings then remain authoritative, while official-only rebindings
are merged into that principal. Ambiguous, expired,
untrusted, or conflicting observations do not create or overwrite a link.
NapCat sends no verification messages. C2C `user_openid` values are not inferred
and remain explicit TOML aliases.

For Unraid, the equivalent deployment overrides are:

```env
ONEBOT_ENABLED=true
ONEBOT_SEND_MESSAGES=true
ONEBOT_IDENTITY_VERIFICATION=true
ONEBOT_TRUSTED_OFFICIAL_BOT_LOCAL_BOT=123456789
```

Remove the old `bot.qq_official.enabled` and per-account `enabled` fields. No
other TOML migration is required.
