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

The SDK release supports C2C and `GROUP_AT_MESSAGE_CREATE`. Receiving ordinary
`GROUP_MESSAGE_CREATE` depends on platform authorization; IronsBot's SDK boundary
forwards that newer event without adding a second transport. The same boundary
forwards Tencent recipient-management events that SDK 1.2.2 does not yet expose.
Receive/reject and add/remove state is persisted and enforced before proactive
delivery. Real AppID, group permission, passive reply, image upload, and proactive
quota behavior remain external gates.

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

Revert the implementation commit and its configuration/documentation changes as
one unit. The removed NoneBot adapter is not a supported fallback and must not be
restored as a second runtime path. No TOML or SQLite data migration is involved.
