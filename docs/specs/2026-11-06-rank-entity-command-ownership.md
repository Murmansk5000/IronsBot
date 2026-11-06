# Reserve Score And Player Rank Queries From Entity Lookup

Status: `verified`

Contract: `baseline`

Owner: shared Seer query grammar and command catalog.

## Problem And Design

Production accepted three autocard score commands on 2026-11-06, but did not
start leaderboard work or send a response. The shared entity guard reserved list
queries only. Consequently the earlier autocard entity contract accepted
`群星牌榜8602分` as the card name `榜8602分` and returned a silent miss.

Extend the existing guard with the existing score and player-target parsers.
Keep one grammar owner; do not reorder platform handlers or duplicate rank syntax.
Valid score/player commands belong to rank contracts on both platforms. Unknown
rank targets remain reserved from unrelated entity lookup. Ordinary card queries
retain their current behavior. No configuration or persistence changes.

## Acceptance And Rollback

- Test the reported scores, numeric and alias player targets, and pagination
  against combined entity-first and rank contracts on both platforms.
- Preserve normal card/chip queries and existing silent unknown-query behavior.
- Run query grammar, rank ownership and portable rank regression tests plus static checks.
- Rollback is the independent fix commit; no database migration or deployment.

## Publication

Commit and archive only the independently verified fix. Preserve other work in
progress. Public development-branch publication and production deployment are
not part of this change.

## Evidence

- Shared grammar, combined command ownership, portable ranks and autocard weekly
  ownership: 662 tests passed on 2026-11-06.
- Ruff, targeted BasedPyright (zero errors), compileall and diff checks passed.
- Initial sandbox runs blocked Windows asyncio socketpair initialization;
  the complete targeted run passed outside that restriction.
- Production logs show recognition without rank work or outbound replies for the
  reported requests. The fix has not been deployed or tested through live replies.
