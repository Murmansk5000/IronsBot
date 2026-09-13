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
- A deferred callback returns one platform-neutral `OutboundMessage`.
- The runtime sends that message as a second reply to the same incoming event.
- Unexpected deferred failures are logged with context and converted to a concise
  user-visible failure message.
- Nested deferred replies are not supported.

`progress_operation_reply()` adapts existing service methods that accept a progress
callback. Such a method must report progress before starting expensive or externally
observable work. The adapter pauses that callback until the initial message has been
delivered, then resumes the service method and exposes its return value as the final
reply. Commands that finish without reporting progress remain single-message replies.

## First Consumer

`rank.sample_refresh` is the first portable deferred command. A QQ Official
superuser receives the existing sample-cache refresh start message immediately and
the existing result message after refresh completion. Empty caches still return the
single existing error message.

## Verification

- Initial delivery succeeds before deferred work resumes.
- Initial delivery failure cancels the paused operation.
- Initial and final QQ Official replies use distinct passive reply sequences.
- Existing `on_delivered` callbacks continue to run exactly once.
- Catalog feature and superuser filtering remains authoritative.
