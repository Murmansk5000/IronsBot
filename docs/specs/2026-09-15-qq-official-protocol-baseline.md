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
| Authentication | Token acquisition and refresh | Secret injection and per-AppID lifecycle | One real account passed token acquisition and READY; refresh remains covered by SDK ownership rather than a controlled expiry test |
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
| Real acceptance | Three deployment modes and real login/reply/media/reconnect/multi-account evidence | Authorized Tencent sandbox | partial; one-account READY, C2C command and ordered shutdown passed |

## Feature And Command Matrix

The command catalog, rather than a second platform-specific inventory, is the
source of truth. The complete application profile currently has 78 direct
commands shared by OneBot and QQ Official. Router construction fails when an
official direct command has no portable operation, so a catalog entry cannot be
silently advertised without an implementation.

| Capability | OneBot / NapCat | QQ Official | Current limitation or evidence |
| --- | --- | --- | --- |
| Help, about, configured text and meeting replies | supported | supported | Real C2C help passed |
| Seer data, player, team, pet, mintmark, equipment, type, peak and autocard queries | supported | supported | Shared services and portable operations; image delivery remains a real-platform gate |
| Weekly content menus and details | supported | supported | Shared router returned a five-choice menu against the validated local release cache |
| Global and sampled ranks, display limits and cache administration | supported | supported | Same rank services; administrative commands retain catalog audience checks |
| Activity and Bilibili history queries | supported | supported | Query paths are portable; scheduled delivery is governed separately |
| AI chat and intent actions | supported when configured | supported when configured | Command-first routing is shared; provider availability and feature policy still apply |
| Message, Bilibili, activity and team-resource subscriptions | supported | supported when proactive delivery is enabled and authorized | Tencent proactive quota and permission failure remain a real-platform gate |
| Data sync, status and Docker maintenance commands | supported | supported | Same services and superuser policy; destructive operations were not exercised during real acceptance |
| Cross-platform identity-link initiation | supported | not supported | OneBot is the side that can authenticate the numeric QQ identity and issue a short-lived challenge |
| Cross-platform identity-link confirmation | not supported | supported | Official OpenID confirms the challenge; no nickname, avatar or timing inference is accepted |
| OneBot-native notices and client-specific passive events | supported where a plugin registers them | not implicitly supported | They require an explicit Tencent event and policy; no fake compatibility event is synthesized |
| Binary and remote images | supported | implemented through SDK media upload | Real same-scope Tencent upload and send remain pending |

Platform differences stay in command metadata, inbound adapters and delivery
capabilities. Business services do not branch on the platform to maintain a
second implementation.

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
- [x] Runtime slices are implemented and locally verified.
- [ ] Remaining real-platform gates are tracked in the matrix below and are not
  reported as passed without platform evidence.

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
| 2026-09-15 | Portable command coverage gate | QQ-enabled full bootstrap plus router failure test; 53 portable, QQ Official and bootstrap tests; Ruff; BasedPyright; compileall; static repository checks | The full catalog currently contains 78 QQ Official direct commands: the original 75-command portability target plus three official identity commands. Construction fails when any direct contract lacks an operation or explicit built-in handler |
| 2026-09-15 | Automated closure run | Full suite `3450 passed, 7 skipped`; Ruff; production and test BasedPyright; compileall; static repository checks; clean worktree | All local gates pass. The manual Tencent account matrix below remains external and must not be reported as passed without captured platform evidence |
| 2026-09-15 | Runtime log redaction | 60 runtime, lifecycle, portable and QQ-enabled bootstrap tests; Ruff; BasedPyright; compileall | Connection logs use the configured account alias. Message and conversation identifiers use irreversible short digests; original AppIDs and OpenIDs remain available only to routing and persistence code |
| 2026-09-15 | Real token and READY acceptance | Dedicated local test account with AppID in ignored TOML and AppSecret in an ignored environment file | SDK obtained an access token and the redacted account alias reached `ready`; no credential or raw platform identifier was retained in this document |
| 2026-09-15 | Real C2C command acceptance | Operator sent `帮助` three times after READY; runtime recorded one recognized inbound route and one successful initial delivery for each message | Each operator message produced exactly one private reply; command recognition, C2C passive delivery and persistent inbound deduplication passed without duplicate execution |
| 2026-09-15 | Application-owned data startup | 51 focused lifecycle/registry/bootstrap tests plus a local portable `新增内容` dispatch against a contract-validated release cache | Seer data now loads as an application resource rather than a OneBot plugin side effect; the shared router returned a five-choice menu after startup |
| 2026-09-15 | Real ordered shutdown | Operator stopped the READY process repeatedly with the normal interrupt path | Uvicorn completed application shutdown and the process exited without a surviving QQ Official runtime task |

## Progress

```text
Program  [█████████▊] 98%  fixed weights; remaining work is external acceptance
Phase    [██████████] 100%  protocol baseline documented
Current  [██████████] 100%  media and identity completed
```

Only verified and committed work counts toward program progress.

## Real Tencent Acceptance Matrix

Run this matrix only with a dedicated test application whose secret is supplied
through the process environment. Never paste the secret into TOML, command-line
arguments, logs, screenshots, or this evidence table.

| Check | Operator action | Required evidence | Status |
| --- | --- | --- | --- |
| Access token and READY | Start one required test account | Redacted startup log reaches `ready` after SDK `READY` | passed 2026-09-15 |
| Group addressed command | In an authorized test group, address the bot and send `帮助` | One reply; no mention-guard interception or duplicate execution | pending operator message |
| C2C command | Send `帮助` in the bot's private conversation | One private reply using the C2C reply budget | passed 2026-09-15; repeated three times without duplicate execution |
| Sequential replies | Run a command whose one inbound message produces several outbound payloads | Payloads referencing that same inbound message use increasing sequence values | pending operator message |
| Image upload | Run a query whose result contains an image | SDK media upload succeeds in the same group/C2C scope | pending operator message |
| Resume and deduplication | Interrupt connectivity after READY, restore it, then retry one message | `reconnecting` to `ready`; replayed message ID causes no duplicate side effect | pending controlled interruption |
| Proactive permission failure | With proactive sends disabled or ungranted, exercise one scheduled target in a test scope | Structured permission/error code is logged; no passive-reply fallback | pending authorized test |
| Multi-account isolation | Enable two authorized test AppIDs and address each independently | Separate READY state, OpenID namespace, token and send route | external gate: second AppID required |
| Ordered shutdown | Stop the local process after the checks | Accounts stop cleanly before shared resources; no surviving SDK task | passed 2026-09-15 |

Completion requires recording only redacted timestamps, result categories and trace
IDs. App secrets, access tokens, full OpenIDs and numeric account identifiers are not
acceptance evidence and must not be retained.
