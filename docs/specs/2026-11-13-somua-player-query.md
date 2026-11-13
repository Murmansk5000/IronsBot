# 苏摩积分与排名查询

Status: completed (local implementation; no public-main release or deployment)

Contract: baseline extension of the shared player operation.

## Verified protocol

Official Windows DefaultPackage `20261111150912`, GameLogic MD5
`1a65293dcaf4fc91a31a9bfe98b73e07`, confirms personal score key `152801`
and dedicated global leaderboard `45965(flag=1,start,end)`. The response is a
uint32 count followed by uint32 player ID, uint32 score and 16-byte nickname.
The client pages 100 entries at a time and displays at most 1000.

Read-only verification on 2026-11-13 confirmed a supplied player's score and
global position independently of the developer login. Observed live positions
are not fixed regression expectations. Protocol sources and diagnostics are in
`.tmp/somua-arena-20261113` and are not source artifacts.

## Scope and boundaries

- Add 苏摩 immediately after 群星牌 in player details and support the shared
  numeric, alias, mention and bound-default shortcut paths under `seer_player`.
- Reuse rank page/confirmed-result caches, bounded lookup budgets, shared player
  sessions, permissions, request classification, cooldown and successful-work quota.
- Keep independent score and ranking failures; never substitute missing data with
  zero or call a limited/failed search a confirmed absence.
- Reuse existing detail observation TTL without extending it on reads. Do not add
  default preheating, private API or dedicated feature flag.
- Follow-up user scope adds 苏摩榜 after the 苏摩 shortcut's routing contract;
  explicit ownership prevents the shortcut stealing leaderboard input. Reuse
  shared list/range/page/score queries under seer_rank; player-target forms also
  recheck seer_player and delegate to the same Somua shortcut. Cap all live pages
  and score/position searches at 1000. No default background rank target is added.
- Do not query group-card career or Somua history: the former ignores an appended
  player argument; the latter rejects the supplied other player with 1800001.
  A linked bot user is not the authenticated game account.

## Acceptance and release

Cover exact wire parsing, malformed/truncated pages, zero score, identity and
score consistency, pagination/ties/limits, cache expiry/reuse, partial failure,
both platform inputs, target permissions, menu navigation and quota attribution.
Run targeted/full tests, Ruff, BasedPyright, compilation and repository checks in
an isolated checkout using committed reserved files only.

Create one independently verified bilingual source commit and append its clean
original archive. Do not rewrite history, push public main, build, deploy or edit
production configuration/databases. Preserve existing work and upstream SHAs.

## Verification on 2026-11-13

- Final isolated snapshot: 7017 passed, 11 skipped; Ruff, BasedPyright (zero errors),
  compileall, repository static and whitespace checks passed. The two additional
  Windows skips are inherited symlink-capability cases, not Somua coverage gaps.
- The initial snapshot had one structural-size failure in rank.py (7011 passed,
  11 skipped); moving Somua scheduling to rank_somua.py fixed it without relaxing
  the existing 800-line limit. Initial and final logs are separate executions.
- Synthetic regression covers both platform contexts, candidate selection and
  cancellation, direct numeric/alias/member/default targets, menu permission
  revocation, explicit board ownership with a visible player named 榜, zero score,
  independent failures, preserved timestamps, cache aging and ties/search caps.
- A read-only developer-account acceptance exercised the new full query path for
  the user-supplied player and completed successfully. Live scores/positions are
  evidence only, not committed fixtures; no chat test messages were sent and the
  developer account was confirmed outside the production login pool.
- Logs, exact snapshot patch, final source proof and source/archive references are
  retained under E:/IronsBot-history-validation/somua-player-query-20261113.
  Existing .gitignore work is preserved; reserved working files were not read or
  modified. Full checks used only their committed copies in the isolated tree.
