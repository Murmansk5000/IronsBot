# Score Probe Exhaustion

Status: `verified`

Contract: `target` explicit incomplete-result semantics, Phase 6

Owner: `services.seer` score range query and its formatter

## Evidence

A controlled 100-entry descending board contains score 125 at rank 76. With a
probe count of 1, the service reads pages 90-99 and 50-59. The algorithm reports
budget exhaustion, but `RankScoreSearchResult` drops it and the formatter claims
there are no score-125 users in the first 100 ranks. No official API was used.
The same loss affects tail-boundary exhaustion and upper-bound exhaustion; the
latter exposes a fallback scan endpoint as an exact same-score population.

## Target

- Carry the existing algorithm's `budget_exhausted` flag through the score
  result. Do not introduce another status registry, parser or retry mechanism.
- Check this state before interpreting an empty result as missing data or a
  confirmed absence. Explain that the probe limit was reached and the complete
  same-score range remains unconfirmed.
- Retain matches obtained during the bounded fallback scan. In this state,
  result population and endpoint describe only collected matching items, not
  the guessed scan endpoint. The formatter labels them as confirmed samples,
  never an exact total or an unverified contiguous interval.
- Preserve source time, page limits, stage budgets, bounded fallback scanning,
  exact gap proofs, normal boundary rejection and fully confirmed samples.
- No TOML, schema, dependency, deployment or main change. Cache-candidate
  completeness, dynamic rank movement and global probe-budget policy remain
  separate audits; do not silently change them in this slice.

## Acceptance

- [x] Tail-boundary and lower-bound exhaustion cannot produce an absence claim.
- [x] Upper-bound exhaustion retains real matching rows without inventing an
  exact range/population from the fallback endpoint.
- [x] A genuine boundary rejection and a fully located score range are unchanged.
- [x] Focused and public/private regression, Ruff, typing, compileall and diff
  checks pass. No live QQ or official API validation is claimed.

## Verification

- Five new service-to-formatter cases in `test_rank_score_search_service.py`
  initially failed. Three reproduced incorrect absence/population messages;
  two checked the new state contract on unchanged normal paths. All now pass.
- The upper-bound fixture contains exactly three matches at indexes 6-8; with
  a six-probe budget, the old response incorrectly claimed ranks 7-16 and ten
  users. It now retains the three observed users, labels them confirmed samples,
  and explains that the complete range is unconfirmed.
- Focused regression: **114 passed**. Full public: **2400 passed, 274 dependency
  warnings, 141.50 seconds**. Private: **26 passed** against this worktree.
- Ruff, BasedPyright (0 errors/warnings), compileall and diff checks passed.
  Production code net change: **+14 lines** across three existing modules;
  no new runtime module, dependency, schema or configuration.
- No fetch/pull/merge/push or production writes. Local main remains `f19c7089`.
  This does not change per-stage budgets. Candidate edge/interior completeness
  is now verified separately in [cache coverage](2026-09-05-score-cache-coverage.md),
  without claiming that multiple live pages form an atomic snapshot.

Program remains 4/8 verified phases; overall completion and image-size reduction
are unproven. Rollback is scoped commits only.
