# Player Rank Partial Results

Status: `verified`

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
| Full detail budget | Shared deadline preserves base/rank data in foreground and background; later stages use remaining time | verified |

The first slice alone did not prove the complete multi-stage player workflow.
The second slice verifies the deadline through foreground/background detail
services; actual conversation publication and cache reuse remain Phase 5 gates.

Pre-change evidence: `PlayerDetailService` allowed a basic stage of 22.5 seconds
with default configuration; the summary guard allowed 60 + 8 seconds; local sample
update could consume another stage. Both foreground `PlayerService._shortcut_live`
and background `_run_background_shortcut` wrapped the whole detail in 90 seconds.
Those equal-duration wrappers have now been removed. Their cancellation previously
reached the domain helper as external cancellation, which must still propagate.

### Full Detail Deadline

- A small monotonic `OperationDeadline` in the existing core task contracts owns
  remaining-time arithmetic, not task spawning, results, retries or protocol I/O.
  Collection, peak and autocard use it; no player-specific global context is added.
- `PlayerDetailService` injects explicit total, per-basic-stage and rank-stage
  limits from typed configuration. Remove the reflective rank-config/test-double
  fallback and per-stage configuration attribute defaults.
- The query pipeline starts one deadline. Every awaited stage receives at most
  its remaining time. The summary recovery from slice 1 then returns completed
  ranks; expired sample work is reported separately without discarding the reply.
- Peak base `timeout_seconds` is a whole-stage budget. Remaining time is shared
  among remaining modes; no mode receives a fresh copy of the whole stage budget.
- Remove the equal-duration foreground/background wrappers around the pipeline.
  Keep the existing background lifecycle watchdog (detail budget plus cleanup
  grace) as catastrophic-task protection, not another normal query budget.
- Formatting remains synchronous and happens even after data time is exhausted.
  The deadline bounds new work, not the duration of cancellation-safe cleanup;
  genuine external cancellation still propagates. No detached work is introduced.
- No TOML field is added. Existing `detail_timeout_seconds` becomes the effective
  shared data budget, rather than a race between independent stage timers.
- Progressive publication and real protocol/deployment smoke remain separate
  Phase 5/7 acceptance gates; this slice is not full program completion.

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
- [x] Foreground/background collection, peak and autocard keep confirmed data when
  sample work exhausts the remaining deadline; external cancellation cleans up
  without caching a partial workflow.
- [x] Expired budgets do not start network/sample operations. Peak mode budgets
  sum to the whole stage allowance instead of multiplying it by three.
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

### Full Detail Budget Evidence

- Red regression: all six foreground/background collection/peak/autocard paths
  raised a whole-detail TimeoutError after their rank data had been obtained.
- Added cancellation variants and expired-budget tests. The focused deadline,
  shortcut, background, peak protocol, rank and request-protection suite passed
  58 tests. The actual deadline/service/summary/scheduler/formatter chain is used;
  network pages and sample storage are controlled test boundaries.
- `uv run pytest -q --basetemp=.test-tmp/detail-budget-full`: 2322 passed,
  271 warnings, 100.37 seconds. Private regression: 26 passed.
- Ruff, BasedPyright (`ironsbot tests`, zero errors/warnings/notes), compileall
  and diff checks passed. Existing framework/ORM warnings remain unchanged.
- Removed reflective stage configuration fallback, the test-double-only rank
  timeout fallback, and foreground/background equal-budget wrapper timers.
  Reused the existing core task module; no new production module or dependency.
- No live protocol timing or Docker image size claim follows from these tests.

## Progress

Program: 4/8 phases verified, not a percentage of effort. This spec remains a
Phase 5 slice. Both scoped slices are verified. Next: inspect and exercise actual
detail conversation publication, cancellation and cache semantics (estimated
30-60 minutes). Release gates need separate measured verification.
