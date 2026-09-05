# Player Rank Partial Results

Status: `implementing`

Contract: `target`

Owner: `services.seer.rank_summary`

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)

Related ledger: [multiplatform-refactor.md](../multiplatform-refactor.md)

## Problem

The page scheduler isolates ordinary board failures, but only returns its result
dictionary after every board finishes. Collection and peak shortcuts wrap that
whole summary in `safe_player_extra` and replace a timed-out summary with an
empty one. Already completed boards are lost. The mutable `current_title` also
cannot identify all unfinished boards when independent lookups run concurrently.

## Goal And Ownership

Record completed board results in the existing `RankSummaryProgress`, keyed by
the existing job IDs. Summary assembly and timeout recovery must consume the
same mapping. Keep rank, score, cache provenance, cost and explicit failures
unchanged for completed boards. Only unfinished boards receive the batch failure.
Reuse the existing scheduler, models and service boundary; no platform adapter,
new persistence, dependency or alternate query engine is needed.

## Design

- Wrap each operation at the summary job boundary to record its terminal result
  immediately. Normalize ordinary exceptions there; propagate cancellation.
- Assemble collection and peak summaries through model factories shared by the
  successful and partial paths. Missing results receive an explicit failure when
  recovering an interrupted summary, never an invented not-ranked conclusion.
- Use one domain helper for the existing summary timeout and partial recovery.
  Do not catch external cancellation or start detached work.
- Keep existing time budgets, page scheduling, quota and protocol cleanup rules.

## Delivery And Remaining Gates

| Slice | Acceptance | Status |
| --- | --- | --- |
| Summary recovery | Completed boards survive collection/peak summary timeouts; cancellation propagates | verified |
| Full detail budget | Audit outer detail timeout, request protection and incremental publication; preserve base data | pending |

The first slice does not prove the complete multi-stage player workflow: the
outer detail timeout can still interrupt before formatting. Phase 5 stays open
until that path and progressive publication are verified as well.

Confirmed next gate: `PlayerDetailService` allows a basic stage of 22.5 seconds
with default configuration; the summary guard allows 60 + 8 seconds; local sample
update can consume another stage. Both foreground `PlayerService._shortcut_live`
and background `_run_background_shortcut` wrap the whole detail in 90 seconds.
Their cancellation reaches the domain helper as external cancellation, which
must propagate. The next slice must consolidate budget ownership rather than
catch arbitrary cancellation, increase every timeout or add another empty reply.

## User And Data Contract

No command, permission, TOML or SQLite change. No live data migration. No new
fallback data source. Rollback is the scoped code commit; deployed data is not
modified. Existing `empty()` constructors remain valid for truly empty summaries,
but shortcut timeout handling no longer discards completed results.

## Acceptance Tests

- [x] Real summary builder and scheduler: one stalled page, completed siblings
  survive the existing enclosing timeout in the rendered collection/peak reply.
- [x] Multiple unfinished boards are all marked timed out; earlier explicit
  failures and successful cache metadata remain unchanged.
- [x] Summary cancellation propagates, drains its owned work and resets context.
- [x] Successful summaries and local metric updates retain existing behavior.
- [x] Ruff, scoped typing, focused/full public tests, private regression,
  compileall and diff checks pass.

## Evidence

- Regression before implementation: both collection and peak shortcut tests
  failed after sibling lookups had completed; their ranks were absent in output.
- Focused summary, shortcut and scheduler tests: 25 passed. The tests use real
  summary/scheduler/formatting code with controlled page operations, not real
  official network traffic. They verify terminal page cleanup, original result
  identity, cache timestamp/cost, explicit earlier failure and cancellation.
- `uv run pytest -q --basetemp=.test-tmp/rank-partial-full`: 2306 passed,
  271 warnings, 83.94 seconds.
- Private suite against this public worktree: 26 passed. Its preexisting
  untracked `uv.lock` is untouched.
- `uv run ruff check ironsbot tests`, `uv run basedpyright ironsbot tests`
  (0 errors/warnings/notes), compileall and `git diff --check` passed.
- Removed title-based summary `mark_failure` methods and duplicated shortcut
  error callbacks. Added no production module, dependency, TOML field or database.
- No main fetch/merge, push or production deployment was performed.

## Progress

Program: 4/8 phases verified, not a percentage of effort. This spec remains a
Phase 5 slice. Summary recovery is verified; the next full-detail budget slice
is estimated at 30-60 minutes. Release gates need separate measured verification.
