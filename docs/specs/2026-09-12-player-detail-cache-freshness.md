# Player Detail Cache Freshness

Status: `verified`

Contract: `target` source-time freshness; preserve `baseline` live-first quota
and delivery of partial results. Owner: player detail service, not the renderer.

## Evidence And Design

The detail composer already calculates the oldest supporting observation for
display, but discards it from QueryReply. The complete-reply cache starts a new
full TTL at insertion, so old source data can become apparently reusable again.

- Carry the same computed observation in QueryReply.fetched_at and the display.
- Admit only complete replies with a finite, known, non-future source time and
  positive remaining configured TTL. Reuse must satisfy both source-time age
  and the monotonic insertion deadline; rewriting never renews the source age.
- Keep in-flight result delivery, incomplete-result delivery, generation guards,
  and existing quota/live/cache-only routing unchanged. Do not parse timestamps
  from text, create a second cache, or change persistent caches in this item.
- Unknown/expired observations may be shown as query results but are not fresh
  complete-cache entries. A failed attempt does not evict a still-valid previous
  complete result.
- No TOML, schema, producer, private extension or main merge changes.

## Acceptance

- Collection/peak/autocard display and metadata use the same oldest timestamp.
- Reuse before expiry, exact expiry, delayed insertion and repeated insertion
  are tested with controlled wall and monotonic clocks.
- Unknown, future, non-finite and partial replies are not admitted.
- In-flight waiters still receive deliverable results; obsolete generations
  cannot publish; quota and existing partial-result tests still pass.
- Focused player/detail/quota tests, private tests, Ruff, types, compileall and
  diff checks pass. Per the latest request to reduce repeated checks, the public
  full suite is deferred to the phase checkpoint rather than each small change.
  Rollback is a code revert, no data migration.

## Progress

Program 4/8 verified phases. Current item estimate 30-60 minutes; overall ETA
unestablished. Source-time admission is not a substitute for real release,
dynamic rank consistency, persistent fallback and platform acceptance.

## Validation

- Player detail, observation, background generation, quota and conversation
  regression: 90 passed (3 existing dependency warnings), 9.26 seconds.
- Private extension: 26 passed, 2.13 seconds; its untracked lock was preserved.
- Ruff, BasedPyright (0 errors/warnings), compileall and diff checks passed.
- Initial observation tests used a fake producer clock but the real cache
  clock, producing six failures; both now share the same controlled wall time.
- Public full suite deliberately deferred to the phase checkpoint per user
  request; previous 2697-test full result belongs to the prior commit only.
- User requested pull: clean main checkout fast-forwarded from ba08f749 to
  55a39fd1. No merge into V5; no production or dependency changes here.
