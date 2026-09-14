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
| [Message buttons](https://bot.q.qq.com/wiki/develop/api-v2/server-inter/message/trans/msg-btn.html) | Template keyboards require an application and do not accept variables; custom keyboards are invite-only. Command buttons can insert and send `@bot` input, while callback buttons require `INTERACTION_CREATE` acknowledgement. |
| [Operating rules](https://bot.q.qq.com/wiki/business/) | Disclosed functionality, content filtering, consented data use and deletion are required. Without Tencent authorization, core bot use cannot depend on another bot or application. |
| Installed `qqbot-agent-sdk==1.2.2` source | The SDK owns token refresh, WebSocket heartbeat/reconnect/Resume, persisted session state, READY/RESUMED callbacks, bounded in-process message-ID deduplication, URL upload, and local-file chunked upload. |

The SDK's DTO includes `union_openid`, but the audited official group/C2C
contract does not guarantee a numeric QQ ID or a common cross-transport identity
in every event. IronsBot therefore must not infer a QQ number from that field.

## Current Gap Matrix

| Concern | SDK responsibility | IronsBot responsibility | Current evidence |
| --- | --- | --- | --- |
| Authentication | Token acquisition and refresh | Secret injection and per-AppID lifecycle | Implemented locally; real credentials remain external |
| Gateway | Heartbeat, reconnect, Resume, session persistence | Startup timeout, account health, required/optional policy, shutdown ordering | Runtime starts a connection but Phase 7 health acceptance is open |
| Inbound deduplication | Bounded in-process message-ID cache | Persistent pre-dispatch message claims beyond the SDK cache | Completed with AppID/event/message isolation and 24-hour retention |
| Passive replies | HTTP calls and DTO encoding | Event-derived deadline, per-scene reply budget, sequential concurrent `msg_seq` | Group 5-minute/5-reply and C2C 60-minute/4-reply policies are enforced; live sequence keys are conversation-scoped and never evicted |
| API failures | Logs status and trace ID, raises `RuntimeError` | Structured failure kind, code, trace ID, retry policy, redaction | HTTP boundary preserves status, business code and trace ID; delivery classification uses typed fields and transport exceptions |
| Rich media | `MediaUploader` URL and chunked upload flows | Materialize binary payloads, preserve scene, and expose delivery outcome | Completed; URL and chunked paths use the SDK, and `file_info` is one-use because SDK 1.2.2 drops TTL |
| Mentions | Text payload transport | Render current official mention markup | Renderer emits escaped `<qqbot-at-user id="" />` markup |
| Identity | Preserves opaque event fields | AppID-scoped identity and explicit, revocable linking | No implicit mapping allowed |

## Interactive Confirmation Target

Finite follow-up choices share one platform-neutral prompt contract rather than
separate button and text workflows. A future `PromptSession` owns the initiating
actor and conversation, reply message, expiry, one-time consumption and
idempotency key. Each `PromptChoice` owns a stable value and user-facing label.

- QQ Official renders available choices as command or callback buttons when the
  account has the required capability.
- OneBot may render buttons only when its transport capability is proven; its
  baseline remains a numbered or yes/no text prompt.
- Typed `y`, `n`, `yes`, `no`, `是` and `否` remain accepted by the same session
  handler as an accessibility and unsupported-client fallback, not as a second
  business path.
- Confirmation, cancellation, numbered selection, pagination and enable/disable
  prompts are button candidates. Player IDs, search terms, times and free-form AI
  input remain text fields.
- Every click is re-authorized server-side against the initiating actor and
  conversation. UI visibility and deprecated client-side click limits are not a
  security boundary.

Template keyboards cannot carry a dynamic per-session token, and custom
keyboards are currently invite-only. The implementation must therefore support a
reliable text fallback before claiming no-input confirmation as accepted.

The shared core now exposes `PromptSession` and `PromptChoice`. Portable
query menus bind a cryptographically random session ID to the initiating AppID,
actor, conversation and message, and button action data and numeric text input
resolve through the same selection callback. Non-persistent prompts are consumed
exactly once. Accounts with Tencent's invite-only custom-button permission may
set `custom_keyboards = true`. The adapter then emits type-2 command buttons
that automatically send the opaque session action as a regular addressed
message; this deliberately avoids a second callback business path and does not
require `INTERACTION_CREATE` acknowledgement. Unsupported clients and accounts
without permission retain the same numeric text choices.

## Identity-Link Target

Cross-platform linking is optional. Public QQ Official features continue to work
without NapCat or a numeric QQ identity, so the official bot does not make another
bot or application a condition of use.

The reliable baseline flow is:

1. A user starts linking from either transport.
2. IronsBot issues a short-lived, single-use token scoped to the initiating
   actor, conversation and target AppID without exposing the numeric QQ number.
3. The user presents or confirms that token on the other transport. When an
   approved button flow yields authenticated events from both transports, this
   step may be rendered as buttons; otherwise the user enters one short code.
4. The identity service atomically stores the AppID, official identity kind,
   OpenID, numeric QQ ID, confirmation time, and audit metadata.
5. Either side can inspect and revoke the link. Conflicts fail closed.

Nickname, avatar, message timing, speech history or OpenID similarity may not
complete a link and are never proof of identity. Binding a Seer player ID to an
official OpenID is a separate operation and does not by itself prove a numeric QQ
identity or ownership of the game account.

## Delivery Slices

| Slice | Acceptance criteria | Dependencies | Status |
| --- | --- | --- | --- |
| Protocol baseline | Current docs identify the SDK path and dated official limits; historical adapter records are labeled | Official docs and installed SDK source | completed |
| Addressed-input routing | Valid commands precede AI and mention hints on both transports | Shared input context and command catalog | completed; chat, intent, command suppression and hints share one decision service |
| Reply protocol | Scene-specific deadline/budget, sequential `msg_seq`, current mention markup, structured failures | Tencent send APIs | completed; command keyboards are capability-gated and reuse ordinary inbound selection |
| Account reliability | READY health, startup timeout, state transitions, side-effect idempotency, ordered shutdown | SDK callbacks and session store | completed; real disconnect/reconnect remains in the external acceptance matrix |
| Media and identity | SDK uploader, safe `file_info` lifetime, explicit identity linking | Platform permissions and identity repository | completed; Lucky Skin Window consumes only exact links |
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
| 2026-09-15 | Addressed-input routing | AI routing, command ownership, OneBot matcher, portable router and QQ Official tests | Both transports share command-first chat/intent policy; duplicate OneBot group matcher removed |
| 2026-09-15 | Passive-reply policy | Reply allocator, official identity, outbound messenger and SDK runtime tests | Event timestamps define deadlines; group and C2C budgets are separate; active live keys cannot be evicted and reused |
| 2026-09-15 | Structured API failures and mentions | 75 QQ Official tests; Ruff; BasedPyright; compileall; static repository checks | HTTP failures retain status/code/trace without parsing exception strings; transport failures remain typed; current mention markup is escaped |
| 2026-09-15 | Shared prompt identity | 52 portable-command tests and 75 QQ Official tests; Ruff; BasedPyright; compileall; static repository checks | Numeric input and opaque button action data resolve through one actor/conversation-bound session; Tencent keyboard delivery remains open |
| 2026-09-15 | Capability-gated command keyboards | 129 portable/QQ Official tests, 39 core capability tests and 37 admin-notice tests; Ruff; BasedPyright; static repository checks | Opt-in SDK sends current 5x5 keyboard schema; dynamic actions traverse the ordinary router; text fallback and strict admin targets remain intact; real AppID permission is external |
| 2026-09-15 | Account lifecycle policy | 205 portable, QQ Official, lifecycle and config tests; Ruff; BasedPyright; compileall; static repository checks | Per-AppID READY/RESUMED startup gate, explicit states, required/optional failure policy and ordered WebSocket stop are application-owned; heartbeat and Resume remain SDK-owned |
| 2026-09-15 | Persistent inbound claims | 145 portable, QQ Official and lifecycle tests; Ruff; BasedPyright; compileall; static repository checks | Concurrent and cross-instance duplicate messages are rejected before portable business dispatch; claims are isolated by AppID and event type |
| 2026-09-15 | SDK media upload | 143 portable and QQ Official tests; Ruff; BasedPyright; compileall; static repository checks | URL uploads and binary chunked uploads preserve C2C/group scope; temporary files are deleted; known platform limits produce text fallback |
| 2026-09-15 | Linked-account Lucky Skin Window | 94 identity, portable, QQ Official, lifecycle and existing Lucky Skin Window tests; Ruff; BasedPyright; compileall; static repository checks | All six commands reuse the OneBot-keyed account service through an exact AppID/kind/OpenID/scope link; uncached login and ambiguous skins use shared labeled prompts |

## Progress

```text
Program  [████████▌░] 85%  fixed weights; feature and identity slice completed
Phase    [██████████] 100%  protocol baseline documented
Current  [██████████] 100%  media and identity completed
```

Only verified and committed work counts toward program progress.
