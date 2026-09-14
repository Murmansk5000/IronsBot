# QQ Official Tencent SDK Transport

Status: `implemented_local`

Contract: `target`

Owner: QQ Official transport integration and application lifecycle.

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)
Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Goal

Replace `nonebot-adapter-qq` with Tencent's framework-independent Python SDK
without changing command, feature-policy, identity, persistence, or business
service contracts. NoneBot remains the OneBot host; QQ Official connections are
ordinary application resources.

## Target Contract

- Deployment supplies AppID and AppSecret only. The SDK owns short-lived access
  token acquisition and refresh.
- Every AppID owns an independent API client, WebSocket, resume session, reply
  sequence allocator, feature namespace, and outbound route.
- SDK inbound events are converted once to `IncomingMessageRef`; only the shared
  portable router decides whether a command runs.
- `OutboundMessage` is converted at the QQ integration boundary. Text, member
  mentions, binary images, and remote images use Tencent SDK DTOs and upload
  APIs.
- The QQ SDK starts before contribution startup hooks and stops before shared
  HTTP clients close.
- No static token, adapter bot registry, default AppID fallback, or second
  command implementation remains.

## Known Platform Boundary

The SDK release supports C2C and `GROUP_AT_MESSAGE_CREATE`. Tencent's Node SDK
classifies `GROUP_MESSAGE_CREATE` as a private-domain bot event while
public-domain bots receive only `GROUP_AT_MESSAGE_CREATE`. Receiving ordinary
group messages therefore requires both private-domain platform authorization
and explicit support in the Python SDK; it is not inferred from group
configuration. Real AppID, group permission, passive reply, image upload, and
proactive quota behavior remain external gates.

## Tencent Reference Decision

The transport design was checked against Tencent Connect's maintained reference
projects rather than inferred from the retired static-token configuration:

- [`qqbot-agent-sdk`](https://github.com/tencent-connect/qqbot-agent-sdk) is the
  selected Python protocol dependency. IronsBot uses its `QQApiClient`,
  `QQWebSocket`, `EventParser`, media upload DTOs, and persisted resume session.
- [`qqbot-nodejs`](https://github.com/tencent-connect/qqbot-nodejs) is a design
  reference for connection readiness, per-AppID token ownership, transport
  middleware, Webhook support, richer media delivery, and the distinction
  between public-domain `GROUP_AT_MESSAGE_CREATE` and private-domain
  `GROUP_MESSAGE_CREATE`. It is not embedded as a Node sidecar because that
  would duplicate the gateway, token, event, and send paths and enlarge the
  runtime image.
- [`openclaw-qqbot`](https://github.com/tencent-connect/openclaw-qqbot) is a
  deployment reference for multi-account isolation, group mention policy, and
  proactive-message diagnostics. Its AI-agent business layer is not copied into
  IronsBot.

The deprecated `token` field means a deployment-provided static token is no
longer the credential contract. Each enabled account supplies an AppID and an
AppSecret; the SDK obtains and refreshes the short-lived AccessToken internally.
An AccessToken remains part of the wire protocol and must never be persisted in
TOML.

Features demonstrated by the Node references are adopted only when the Python
transport and the bot application's platform permissions can support them:

| Reference capability | IronsBot decision |
| --- | --- |
| WebSocket heartbeat, reconnect, and Resume | Implemented through the Python SDK. |
| Independent token and session state per AppID | Implemented; cross-account fallback is forbidden. |
| C2C and group-at passive replies | Implemented; real AppID acceptance remains required. |
| Text and image/media delivery | Implemented through the shared outbound port. |
| Ordinary non-at group messages | Private-domain permission-gated and unsupported by the pinned Python event surface; do not claim support from `requireMention=false` or configuration alone. |
| Webhook transport | Deferred until a deployment needs public callback or horizontal scaling. |
| C2C streaming, voice, video, and large files | Deferred; they are not required by the current IronsBot command contract. |
| Proactive messages | Implemented behind an explicit account capability flag and still subject to platform quota. |

Do not replace this transport with a Node subprocess merely to obtain a feature
shown by a reference project. First add the missing protocol surface upstream or
behind the existing Python integration boundary, then prove it with the live
acceptance matrix.

Do not monkey-patch `qqbot_agent_sdk.websocket.MESSAGE_EVENT_TYPES` or its
`EventParser`. When the deployment receives private-domain permission, add
`GROUP_MESSAGE_CREATE` in an audited SDK release, upgrade the pinned dependency,
and keep IronsBot's integration limited to converting the resulting
`InboundEvent`.

## Acceptance

- [x] `qqbot-agent-sdk==1.2.2` is the only QQ Official runtime dependency.
- [x] Two configured AppIDs create isolated clients and session stores.
- [x] C2C and group-at events preserve opaque identity and reply exclusion.
- [x] Text, mention, binary image, and remote image delivery use SDK calls.
- [x] Delivery-aware callbacks run only after a successful SDK response.
- [x] Disabled QQ Official mode imports no optional SDK package.
- [x] Ruff, BasedPyright, targeted tests, full pytest, compileall, and diff checks
  pass.
- [x] Private preview image builds and passes its offline smoke test.

Local evidence: `86 passed` in the focused SDK/lifecycle suite and `3390 passed,
7 skipped` in the full suite. Ruff and BasedPyright report no findings. An
isolated no-dev/no-extra environment imports the standard composition root
without importing `qqbot_agent_sdk`.

Private preview workflow `34787564915` passed dependency audit, Linux image
build, offline smoke, size budgets, growth comparison, and GHCR publication for
commit `c66eec1b`; published digest:
`sha256:16c33659b96c1ffe8c70ca2a041a2f458eff3fbb1ebcd9827dd6fa644713b80a`.

## Rollback

Revert the implementation commit and restore the previous optional adapter
dependency. No TOML or SQLite migration is involved.
