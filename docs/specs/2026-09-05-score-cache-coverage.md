# Score Cache Coverage

Status: `verified`

Contract: `target`, shared bounded evidence planning for score candidates

Owner: `services.seer.rank_score_helpers`; I/O remains with online/cache callers

## Evidence

Before this change, online candidate expansion stopped its while loops when
the page budget was full, without setting `truncated`. Disconnected candidate
pages could therefore be reported as a complete score interval. Cache-only
expansion required out-of-range neighbors at the first/last requested rank and
rejected valid clipped windows. Both duplicated match and boundary reasoning.

## Target

- Add one pure coverage planner in the existing score helpers module. It reads
  supplied aligned page results, query bounds and target score. It returns the
  observed matching indexes and missing page starts needed to prove their
  contiguous interval and immediate neighbors. No I/O, clock or policy lookup.
- Query bounds and an observed short/empty terminal page close the corresponding
  edge. Clip indexes to the requested half-open range, including unaligned bounds.
  Existing SQLite page reads reject short/incomplete coverage: the schema does
  not distinguish a terminal response from subsequently missing facts. Preserve
  that refusal; do not reinterpret a partial cache as terminal evidence. Only
  providers actually returning an observed terminal page can close this edge.
- Reject contradictory evidence: score inversions, duplicate players, malformed
  page shape, or observed rows beyond an observed terminal page. This is not an
  atomic server snapshot or a general dynamic-rank consistency guarantee.
- Online candidate confirmation and cache-only queries share this planner.
  Unconfirmed coverage returns `None`, never a fabricated population. Online
  callers retain the existing bounded binary fallback; cache-only never opens
  the network. No new retry or budget policy.
- Do not exceed the candidate page budget or reread already supplied pages.
  Include all proof-page times. Do not mutate a caller's result on failed
  candidate confirmation. Hidden-account prefix reads retain their separate
  rank-renumbering responsibility and existing coverage requirements.
- Delete the duplicated boundary expansion and match-index implementation.
  Keep gap-proof generation, display sampling, quotas and public grammar.

No TOML, schema, dependencies, runtime module, production writes or main merge.

## Acceptance

- [x] Open edges at budget exhaustion remain unconfirmed; closed edges can
  succeed with exactly the configured page budget.
- [x] Disconnected candidates fetch the missing interior pages or decline the
  shortcut; no skipped interval is counted as complete.
- [x] First rank, search-limit edge and unaligned query windows work in both
  paths. Online short/empty terminal evidence closes the edge; partial SQLite
  pages stay unavailable rather than being reclassified as the end of a board.
- [x] Contradictory pages cannot prove a score interval.
- [x] Existing cache candidates, head/tail samples, observation times, hidden
  users and bounded fallback tests pass, with no network in cache-only mode.
- [x] Ruff, types, full public/private tests, compileall and diff checks pass.

## Verification

- Focused cache/limit/observation/exclusion regression: **71 passed**. Fifteen
  new cases exercise both candidate adapters (with real temporary SQLite) and
  pure contradictory-page validation. Initially reproduced false completeness,
  disconnected intervals and incorrect rejection of query bounds.
- Short-page expectations were corrected after inspecting the SQLite contract:
  physical partial pages are unavailable, not terminal evidence. No schema or
  production cache was modified to make those cases pass.
- One old candidate fixture was not descending (200, 150, 200). It now uses
  higher scores before the single match and lower scores after, preserving its
  intended cache-anchor test. A separate inversion test explicitly verifies
  rejection of the formerly malformed evidence.
- Ruff, BasedPyright (0 errors/warnings), compileall and diff checks pass.
  Private regression: **26 passed** against this public worktree.
- Production net change: **+5 lines** in existing modules. Two copies of edge
  expansion and duplicate match enumeration were replaced by one pure planner.
  No new runtime module, dependency, configuration or image-size claim.
- Full public regression: **2415 passed, 274 dependency warnings, 484.86 seconds**.
  The existing test process remained live and was polled to completion; no
  replacement run was started on an observation timeout.
- An additional in-memory exhaustive check covered **2205** combinations of a
  six-entry monotonic board, tie boundaries, clipped windows and subsets of
  two-entry pages. Every complete planner result matched the reference board's
  exact interval; missing page requests never included already supplied pages.
  This is a small static oracle, not live rank consistency or a throughput test.
- Local main remains `f19c7089`. No fetch/pull/merge/push, production data changes
  or private worktree edits; its existing untracked `uv.lock` is unchanged.

Program stays 4/8; this is not all cache freshness, dynamic consistency, release
or image-budget acceptance. Rollback is scoped commits only.
