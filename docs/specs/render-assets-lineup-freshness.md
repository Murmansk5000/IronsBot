# Render Asset Degradation And Lineup Fallback Freshness

Status: `in_progress`

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
| Workflow | Independent original commits archived before folding | in_progress |
| Network | Router node only; both PNG origins and deployed vote render verified | verified locally |
| Assets | Individual failures degrade; no incomplete final/reply cache | verified locally; publication pending |
| Freshness | Actual fetched time, no renewal, deny stale/undated/unauthorized fallback | verified locally; publication pending |
| Private | main/details consume public quality and freshness ports | verified locally; pairing pending |
| History | Original heads/bundles verified; separate historical owners and paired release | pending |

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

Public originals append to IronsBot-History-Archive/main; private originals append
to archive/original-main and archive/original-details. Confirm SHA reachability,
exact trees and a complete restorable E-drive bundle before rewrites. Fold asset
behavior into 7d0befbc2 (later renderers at introduction), public freshness into
54137a5ff and private fallback into bd40697 through explicit commit maps. Publish
public code first, then paired private main/details with exact leases; verify
archives and Docker builds separately from production deployment.

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
Public regression: 6,681 passed, 9 skipped, excluding the reserved test; Ruff
passed and BasedPyright reported zero errors or warnings. Private main: 55 passed,
1 skipped; details: 93 passed, 1 skipped. Historical folding, paired publication,
bundle restoration and image publication remain separate pending gates.
