# Outbound platform migration

IronsBot selects one outbound platform during configuration loading. It never
fails over between QQ Official and OneBot at runtime.

## NapCat-only deployment

Do not define any `QQ_OFFICIAL_APP_ID_*` or `QQ_OFFICIAL_SECRET_*` variables.

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
required = true
proactive_messages = true
custom_keyboards = false
features = ["help", "about", "seer_data"]
```

Activate it with a complete environment pair:

```env
QQ_OFFICIAL_APP_ID_LOCAL_BOT=
QQ_OFFICIAL_SECRET_LOCAL_BOT=
```

Once the pair is present, QQ Official is the sole outbound platform. OneBot is
silent even when `send_messages = true`. Missing one half of the pair, or using
an environment suffix not declared in TOML, prevents startup. An official
connection or delivery failure never enables OneBot fallback.

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
links a group `member_openid` to a QQ number only after two independent, unique,
consistent observations in the same logical group. Each observation uses the
official reply's source-message reference and the numeric sender that NapCat
reports for that referenced message; it does not infer identity from a visible
mention. Ambiguous, expired,
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
