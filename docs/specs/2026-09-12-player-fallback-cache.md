# Player Fallback Cache

Status: `verified`

Target: one source-age calculation for base and detail reply caches. Owner:
core time arithmetic and the existing player cache/service. Baseline: live
queries retain priority before quota exhaustion; cached replies are not charged.

## Scope

- Extract the detail cache's finite/known/non-future observation TTL arithmetic
  to a pure function in core.time, reused by both existing cache implementations.
- Base cache uses its matching PlayerBaseSnapshot observation, never insertion
  time as a replacement. Missing/mismatched snapshots cannot prove freshness.
- Keep a monotonic deadline alongside source age; cache writes cannot renew old
  evidence. Do not merge caches, create a universal cache manager or change SQL.
- PlayerService must resolve fallback at return time, not capture a cached result
  before awaiting a potentially slow live request.
- No main merge, new config/dependency, persistent migration or image-size claim.

## Verification

Test old/missing/invalid source times, expiry while a live request is in flight,
snapshot mismatch, reuse without additional quota, and unchanged live-first
behavior. Run the combined focused player tests and static/type checks once per
batch; full public regression remains a phase gate per user instruction.

Rollback: revert the code commit. Program remains 4/8 verified phases; estimate
20-40 minutes for this item, overall ETA unestablished.

Evidence: combined player/cache/observation/quota/background regressions 79
passed in 6.27 seconds; private extension 26 passed in 2.39 seconds. BasedPyright
reported zero errors/warnings. Ruff, compileall and diff checks passed. Public
full-suite and real deployment checks remain phase gates, not claimed here.
