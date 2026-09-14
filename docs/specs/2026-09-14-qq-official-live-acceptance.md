# QQ Official Live Acceptance

Status: `blocked_by_external_credentials`

Contract: `release_gate`

Owner: QQ Official transport integration and deployment operator.

Related transport: [QQ Official Tencent SDK Transport](2026-09-14-qq-official-tencent-sdk.md)

## Purpose

This is the only remaining Phase 7 gate. Unit tests, an offline container smoke,
and a successful image build do not prove that a real QQ application has the
required event intents, media permissions, or proactive-message quota.

## Prerequisites

- One enabled QQ Bot application with an AppID and AppSecret.
- A sandbox C2C user and sandbox group, or equivalent production access.
- The application is permitted to receive C2C and group-at events.
- Image replies are enabled for the application.
- Proactive-message permission is required only when testing scheduled pushes.

Never paste an AppSecret, access token, user OpenID, member OpenID, or group
OpenID into an issue, commit, screenshot, or unredacted log attachment.

## Minimal Configuration

```toml
[bot.qq_official]
enabled = true
sandbox = true

[bot.qq_official.accounts.acceptance_bot]
enabled = true
app_id = "YOUR_APP_ID"
proactive_messages = false
features = [
  "help",
  "about",
  "seer_data",
  "seer_pet",
]
```

Supply the secret only through the process environment:

```text
QQ_OFFICIAL_SECRET_ACCEPTANCE_BOT=YOUR_APP_SECRET
```

The deprecated static `token` field must not be configured. The Tencent SDK
obtains and refreshes the short-lived access token from AppID and AppSecret.

## Connection Gate

Start the exact candidate image intended for release. Passing requires all of
the following evidence:

1. The log contains `QQ Official connection starting` for the configured AppID.
2. The log later contains `QQ Official connected` for the same AppID. The first
   line alone is not success because the SDK starts its WebSocket thread before
   the platform sends `READY` or `RESUMED`.
3. No fatal close, authentication failure, reconnect storm, or secret value is
   present in the captured log interval.

## Passive Message Matrix

Run each row once and retain redacted timestamps plus outcomes.

| Context | Input | Required result |
| --- | --- | --- |
| C2C | `关于` | One text reply in the same conversation. |
| C2C | `精灵雷伊` | The normal shared query result, not a platform-specific fallback. |
| C2C | `下周预告` | A valid image reply, proving upload and rich-media delivery. |
| Group | Directly `@机器人 帮助` | One help reply in that group. |
| Group | `帮助` without an at | No response unless ordinary group events were explicitly granted and enabled. |
| Group | Quote a message and also at the bot | No response, preserving the global reply-ignore rule. |

Every received event and every reply must retain the same AppID. A user OpenID
or member OpenID observed under one application must never route through a
different application client.

## Proactive Message Gate

This gate is optional for passive-only deployments and mandatory before setting
`proactive_messages = true` in production.

1. Confirm proactive-message permission and quota in the QQ platform console.
2. Enable `proactive_messages` for only the acceptance account.
3. Configure one temporary user or group target using an OpenID observed under
   that same AppID.
4. Trigger one existing scheduled push through its normal application service.
5. Verify exactly one delivery, then verify a user unsubscribe suppresses the
   next delivery.

Delete the temporary target after the test. Do not use a guessed OpenID or a
numeric QQ identifier.

## Acceptance Record

Record only non-secret evidence:

```text
candidate commit:
container digest:
AppID fingerprint (last four characters only):
READY/RESUMED timestamp:
C2C text: pass/fail
C2C Seer query: pass/fail
C2C image: pass/fail
group at: pass/fail
group non-at policy: pass/fail
quoted reply policy: pass/fail
proactive delivery: pass/fail/not enabled
```

Phase 7 may close only when every required row passes against the same candidate
digest. A credential preflight, successful token request, or gateway URL alone
is insufficient.

## Partial Local Evidence

On 2026-09-14 a local source checkout connected with AppID fingerprint `2026`.
The SDK persisted a resumable session record with a non-empty session ID and
sequence `1`. The process and listener were stopped after the probe, and the
temporary configuration and session cache were removed. No credential was
written to the repository.

This does not pass the connection gate: the run did not retain the required
visible `READY/RESUMED` log line and was not an immutable candidate container.
No passive-message or proactive-message matrix row is marked as passed from
this probe.
