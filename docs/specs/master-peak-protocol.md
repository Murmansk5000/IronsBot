# Master Peak Protocol Evidence

## Verified Sources

- Official DefaultPackage version: `20260930181402`.
- GameLogic DLL MD5: `459146f1297457e3245060a9c737bf62`.
- `PeakJihadRankPanelConst` defines keys 256 (player), 257 (pet bans),
  258/259 (pet appearances/wins), 260/261 (suit appearances/wins),
  262/263 (title appearances/wins). These are game keys, not frontend tabs.
- The earlier `PeakJihadController` inspection reads 408302, 408304 and
  408315. These controller fields are not the personal-card statistics contract.
  In particular, 408304 must not be labelled as the player's historical maximum,
  and 408315 must not be used as personal wins or converted into new samples.
- `PeakJihadRankPanelMain.updateView` reads `subkeyMonth` and `subkeyTotal`
  from the cost-pool config. Month keys have the 1,000,000,000 prefix.

## Live Read-Only Verification

A development login fetched keys 256 through 263 for season 20260904.
All returned records. The first player rating was 400004; that same player's
408302 and 408304 were 262148 (`4 | 4 << 16`), and 408315 was 31.
No player identifiers, nicknames, credentials or session tokens are retained.
Fixture values use synthetic identifiers.

## Personal Card Correction (verified 2026-10-28)

The earlier "match-count field unverified" conclusion is superseded by the
official Windows DefaultPackage `20261026161231`, retrieved and version-checked
at `2026-10-27T16:18:59Z`. GameLogic.dll is 28,192,768 bytes:

- SHA256: `49600acf5af26ca40e8dfeb087a61c2af273ea085780027f06a918abd4f7ae13`.
- MD5: `58064e3d768fbda81361f18e44bf6689`.
- Source: `https://newseer.61.com/Assets/StandaloneWindows64/DefaultPackage/`.

`module.personalInformation.Card.PersonalinformationIdCardPopView` initializes
four arrays in `.cctor` (method row 27843). Their order is sport, cost/master,
wild, expert; the master element is index 1:

| Personal statistic | Array | Master key |
| --- | --- | --- |
| Current rating | PeakJihadForeverCurScore | 408302 |
| Historical maximum | PeakJihadForeverMaxScore | 408303 |
| Wins | PeakJihadForeverWinCount | 408306 |
| Matches | PeakJihadForeverMatchCount | 408307 |

`GetPeakJihadModeSuffix`, `GetPeakJihadForeverId`, `updatePeakJihadView` and its
callbacks consume these arrays. The current/maximum callbacks unpack the low
uint16 rank and high uint16 points/stars. The wins callback requests MatchCount
and the result callback combines the two counters. Static FieldRVA array
contents and actual IL consumers, not adjacency of numeric keys, establish
this mapping. This is later protocol evidence folded into the historical
feature; it does not claim that the October 26 client existed on October 11.

The application reads sixteen uint32 slots across four modes. Truncated or
extra fields are rejected. Partial requests retain fixed slots and mark failed
modes unavailable rather than supplying real zero statistics. A valid zero
match count does not produce a percentage. Invalid counts produce an explicit
error and no win-rate/match samples or four-mode total. Failed rank lookups do
not overwrite successful personal statistics.

Master observations include the four-field parameter tuple in their cache
identity; composed peak replies include the protocol schema and season. Other
mode observations and ranking caches are not reset. No legacy counter is
converted, and no historical match count is inferred.

No real-player query was performed in this change. Real-account verification
remains a separate external acceptance item.

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
