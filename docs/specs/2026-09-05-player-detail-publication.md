# Player Detail Publication And Cache Ownership

Status: `verified`

Contract: `target`

Owner: `services.seer.player_detail_service`

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

The bounded detail pipeline now preserves partial results, but every reply still
defaults to `complete=True` and is stored in the complete-reply cache. A retry can
therefore reuse a failed reply instead of querying again. A finished background
future is also reused while other sections remain active.

Background publication looks up the *current* refresh by player ID, even when
the producing task belongs to an expired refresh. Expiry releases waiters but
does not cancel the old task. A late old result can fulfill a replacement
refresh's future or overwrite its cache.

## Design And Scope

- Existing `QueryReply.complete` describes completeness of the requested detail.
  The collection/peak/autocard pipeline sets it from actual base/local failures
  and rank result status, not from Chinese reply text. Partial data is still sent.
- Only complete replies enter the short-lived complete-reply cache. A partial
  result never evicts a valid complete entry. Already waiting callers receive
  their partial result once; future callers do not reuse its terminal future.
- Capture the owning `_BackgroundRefresh` before work starts and pass it to the
  common publication operation. Expired/replaced owners cannot cache or resolve
  another refresh. Foreground completion can still fulfill its own captured
  refresh, preserving existing shared-waiter behavior.
- Expiry cancels the old owned task and reuses normal waiter cleanup. Identity
  checks also reject a late producer that suppresses cancellation.
- Verify existing OneBot cancellation suppression and independent section
  delivery with actual session/adapter code where feasible. Do not add a new
  stream of unsolicited per-board messages or change numeric menu syntax.
- Check cancellation before acquiring a new prompt version in the common
  OneBot conversation entry. A canceled detail task currently suppresses sending
  too late: it has already invalidated a replacement menu's version.

## Non-Goals

No new TOML, SQLite, dependency, main integration, quota policy, UI command or
production deployment. General cache-first versus live-first policy is unchanged.
No compatibility wrapper, second result cache or alternate task owner is added.

## Acceptance

- [x] Pipeline base, rank and sample failures set `complete=False`; normal
  results remain complete.
- [x] A partial reply is delivered to existing waiters, is not cached, and does
  not prevent a later retry; complete cache entries remain reusable.
- [x] An expired producer cannot resolve a new refresh, overwrite its cache or
  remove its lifecycle record, including after cancellation is suppressed.
- [x] A fast section is available while another section is still running.
- [x] A canceled menu does not emit a late detail result; numeric input and
  separate user/conversation scope retain current behavior.
- [x] Focused/full public tests, private regression, Ruff, typing, compileall
  and diff checks pass.

## Evidence And Progress

- Reproduced three cache/refresh failures before the production changes:
  partial results were cached, expiry did not cancel producers, and partial
  replies replaced complete entries. All three now pass.
- A real detail handler -> common conversation -> prompt loop test reproduced
  replacement-menu invalidation after cancellation. The early common guard
  now preserves both message suppression and the replacement version.
- Background tests use the actual detail service/lifecycle with controlled
  query responses; they verify fast partial delivery while sibling sections
  remain active, cancellation-resistant old producers and captured foreground
  publication ownership. No real QQ messages or official requests were sent.
- A 20-case pipeline matrix covers collection/peak/autocard success, confirmed
  misses, nickname/base/rank/sample failure and restricted rank lookup. Existing
  deadline tests now also assert partial completeness.
- Focused player/menu/reply tests: **97 passed**. Public full suite:
  **2348 passed, 274 warnings, 90.01 seconds** (dependency deprecation/ORM
  warnings). Private suite: **26 passed**, using this public worktree.
- `uv run ruff check ironsbot tests`, `uv run basedpyright ironsbot tests`,
  `uv run python -m compileall -q ironsbot`, and `git diff --check` passed.
- No new runtime module, dependency or configuration. Production code net
  change is +29 lines; no Docker build or image-size reduction is claimed.
- Program remains **4/8 verified phases**, not an effort percentage. This
  closes this result-publication slice, not the remaining parameterized-command,
  data freshness or real-platform/release acceptance gates. Local main is still
  `f19c7089`; no fetch, pull, merge, push or production migration was performed.

Rollback: scoped code commit only; no deployed or persistent data is modified.
