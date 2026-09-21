# Render Asset Degradation And Lineup Fallback Freshness

Status: `completed`

Acceptance completed on 2026-10-31; documentation status corrected on 2026-11-06.

Contract: `baseline`

Owner: public render sessions, published image source, public lineup cache port.

## Problem And Goal

Production lineup requests on 2026-10-31 fetched current packets successfully,
then failed on head downloads and silently returned an undated persistent reply
from 2026-10-16. Peak vote rendering also aborts on individual asset failures.
Preserve current data, isolate failed assets, and bound reply fallback by the
existing player observation TTL. Network recovery is an independent operation.

## Ownership And Reuse

- Keep verified image origins, source order, request isolation and real data errors.
- Public render sessions own per-render failures, placeholders, aggregated notices
  and suppression of incomplete final cache writes; original-image commands do
  not use presentation fallback.
- Public extension ports expose image completeness and actual observation time.
- Public lineup storage alone owns TTL, using `background_refresh.cache_ttl_seconds`.
- Private main/details always request live data; only eligible failures may use a
  fresh complete reply, labelled with the original time and current failure.

## Delivery Slices

| Slice | Acceptance | Status |
| --- | --- | --- |
| Workflow | Independent original commits archived before folding | completed; original snapshots archived |
| Network | Router node only; both PNG origins and deployed vote render verified | completed on 2026-10-31; not a current health claim |
| Assets | Individual failures degrade; no incomplete final/reply cache | completed; verified and published |
| Freshness | Actual fetched time, no renewal, deny stale/undated/unauthorized fallback | completed; verified and published |
| Private | main/details consume public quality and freshness ports | completed; paired versions published |
| History | Original heads/bundles verified; separate historical owners and paired release | completed; bundles restored, history folded and archived |

## Data And Rollback

Lineup SQLite gains nullable source observation time through a startup migration.
Old undated rows cannot be fallback evidence; migration does not invent a time.
No production SQLite edits or TOML changes. Router operations change only the
selected node and restore the original on unsuccessful recovery. No bot deployment.

## Acceptance Tests

- Every public render entry uses the shared session; healthy assets are unchanged.
- Connection, HTTP, validation and decode errors affect only the failed asset;
  cancellation, data errors and native renderer errors remain failures.
- Degraded images and placeholder bytes never enter final/reply or asset caches.
- Notice failures do not interrupt rendering; failures are aggregated once.
- Lineup always queries live; fresh fallback is labelled, stale and unknown times
  are rejected, reading does not renew TTL, denied access/quota never falls back.
- Network checks return decoded, verified PNGs from both origins; deployed vote
  output has real heads/icons. Isolated fault injection does not alter production.
- Run scoped and full regression/static checks without touching the reserved
  mintmark resolver files. Preserve private `uv.lock`, `tools/` and font caches.

## Publication

Public originals were appended to IronsBot-History-Archive/main; private originals
were appended to archive/original-main and archive/original-details. Source
reachability, exact trees and complete E-drive bundle restoration were verified
before historical rewriting. The original asset owner 7d0befbc2, public freshness
owner 54137a5ff and private fallback owner bd40697 were located through explicit
commit maps; later interfaces and renderers were adapted at introduction.
The details fork predates bd40697, so its corresponding public-port introduction
was used instead. These IDs describe original historical owners, not current pins.
Public and paired private main/details versions were published and archived;
successful image builds were verified independently of production deployment.

## Evidence

Baseline: public f164b108. On 2026-10-31 the original Hong Kong IEPL 01 node
failed container TLS requests. Japan IEPL 02 restored both pinned GitHub and
jsDelivr PNG requests (HTTP 200, decoded 50,008-byte images). OpenClash persisted
the selector through its existing store-selected setting; no rules were changed.
The deployed vote query and renderer generated a 960 x 967 PNG containing all
20 real heads and type icons. No chat message was sent and no image was deployed.

Evidence root: `E:/IronsBot-history-validation/render-lineup-recovery-20261031/`;
vote output: `deployed-peak-vote.png`, request summary: `deployed-vote.json`.
Public originals b7453af68 and adfb98c7e implement asset quality and freshness.
Initial-stage public regression: 6,681 passed, 9 skipped, excluding the reserved test; Ruff
passed and BasedPyright reported zero errors or warnings. Private main: 55 passed,
1 skipped; details: 93 passed, 1 skipped. These are the original stage results,
not the final acceptance totals below.

## Final Acceptance (2026-10-31)

The evidence root's `completion.json` records
`published_archived_and_fully_verified`, completed at 2026-10-31 15:05:06 +08:00.
It retains the original commit and archive IDs, bundle checksums, rewrite owners,
paired versions, image digest and workflow results; subsequent history rewrites
do not change these original evidence references.

- Rewritten public full regression: 6,697 passed, 9 skipped, both locally and in CI.
- Rewritten public scoped regression: 82 passed. Historical public assets:
  57 passed, with two recorded historical model warnings; historical freshness:
  4 passed. The asset check used the historical lock in an isolated Python 3.11
  environment after an incompatible current-environment attempt was diagnosed.
- Final private main: 56 passed, 1 skipped; details: 94 passed, 1 skipped.
  Historical private checks: 3 passed; historical details checks: 23 passed.
- Ruff, BasedPyright and compile checks passed. Supplemental tests used committed
  reserved-file copies in E-drive isolation, without accessing the two original
  reserved working files. Complete bundles were restored and original commits
  remained reachable in cumulative archives.
- The network evidence is the October 31 node selection and decoded PNG checks
  above, plus the deployed vote render with 20 real heads and type icons.
  It does not assert current node health or perform a new network operation.
- No new application image was deployed during this work; production TOML,
  production databases and other containers were not modified.

Successful original publication and archive workflow records:

| Source | Image publication | Original-history archive |
| --- | --- | --- |
| Public | [Build 41178455139](https://github.com/Murmansk5000/IronsBot/actions/runs/41178455139) | [Archive 41178455137](https://github.com/Murmansk5000/IronsBot/actions/runs/41178455137) |
| Private main | [Build 41178897225](https://github.com/Murmansk5000/ironsbot-private/actions/runs/41178897225) | [Archive 41178897522](https://github.com/Murmansk5000/ironsbot-private/actions/runs/41178897522) |
| Private details | [Build 41178906402](https://github.com/Murmansk5000/ironsbot-private/actions/runs/41178906402) | [Archive 41178906608](https://github.com/Murmansk5000/ironsbot-private/actions/runs/41178906608) |

The 2026-11-06 correction reconciles this document with that completed record;
it adds no implementation, business tests, deployment or new production checks.
