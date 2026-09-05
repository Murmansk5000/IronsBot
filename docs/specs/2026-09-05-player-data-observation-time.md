# Player Data Observation Time

Status: `implementing`

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

## Acceptance

- [x] Rank page time survives anchor, linear and binary search.
- [x] Cached hit, cached miss and timeout fallback preserve stored time.
- [x] Multiple-page evidence uses the oldest required page; visibility pages
  contribute observation time without changing existing quota attribution.
- [x] Binary probes still fetch aligned pages and obey bounded search limits.
- [x] Artificial position-page wrapper is deleted, without a compatibility path.
- [ ] Details and lineup use explicit producer timestamps, including cached and
  mixed results; missing source times are never replaced by the current clock.
- [x] Slice 1 public/private regression, Ruff, typing, compileall and diff checks pass.

## Progress

Slice 1 verified. Program stays 4/8 verified phases. Slice 2 and composite
window/score-segment audit remain open. The detail heading still uses the old
formatter until slice 2; this is not an end-to-end freshness completion claim.

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
in this metadata slice. Slice 2 must preserve unknown times and base snapshot
time without pretending all composite data was observed simultaneously.

Local main remains `f19c7089`; no fetch/pull/merge/push. No real-platform/release
validation or image-size improvement is claimed. Rollback is scoped code commits
only.
