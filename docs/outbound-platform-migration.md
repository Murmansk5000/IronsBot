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

All accounts with a configured Secret connect independently. `required` only
controls whether that account's startup failure aborts the application; it does
not select a fallback sender. A group feature policy authorizes the logical
group and does not require two official bots to reply there. C2C and group
replies always return through the AppID that received the event, so acceptance
tests for a designated private bot must send the private message to that bot.

In Unraid, duplicate the AppID/AppSecret variable pair for each TOML alias and
replace the suffix with the alias in uppercase. Adding environment variables
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
It then links a group `member_openid` to a QQ number only after two independent,
unique, consistent observations in that logical group. Each observation uses
the official reply's source-message reference and the numeric sender that
NapCat reports for that referenced message; it does not infer identity from a
visible mention. Ambiguous, expired,
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
