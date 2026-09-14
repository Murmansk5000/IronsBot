# Portable Deferred Replies

## Goal

Long-running commands must acknowledge the user before starting expensive work and
must deliver one final result without importing a platform adapter into the service
layer. The same contract must work for OneBot, QQ Official, and future transports.

## Contract

- `PortableReply.message` is delivered first.
- Delivery-aware callbacks run only after the transport confirms delivery.
- A failed initial delivery invokes cleanup and prevents deferred work from
  continuing.
- A deferred callback returns a platform-neutral `OutboundMessage` or another
  `PortableReply` when the next stage also has delivery-aware work.
- The runtime sends every stage in order to the same incoming event and commits
  each stage only after its own transport receipt.
- Unexpected deferred failures are logged with context and converted to a concise
  user-visible failure message.

`progress_operation_reply()` adapts existing service methods that accept a progress
callback. Such a method must report progress before starting expensive or externally
observable work. The adapter pauses that callback until the initial message has been
delivered, then resumes the service method and exposes its return value as the final
reply. Commands that finish without reporting progress remain single-message replies.

## Consumers

`rank.sample_refresh`, `rank.page_refresh`, and `rank.page_batch` use the portable
deferred contract. A QQ Official superuser receives the existing start message
immediately and the existing result message after the operation completes. Commands
that cannot start, such as refreshing an empty sample cache or caching a rank that
requires an unavailable season key, still return one error message.

Batch rank caching now reports its planned, policy-limited request count before any
headless request starts. The final reply remains authoritative for the actual number
of cached entries. This ordering is shared by OneBot and QQ Official rather than
implemented as a transport-specific workaround.

OneBot server-status, meeting and activity-query matchers are the first passive
commands to invoke their existing portable operations directly. The matcher still
owns OneBot rule, priority, permission, cooldown and sender-mention behavior; result
normalization, transport receipts, delivery callbacks and follow-up ordering use the
same portable delivery state machine as QQ Official. A OneBot response without a
message ID is an uncertain failure and cannot commit delivery-dependent state.

## Verification

- Initial delivery succeeds before deferred work resumes.
- Initial delivery failure cancels the paused operation.
- Initial and final QQ Official replies use distinct passive reply sequences.
- OneBot portable replies preserve the existing sender mention and require a real
  send receipt before committing state.
- Existing `on_delivered` callbacks continue to run exactly once.
- Catalog feature and superuser filtering remains authoritative.
