# QQ Official Protocol Baseline

Status: `accepted`

Contract: `target`

Owner: QQ Official transport integration, application lifecycle, and shared
delivery contracts.

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

The Tencent SDK transport is implemented, but several current documents still
describe the removed NoneBot adapter. The application also needs an explicit
boundary between protocol work already performed by `qqbot-agent-sdk==1.2.2`
and business guarantees that remain IronsBot's responsibility. Without that
baseline, later reply, lifecycle, and media work could duplicate the SDK or
mistake a local unit test for real platform acceptance.

## Goal

Freeze a dated, source-backed protocol baseline for Phase 7. Current documents
must describe the SDK transport accurately, and every remaining implementation
slice must have a named owner and observable acceptance evidence.

## Non-Goals

- This slice does not change runtime behavior.
- This slice does not claim that a real AppID has passed login, message, media,
  quota, reconnect, or multi-account acceptance.
- This slice does not implement cross-platform identity linking.

## Ownership And Reuse

- Semantic owner: shared inbound, reply, delivery, identity, and account-health
  contracts.
- Reused contracts: `ActorRef`, `ConversationRef`, `MessageInputContext`,
  `OutboundMessage`, `CommandCatalog`, and `FeatureService`.
- Adapter boundary: `integrations.qq_official` converts Tencent events and API
  results; services never receive Tencent or NoneBot event types.
- No new interface is introduced in this documentation-only slice.

## Audited Sources

Audit date: 2026-09-15.

| Source | Observed contract |
| --- | --- |
| [Access token](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/access-token.html) | AppID and ClientSecret obtain a short-lived token; the documented default lifetime is 7200 seconds and refresh becomes available near expiry. |
| [WebSocket](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/websocket.html) | HELLO supplies the heartbeat interval; READY establishes a session; Resume uses session ID and gateway sequence; RESUMED follows replay. |
| [Intents](https://bot.q.qq.com/wiki/develop/api-v2/dev-prepare/event-emit/payload.html) | `GROUP_AND_C2C_EVENT` covers C2C and group-at events; event subscriptions remain permission controlled. |
| [Message overview](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/overview.html) | C2C passive replies are documented as 60 minutes and four replies; group passive replies are five minutes and five replies; repeated delivery can occur and inbound `msg_id` plus outbound `msg_seq` carry deduplication semantics. |
| [Rich media](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/rich-media.html) | Media is uploaded before send; local files use the recommended chunked flow; `file_info` has a TTL and cannot cross C2C/group scopes. |
| [Text interaction](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/text-chain.html) | The current user mention form is `<qqbot-at-user id="" />`; legacy `<@userid>` is marked for deprecation. |
| Installed `qqbot-agent-sdk==1.2.2` source | The SDK owns token refresh, WebSocket heartbeat/reconnect/Resume, persisted session state, READY/RESUMED callbacks, bounded in-process message-ID deduplication, URL upload, and local-file chunked upload. |

The SDK's DTO includes `union_openid`, but the audited official group/C2C
contract does not guarantee a numeric QQ ID or a common cross-transport identity
in every event. IronsBot therefore must not infer a QQ number from that field.

## Current Gap Matrix

| Concern | SDK responsibility | IronsBot responsibility | Current evidence |
| --- | --- | --- | --- |
| Authentication | Token acquisition and refresh | Secret injection and per-AppID lifecycle | Implemented locally; real credentials remain external |
| Gateway | Heartbeat, reconnect, Resume, session persistence | Startup timeout, account health, required/optional policy, shutdown ordering | Runtime starts a connection but Phase 7 health acceptance is open |
| Inbound deduplication | Bounded in-process message-ID cache | Side-effect idempotency and any recovery scope beyond the SDK cache | SDK source verified; business boundaries remain open |
| Passive replies | HTTP calls and DTO encoding | Event-derived deadline, per-scene reply budget, sequential concurrent `msg_seq` | Current defaults and allocator require correction |
| API failures | Logs status and trace ID, raises `RuntimeError` | Structured failure kind, code, trace ID, retry policy, redaction | Open; string classification remains in the adapter |
| Rich media | `MediaUploader` URL and chunked upload flows | Use uploader, scope cache by AppID/scene, honor TTL, expose delivery outcome | Current binary path still Base64-encodes whole content |
| Mentions | Text payload transport | Render current official mention markup | Current renderer still uses deprecated markup |
| Identity | Preserves opaque event fields | AppID-scoped identity and explicit, revocable linking | No implicit mapping allowed |

## Identity-Link Target

The preferred NapCat-assisted flow has no typed code in its normal path:

1. A user starts linking from the OneBot side, where the numeric QQ identity is
   already authenticated by the transport.
2. IronsBot issues a short-lived, single-use signed link or interaction token
   that does not expose the QQ number.
3. The same user confirms the request through an official-bot interaction.
4. The identity service atomically stores the AppID, official identity kind,
   OpenID, numeric QQ ID, confirmation time, and audit metadata.
5. Either side can inspect and revoke the link. Conflicts fail closed.

A typed one-time code is only a fallback when the account lacks the required
button or link capability. Nickname, avatar, message timing, or OpenID similarity
is never proof of identity.

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| Protocol baseline | Current docs identify the SDK path and dated official limits; historical adapter records are labeled | Official docs and installed SDK source | completed |
| Addressed-input routing | Valid commands precede AI and mention hints on both transports | Shared input context and command catalog | planned |
| Reply protocol | Scene-specific deadline/budget, sequential `msg_seq`, current mention markup, structured failures | Tencent send APIs | planned |
| Account reliability | READY health, startup timeout, state transitions, side-effect idempotency, ordered shutdown | SDK callbacks and session store | planned |
| Media and identity | SDK uploader, scoped TTL cache, explicit one-click identity linking | Platform permissions and identity repository | planned |
| Real acceptance | Three deployment modes and real login/reply/media/reconnect/multi-account evidence | Authorized Tencent sandbox | planned |

## Migration And Rollback

- Migration: none; this slice changes documentation only.
- Rollback: revert the documentation commit as one unit.
- Removal condition: references to the old adapter may remain only inside dated
  historical evidence and must be explicitly labeled as historical.

## Acceptance Tests

- [x] Locked runtime dependency is `qqbot-agent-sdk==1.2.2`.
- [x] Current architecture text no longer presents `nonebot-adapter-qq` as the
  supported transport.
- [x] SDK and IronsBot responsibilities are separated by evidence.
- [x] Official reply, event, upload, and mention contracts are dated and linked.
- [ ] Runtime slices and real-platform gates are completed in later commits.

## Evidence

| Date | Change | Verification actually run | Result / remaining risk |
| --- | --- | --- | --- |
| 2026-09-15 | Protocol and implementation audit | Official documents above; installed SDK 1.2.2 source; dependency lock; architecture text search | Baseline accepted; runtime gaps and real-platform gates remain open |

## Progress

```text
Program  [█░░░░░░░░░] 5%   fixed Phase 7 baseline weight
Phase    [██████████] 100%  protocol baseline documented
Current  [░░░░░░░░░░] 0%   next: addressed-input routing
```

Only verified and committed work counts toward program progress.
