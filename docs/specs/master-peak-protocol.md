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

## Season Compatibility

Individual master samples use the master subkey. Four-mode total samples use
the exact negative integer pair `-(regular * 100000000 + master)`. This fits
SQLite int64 for eight-digit date subkeys, needs no schema migration and
excludes legacy three-mode totals. Changing either season changes the scope.
