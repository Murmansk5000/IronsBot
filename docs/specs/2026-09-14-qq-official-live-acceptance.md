# QQ Official Live Acceptance

Status: `blocked_by_candidate_message_matrix`

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
| Group | Quote a message and also at the bot | No response under the current Official transport's quote exclusion. Do not execute text or mentions from `msg_elements`. |

Every received event and every reply must retain the same AppID. A user OpenID
or member OpenID observed under one application must never route through a
different application client.

This is the current Official transport acceptance policy, not a claim that
OneBot globally ignores replies. The current architecture permits newly sent
explicit commands in OneBot replies; the SDK transport spec separately retains
Official quote exclusion. Do not remove that exclusion or declare cross-platform
quote parity from this matrix without a dedicated contract change and tests.

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
The first probe persisted a resumable session record with a non-empty session
ID and sequence `1`. After adding the project logging bridge, a second probe
started from an empty session directory and retained these redacted lifecycle
events:

```text
10:53:46 QQ Official connection starting
10:53:47 QQ Official connected
```

Starting without a stored session means this callback followed the SDK's fresh
READY path rather than Resume. Both probe processes and listeners were stopped,
and their temporary configuration and session cache were removed. No credential
was written to the repository.

This evidence still does not close the connection gate because the run was not
an immutable candidate container. No passive-message or proactive-message
matrix row is marked as passed from these probes.

On 2026-09-14 at 12:15 local time, the current source branch completed another
fresh production-endpoint probe with AppID fingerprint `2026`. Configuration
validation confirmed that only AppID and the process-environment AppSecret were
used; the retired static Token was absent. The project log recorded connection
start at `12:15:30` and `connected` at `12:15:31`, with no authentication error,
fatal close, or reconnect storm before an orderly shutdown. The temporary
session record was removed after inspection. This strengthens the source-level
connection evidence, but it still cannot be attributed to a frozen image digest
and does not replace the passive-message matrix.

The earlier private preview workflow froze commit `7fc19e17` as a candidate
image:

```text
ghcr.io/murmansk5000/ironsbot-qq-official-preview@sha256:6601faaea16b93d76cb39cf9d0ec5a110ff74375387a973039aa7f97bda40bb0
```

Workflow run `34803647246` passed dependency audit, Linux build, offline smoke,
runtime size budgets, image growth comparison, and publication. This host had
no available Docker Engine, so the candidate digest itself has not yet run the
connection or passive-message matrix.

On September 14, workflow run `34817126039` completed successfully for
`bde8bceccdc2fb5904b54ef9b50cf5402049c94f`. Its published-image artifact records:

```text
ghcr.io/murmansk5000/ironsbot-qq-official-preview@sha256:311a78c1abba5076eeeead8fba8443253500ebf4284bffdf3a5196fa56b151e6
Docker local image size: 259726834 bytes
/app: 4460 KiB
site-packages: 105948 KiB
fonts: 19452 KiB
```

The audited comparison baseline was preview `latest` pinned to
`sha256:afd905d13aa459516f25bd827bbd3f95d5a4fa5ade2b968b367e392947706841`,
259738853 bytes on that runner; the candidate is 12019 bytes smaller. These
are local expanded Docker sizes, not registry compressed transfer sizes.
Dependency audit, Linux smoke, budgets and publication passed. This supersedes
the earlier published candidate evidence, but includes neither the subsequent
Bilibili collage wiring nor the configured-text content ownership fix.
No real message matrix row is accepted by this build result.

The subsequent run `34818679162` also passed audit, Linux smoke, size budgets
and publication for `1526bc4fb0ee08b65e6d6e7da7557a4ce9170af2`:

```text
ghcr.io/murmansk5000/ironsbot-qq-official-preview@sha256:07fc781c634f9370604a037a25d41f98dd80e2505267cb9188629b0ba93710ad
Docker local image size: 259729851 bytes
/app: 4460 KiB
site-packages: 105948 KiB
fonts: 19452 KiB
```

The same pinned baseline `afd905d13aa4...` measured 259738853 bytes; this
candidate is 9002 bytes smaller. It includes Bilibili collage wiring and the
service-owned configured-text fix. It does not include the later Docker source
diagnostics change. It is now the latest verified published candidate in this
record, not evidence of any real QQ message delivery.

Another bounded local Docker availability attempt on September 14 did not
return a server version. The new probe was stopped after observing its exact
process ID and command; unrelated existing probes were not stopped. No local
container connection or message-matrix result is inferred from this attempt.

## Partial Delivery Contract

Target: the official SDK sender must preserve the shared outbound policy that
uncertain delivery is never automatically replayed. A composite text/image/text
message is multiple API operations, not an atomic send. If any operation fails
after a preceding operation is acknowledged, return an uncertain result even
when the underlying failure (for example HTTP 429) would otherwise be retryable.
Stop remaining operations and retain the original exception as the cause.
Cancellation continues to propagate; this is not a new transport retry engine.

