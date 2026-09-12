# Player Data Observation Time

Status: `verified`

Contract: `target`

Owner: `services.seer` query results and formatting

Related: [architecture](../../ARCHITECTURE.md),
[phase ledger](../multiplatform-refactor.md)

## Evidence

Detail headings call `format_player_data_time()` with no source time. Rank
position confirmation discards `RankPageResult.fetched_at` through `fetch_page`
and reconstructs it using the current clock. Score and linear lookups similarly
discard page metadata. Complete-reply reuse retains its text timestamp, but
reformatting source caches can present the render time as the observation time.

## Target

Data producers own observation times. Formatters never invent them. A composite
result carries the oldest observation needed to support it, not the newest
page's time. Unknown time remains unknown. No source labels, relative times,
new TOML, schema migration, runtime dependency or production data edits.

## Ordered Slices

1. Rank evidence: `RankLookupResult.fetched_at` records page/cache evidence;
   position, score and linear searches consume `RankPageResult`. Remove the
   artificial position wrapper. Reuse the existing bounded search algorithm,
   keeping probe, tie-page and scheduling limits. A common result method records
   page time and work cost. Cached facts, miss proofs and timeout fallback retain
   their original time. Visibility adjustment includes the pages it reads.
2. Presentation: pass explicit observation time through collection, peak,
   autocard and lineup formatting. Base snapshots retain capture time; combined
   details conservatively combine relevant observations. Cached results must not
   gain a new time on rendering. Validate direct/menu/cache/private entry paths.

No change to cache-first/live-first admission or quota policy in these slices.
The score-segment and arbitrary rank-window timestamp aggregation require a
separate audit before the overall freshness gate can close.

Slice 2 implementation rule: reuse one observation accumulator in `core.time`.
Successful live reads record completion time; failed/cancelled reads do not.
Reused evidence contributes its stored timestamp, including an explicit unknown.
Unknown evidence cannot be made known by a later live read. Partial peak reads
contribute only fully decoded modes, taking the oldest successful packet within
those modes. Rank failures without data do not date the successful fields.
Base snapshot time covers its reusable nickname/collection data; immutable cached
registration dates are not presented as freshly fetched collection metrics.
Formatters require an explicit timestamp. Lineup captures time before subsequent
availability bookkeeping, rendering or persistence, and caches retain the text.

## Acceptance

- [x] Rank page time survives anchor, linear and binary search.
- [x] Cached hit, cached miss and timeout fallback preserve stored time.
- [x] Multiple-page evidence uses the oldest required page; visibility pages
  contribute observation time without changing existing quota attribution.
- [x] Binary probes still fetch aligned pages and obey bounded search limits.
- [x] Artificial position-page wrapper is deleted, without a compatibility path.
- [x] Details and lineup use explicit producer timestamps, including cached and
  mixed results; missing source times are never replaced by the current clock.
- [x] Slice 1 public/private regression, Ruff, typing, compileall and diff checks pass.
- [x] Slice 2 public/private regression, Ruff, typing, compileall and diff checks pass.

## Progress

Slices 1 and 2 are verified against the controlled tests described below.
Program stays 4/8 verified phases. Composite window/score-segment time propagation
is now verified in the separate [rank window Spec](2026-09-05-rank-window-observation-time.md);
neither scope is an overall freshness completion claim.

Evidence:

- `tests/test_rank_observation_time.py` covers source page timestamps across
  three search modes, real SQLite cached hit/miss and timeout fallback, persisted
  oldest-page miss proofs and public-rank adjustment evidence. Transport is
  controlled; no official server or production cache is accessed.
- Existing rank-limit tests now inject transport through the normal RankService
  dependency, exercising the actual page boundary instead of mocking the removed
  list-only position wrapper. Numeric bounds, tie page limits and anchor quota
  classification remain covered.
- Focused rank/cache/summary/player regression: **90 passed**. Final full public
  suite: **2354 passed, 274 dependency warnings, 87.68 seconds**. Private: **26
  passed** using this worktree. Ruff, BasedPyright (0 errors/warnings), compileall
  and `git diff --check` passed.
- Deleted `_fetch_page_result_for_position_lookup`, `cached_rank_miss` and
  `save_rank_miss`; the latter two were legacy reflection/forwarding wrappers.
  Normal reads/writes use the existing typed cache contract directly. Miss
  persistence receives the observation time explicitly, not its save time.
- Production net change: **-38 lines**, no new runtime module or dependency,
  no new TOML or SQLite schema. No Docker image measurement is claimed.

Remaining audit: the existing score algorithm resets probe budgets between
boundary/lower-bound/upper-bound stages. Tests now expose these three bounded
stages; this is not a single global probe budget. No budget policy was changed
in this metadata slice. Slice 2 preserves unknown times and base snapshot time
without pretending all composite data was observed simultaneously.

Slice 2 implementation:

- `core.time.ObservationTime` is shared by base snapshots, detail composition,
  peak packet decoding and the public lineup query port. It captures successful
  read completion, retains old/unknown evidence, and never stamps failure or
  cancellation. No new runtime module or dependency was added.
- All collection/peak/autocard/lineup heading callers pass explicit source time.
  A timed-out rank's search target is not a fetched score. A cached rank restored
  after timeout still contributes its original time and stays a partial reply.
- `tests/test_player_detail_observation_time.py` exercises the actual detail
  service and formatter pipeline, old snapshot and rank evidence, undated
  sources, cached reply reuse, timeout fallback and per-board failure isolation.
  The public lineup port and actual SQLite reopen preserve the same heading.
- Core tests cover completion, cancellation, failure and never-started reads;
  the protocol partial-mode test discards successful packets of an incomplete
  mode from the result time. Base-query fanout confirms that later fields do not
  redate the original observation. Existing numeric/menu and private-extension
  tests remain part of regression.
- Production net change: **+95 lines** across existing modules. No TOML,
  schema or deployment data changes; no measured image-size claim.
- Final focused detail regression: **72 passed**. Final full public suite:
  **2378 passed, 274 dependency warnings, 99.16 seconds**. Private: **26 passed**
  against this worktree. Ruff, BasedPyright (0 errors/warnings), compileall and
  `git diff --check` passed. No live QQ or official API request was used.

Follow-up completed in the rank window Spec: `rank_range`, `rank_cache_queries`,
`rank_score_cache`, `rank_score_segments` and the range paths in
`rank_exclusion_lookups` preserve supporting page times instead of aggregating
with `max` or supplying current time for empty windows. The separate acceptance
covers binary probes and boundary pages, not just a textual replacement.
Bounded-search completeness, cache policy and real release validation remain
open; the overall freshness phase is not closed.

Local main remains `f19c7089`; no fetch/pull/merge/push. No real-platform/release
validation or image-size improvement is claimed. Rollback is scoped code commits
only.
