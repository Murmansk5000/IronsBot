# Rank Miss Evidence Freshness

Status: verified slice; full-run bootstrap timing caveat below

## Contract

Target: negative rank evidence must have sufficient coverage, usable freshness,
and no newer contradictory observation. Storage owns evidence consistency;
the live lookup chooses fresh evidence, while explicit cache-only lookup may
use historical evidence with its original timestamp.

The current live lookup inherits `allow_stale_cache = true` for misses and can
skip online work indefinitely. A later positive observation also leaves the
old miss eligible to return before cached-position online confirmation.

## Changes

- Require unexpired miss evidence in the shared live `find_rank` entry point.
  Preserve fresh negative-cache reuse and explicit historical cache-only reads.
- Reject a miss contradicted by a same-board, same-player last-seen observation
  inside its searched range at an equal or later source time. Use the existing
  indexed last-seen table, including for databases already containing conflicts.
- A delayed miss must not remove newer/equal last-seen evidence or replace a
  newer miss. Use source timestamps, not insertion order.
- Do not add runtime modules, configuration, dependencies or schema migrations.
  Keep old positive coordinates as online-search hints and timed fallback data.

## Verification

Use real temporary SQLite with the actual RankService: expired misses trigger
an online lookup, fresh misses retain their timestamp without network work,
and explicit cache-only lookup can still use historical misses. Test a new
positive observation after a miss and the reverse insertion order; isolate
board, season, player, range and source time. Preserve newer misses when old
work finishes later. Run rank/player regressions, public and private pytest,
Ruff, BasedPyright, compileall and diff checks.

## Boundaries

This does not establish an atomic snapshot across mutable official pages or
change admission age for composed player-detail replies. Phase 5/6 remain
in progress. No production database, TOML, main integration or push is needed.
Rollback is a code revert; existing tables are unchanged.

## Evidence

- Before production changes, 7 failures reproduced stale live miss reuse,
  newer/equal positive evidence ignored in both insertion orders, and older
  miss work overwriting a newer proof. The other 12 new matrix cases passed.
- Focused rank observation/cache/limit/score tests: 93 passed. Fresh evidence
  at the exact TTL boundary remains valid; an expired miss cannot bypass the
  online request. Cache-only history retains its actual timestamp.
- Ruff, BasedPyright (0 errors/warnings), compileall and diff checks passed;
  private regression against this worktree: 26 passed.
- Production delta: +10 net lines in two existing modules. The contradiction
  check uses the existing `(key, sub_key, user_id)` primary key, not a page scan.
- Full public regression: 2433 passed, 1 failed, 274 dependency warnings in
  455.95 seconds. The sole failure was the bootstrap subprocess's existing
  30-second timeout, not a rank assertion. Its unchanged isolated rerun passed
  in 19.20 seconds. Do not report this as a single fully green suite run or
  infer the timeout's cause; startup timing remains a Phase 7 acceptance risk.
- Local main advanced independently to `963a83c3`; its master-pool changes
  were read and recorded in the ledger, not merged or claimed as migrated.

## Positive Page Write Ordering (2026-09-12)

Persistent positive observations had the inverse race: a late older save deleted
overlapping newer pages, moved an already-observed player backwards, and could
erase a newer page with an old empty response. Three real SQLite/reopen tests
failed before the fix. Page save now takes BEGIN IMMEDIATE before checking
overlapping page timestamps and each incoming player's last-seen/miss evidence.
If newer contradictory evidence exists, reject the entire incoming page; do not
splice its old rows into a newer observation. The guard and write share one
transaction. Miss coverage is checked against each incoming rank index; another
board/season is independent. Global nicknames only update with equal/newer time.

Existing primary keys serve the player checks, avoiding a new index, table,
cache or migration. Checks are per incoming row and use bound parameters, not a
variable-size SQL IN list. Equal timestamps retain existing replacement behavior;
this is a strict older-write guard, not proof of atomic official multi-page data.
Repeated reopening, old empty pages, miss-range boundaries, independent boards,
global nicknames and two real concurrent SQLite writers are covered.

127 focused rank/cache/refresh/SQLite tests and 43 private native-enabled tests
passed; targeted type checking, Ruff, compileall and diff checks passed. No full
public-suite rerun in this batch, no production data change, main merge or push.
Invalid/future timestamps and full dynamic multi-page consistency are not newly
certified by this change. Overall verified phase count remains 4/8.