Official message IDs and upload handles must be nonblank strings. A missing or
malformed post-message receipt is uncertain, since the recipient may already
have received the message. This includes invalid JSON or a non-object response
returned by an otherwise successful post. A malformed upload handle must never be posted as
media. Typed HTTP transport timeouts/errors also yield uncertain results without
depending on nonempty exception text. Tests must cover both group and C2C,
failures at upload/post/receipt, and the complete shared proactive retry path.
No new dependency, persistent state, configuration, or packaged asset is needed.

Workflow `34819501551` for `a2936456` has now completed successfully. This is
candidate build evidence, not a real message-matrix result; it predates this
partial-delivery correction.

```text
ghcr.io/murmansk5000/ironsbot-qq-official-preview@sha256:7564fc171d47fb8b24f567b61640eb02ff634e5a4c7d2e4b11463015dada5c0d
Docker local image size: 259731577 bytes
Comparison against pinned afd905d13aa4...: -7276 bytes
```

The image inspect and growth artifacts were downloaded and checked. This is
the latest verified published candidate in this record; it includes the Docker
source diagnostics, but not the later partial-delivery correction.

The partial-delivery source change passed full regression: 3490 passed,
7 skipped; Ruff, BasedPyright, compileall and diff checks passed. The final
pytest invocation used a fresh isolated temporary directory after the first
run failed during cleanup of the host's old pytest-current directory. Existing
2879 dependency warnings remain visible. These are source-level results only.

Workflow `34821149687` passed for `f1b4639f`, including the partial-delivery
correction. Image-inspect and growth artifacts confirm:

```text
ghcr.io/murmansk5000/ironsbot-qq-official-preview@sha256:33e2f0c4509107b3b4e0f05b067de8cef3e26e107afd10f8c4537b7ed1be002b
Docker local image size: 259732829 bytes
Comparison against pinned afd905d13aa4...: -6024 bytes
```

This supersedes the preceding candidate in this record. It does not include
the subsequent player team-menu work or establish real QQ message delivery.

Workflow `34822187566` subsequently passed for `cfe27d3f`, including the player
team menu. Downloaded image-inspect and growth artifacts confirm:

```text
ghcr.io/murmansk5000/ironsbot-qq-official-preview@sha256:cc2b491f4440043c7ba007996e313998f54c776e4c20fc265fc65fbe92640407
Docker local image size: 259735497 bytes
Comparison against pinned afd905d13aa4...: -3356 bytes
```

This candidate does not contain the subsequent direct player-team query slice.
Build success still does not establish real QQ connection/message acceptance.

Workflow `34824609352` passed for `b62d603e`. It includes direct player-team
queries and the shared bound/subscribed overview. Downloaded image-inspect and
growth artifacts confirm:

```text
ghcr.io/murmansk5000/ironsbot-qq-official-preview@sha256:b363e0aac5eb9f9521a16837245a057326be7a17307903ba49a484630b18d1dd
Docker local image size: 259745233 bytes
Comparison against pinned afd905d13aa4...: +6380 bytes
```

This supersedes the earlier candidate but predates the optional inbound metadata
validation correction. An 8-second local Docker server probe still did not
respond; only that owned probe process was stopped. The current process has no
`QQ_OFFICIAL*` environment variables. Neither finding proves that credentials
or another Docker host are unavailable elsewhere, but this host has not run the
candidate message matrix. Historical source READY logs do not fill that gap.

Workflow `34825220887` succeeded for
`ec2f98cf6ce836209e5ec51d67badcca9034d3a2`, including the optional inbound metadata
validation correction. Downloaded image-inspect and growth artifacts confirm:

```text
ghcr.io/murmansk5000/ironsbot-qq-official-preview@sha256:196d0ace492d9ef2182dba74ce444c7967232459bf67fa36fd3e32844f0fc96f
Docker local image size: 259745352 bytes
Comparison against pinned afd905d13aa4...: +6499 bytes
/app: 4476 KiB
site-packages: 105948 KiB
fonts: 19452 KiB
```

This supersedes the preceding published candidate. Dependency audit, offline
entrypoint smoke, directory budgets, growth budget and publication passed.
No connection or passive-message matrix row is accepted from these results.

Private extension commit `4dce691` was tested against this exact public source
using `IRONSBOT_PUBLIC_ROOT`, rather than the sibling main checkout: 45 passed,
1 native-render case skipped. The joint manifest test uses the current query
session composition and shared player resolver for numeric and alias inputs,
including feature filtering. It does not restore retired matcher state keys or
prove live lineup delivery. These test-only changes require no replacement
public candidate image.
