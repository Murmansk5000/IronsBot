# Master Peak Protocol Evidence

## Verified Sources

- Official DefaultPackage version: `20260930181402`.
- GameLogic DLL MD5: `459146f1297457e3245060a9c737bf62`.
- `PeakJihadRankPanelConst` defines keys 256 (player), 257 (pet bans),
  258/259 (pet appearances/wins), 260/261 (suit appearances/wins),
  262/263 (title appearances/wins). These are game keys, not frontend tabs.
- `PeakJihadController.costlevelForever = 408302`. Its
  `updateCurLevel` reads the current packed rating, season maximum at 408304,
  and wins at 408315. Low uint16 is rank; high uint16 is points/stars.
- `PeakJihadRankPanelMain.updateView` reads `subkeyMonth` and `subkeyTotal`
  from the cost-pool config. Month keys have the 1,000,000,000 prefix.

## Live Read-Only Verification

A development login fetched keys 256 through 263 for season 20260904.
All returned records. The first player rating was 400004; that same player's
408302 and 408304 were 262148 (`4 | 4 << 16`), and 408315 was 31.
No player identifiers, nicknames, credentials or session tokens are retained.
Fixture values use synthetic identifiers.

## Unverified Capability

Neither inspected DLL publishes a confirmed per-player master match-count
field. Do not guess adjacent forever IDs or use pet/suit aggregate counts as
an individual's match count. Master match count remains `None`, its win rate
is unavailable, and four-mode total samples are not written until all four
counts are verified. The renderer explains this limitation.

## Common Season (2026-10-16)

Official ConfigPackage `20261015224012` publishes the common season starting
2026-10-16 10:00 and ending 2027-01-08 10:00 (Asia/Shanghai).
All cost rows publish `subkeyTotal=20261016`, `subkeyMonth=1020261016`;
their `time=2026_10_23 10:00:00` is a pool rotation boundary, not season end.
The application uses the published common `peak_season` for all four modes.
Monthly statistics retain the actual cost-pool subperiod and key prefix.

Sample migration 3 archives originals in `legacy_peak_metrics`, converts
master scope `20260904` to common `20260717`, and preserves sample timestamps.
Only verified four-mode pairs (equal seasons, or `20260717` + `20260904`)
convert to `peak_total_matches_v4`. Old three-mode totals and unknown pairs
are archived, not reused. Runtime pair encoding and separate master-season
lookup have been removed. Raw protocol caches are not rewritten.
