# Rank Window Observation Time

Status: `verified`

Contract: `target`

Owner: `services.seer` rank range and score queries

Related: [architecture](../../ARCHITECTURE.md),
[player observation time](2026-09-05-player-data-observation-time.md)

## Evidence And Scope

Before this change, `rank_range`, cache-only ranges, exclusion views and score
segments merged page times with `max`, sometimes initialized with the current
time. Binary score probes discarded page time through `fetch_item`. Score and
global-list formatters could replace missing timestamps with the render time.

## Target Contract

- Raw `RankPageResult` keeps its required observation time. Add `RankRangeResult`
  in the existing models module for composed windows: its time may be unknown
  when no page was read. This prevents an empty request from masquerading as an
  observed raw page or weakening the transport/cache evidence contract.
- Reuse `ObservationTime`. All supporting pages contribute their original time,
  including empty terminal pages, exclusion prefixes, binary boundary probes,
  tie-boundary pages and displayed samples. A newer sample cannot redate an
  older boundary proof. Empty requests perform no fetch and have no timestamp.
- Cache-only misses stay `None` (unavailable coverage), distinct from an empty
  request/result. Cache-only and mixed range metadata retain their cache flags.
- Score results use an optional timestamp rather than epoch zero as a sentinel.
  Binary probes consume aligned `RankPageResult`; remove the now-unused
  list-only `fetch_item` and its dependency field. Do not add probe requests,
  pagination loops, cache stores, runtime modules or compatibility wrappers.
- Global-list and score formatters require an explicit timestamp; unknown stays
  unknown. Keep query grammar, quotas, page/probe/tie limits and display layout.
- Cache-candidate discovery is a position hint, not observation evidence. Its
  confirmation pages, not the hint's age, date the successful result. Failed
  candidate confirmation is not carried into a separate binary result.

No new TOML, schema, dependencies, production writes or main integration. Other
sample/static leaderboard timestamps and bounded-search completeness semantics
remain separate audits; this is not completion of all freshness/error gates.

## Acceptance

- [x] Mixed raw ranges use the oldest supporting page, including terminal empty
  pages, while zero/negative counts never fetch or invent time.
- [x] Cache-only and excluded public windows include earlier hidden-account
  prefix pages; missing coverage stays unavailable.
- [x] Binary score matches/misses include probe and neighbor proof times;
  boundary rejection and empty observed datasets retain probe time.
- [x] Confirmed cached candidates and cache-only score ranges include boundary
  pages even when only head/tail samples are displayed.
- [x] Unknown and epoch-zero timestamps are distinguished in formatting.
- [x] Existing score/range limits, positions and cache policy tests pass through
  the page boundary after the discarded-metadata item wrapper is removed.
- [x] Public/private regression, Ruff, typing, compileall and diff checks pass.

## Verification

- `tests/test_rank_observation_time.py`: 23 cases, including 17 added for this
  scope. Controlled page responses cover mixed/empty windows, cached SQLite
  coverage, hidden-account prefixes, binary probes, gap proofs, candidate
  confirmation and head/tail samples. Formatting distinguishes unknown from
  epoch zero. No live QQ or official API requests were made.
- Focused range/score/cache/exclusion regression: **120 passed**. Full public
  regression: **2395 passed, 274 dependency warnings, 116.55 seconds**. Private
  regression against this worktree: **26 passed**.
- `uv run ruff check ironsbot tests`, `uv run basedpyright ironsbot tests`
  (0 errors/warnings), `uv run python -m compileall -q ironsbot` and
  `git diff --check` passed.
- Production code net change: **-3 lines**, all in existing modules. No runtime
  dependencies, schema, deployment data or TOML changes. The private worktree's
  pre-existing untracked `uv.lock` was not modified.
- Local main remains `f19c7089`; no fetch/pull/merge/push. The old full-test
  process had ended but its output was unavailable, so the final suite above
  was rerun after checking that no test/type-check process remained alive.

Remaining gates include bounded-search completeness and cache admission/freshness
policy. In particular, exhaustion of score probes must not be presented as a
confirmed missing score; this slice does not change that independent contract.

Program remains 4/8 verified phases. No measured image-size improvement is
claimed. Rollback is scoped code commits only.
