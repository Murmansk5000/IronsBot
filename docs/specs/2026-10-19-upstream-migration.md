# Upstream feature migration and history integration

Status: `implementing`

Contract: `target`

Owner: Seer presentation, messaging topics, headless protocol integrations

## Baseline and execution order

The accepted baseline is `168a800eeca628dd6280b8eadaa23ca9ec40e414`.
The audited upstream endpoint is `e42b71731f1f38516b280e1fcd28e06dd702741c`.
Implement absent capabilities first, improve accepted behavior second, ask about
remaining behavior conflicts third, and construct historical candidates only
after the final behavior and tests have been accepted. Preserve existing history
and backup refs. No publishing, deployment or production configuration changes.

## Ownership and reuse

- Topic subscriptions reuse platform identities, feature policy, TD preferences,
  application-owned scheduling and the existing outbound delivery boundary.
- Pet flip uses structured mentions and the shared type multiplier calculation;
  platform adapters do not own its rules.
- Maintenance packet decoding belongs to the headless integration; notification
  policy belongs to the operations service and existing notice delivery.
- Pet presentation consumes detached snapshots; effect relationships come from
  the project's SeerAPI producer, not runtime text inference.

## Accepted behavior

Topics expose registration, discovery, enable/disable, deletion, subscriptions,
broadcasts and delivery history. Programmatic topics can supply content and
interval/cron/date schedules and cannot be deleted through chat. Superusers
manage topics and broadcasts; group administrators manage their own group;
private actors manage themselves. Retain 500 history entries per topic and use
a 3600-second explicit deduplication window. No automatic subscriptions.

Pet flip requires two different member targets and two different random pets.
Ignore the receiving bot and all-member mentions. Compare both type attack
multipliers and break ties by pet ID. Missing avatars do not suppress results.

Packet 41457 decodes network-order unsigned Unix seconds using the fixed client
implementation linked in the maintenance spec. Delivery failures are isolated;
equal deadlines are deduplicated across workers and corrections can notify.
Invalid or expired values do not produce user notifications. Generated protocol
fixtures verify the implementation and are not live server captures.

Pet information retains upstream dimensions (64px avatar, 32px default name),
uses zero letter spacing and does not truncate names. Height/weight appear in
the header and use unknown for missing values; food belongs to the introduction
and is omitted when empty. Flip only the pet-information body artwork once.
Add BOSS annotations per analyzed soulmark segment only when not already
explicit. Preserve local asset failure placeholders and invalidate stale renders
through the existing source/data fingerprint mechanism.

## Upstream disposition ledger

| Source | Behavior | Disposition |
| --- | --- | --- |
| 0a7cf83c | Per-segment soulmark BOSS description | Implement in detached presentation |
| 8e477540 | Flip pet information artwork | Implement once in render preparation |
| 1039b981 | Upgrade SeerAPI models | Keep own producer; pin only reproducible contract |
| 1fc66237 | Encyclopedia height/weight/food | Extend existing snapshot |
| fe04c674 | Move encyclopedia introduction | Keep accepted local layout and upstream sizes |
| 1fd5f36c | Linked glossary display | Precompute relationships in own producer |
| e84f5eb1 | Renderer class reorganization | Keep current detached rendering architecture |
| 34dddb85 | Deduplicate glossary matches | Stable identity deduplication |
| e702bccd | Remove announcement login gate | Accepted: actual connection determines readiness |
| c153eabb | More accurate server status | Preserve richer current status; verify parity |
| a9e85bbc | Manual database synchronization | Accepted: keep primary commands; add sync aliases |
| 01ca59c7 | Detailed skin prices | Accepted: supplement missing model facts; retain current window name and ticket arithmetic |
| 457f3a58 | General topic push | Implement using existing delivery and TD |
| 1c12285b | Data update notification | Existing d2556727; verify no duplicate trigger |
| 9f1d3b93 | Headless state/maintenance notices | Keep state notices; add 41457 boundary |
| 4d43561e | Compose environment examples | Update only affected current deployment docs |
| 702f7c81 | Version 0.6.0 | Historical release boundary after feature decisions |
| ee92bcbd | Match before permission denial | Preserve current command ownership; test topics |
| 561a7ba7 | Version 0.6.1 | Historical release boundary after feature decisions |
| b519b726 | Peak pool timezone handling | Verify current time contract; no duplicate helper |
| 7e7009db | Shared type calculation | Reuse current shared calculator |
| 7111861d | Pet flip | Implement shared two-platform command |
| e42b7173 | Version 0.7.0 | Final historical release boundary |

## User decisions

- Announcement presence must not prevent login. Server-status queries still
  consult the announcement and report actual connection state.
- Keep `/更新数据` and `/强制更新数据` as primary commands. Add `/同步数据`
  and `/强制同步数据` to their existing alias sets and selection workflow.
- Keep the current lucky-window label. SeerAPI publishes explicit coupon
  deduction facts with provenance; IronsBot calculates only from those facts,
  never from a hardcoded item ID, face value or runtime description parsing.
  Items without verified rules show names and quantities without inferred
  discounts or minimum prices. The published fashion-ticket description proves
  ten diamonds per ticket; it does not establish values for other items.
  Positive detailed prices win; model facts supplement absent/zero fields.
- For direct-hit/linked grouping, follow the author's subordinate precedence:
  an effect linked by another matched effect remains an associated explanation,
  with its direct evidence retained. Cycles stay in their existing partitions,
  display each effect once and show references instead of recursive expansion.
- Preserve the project's display positions. Effects stay in the dedicated
  special-effects section, never underneath individual skills or soulmarks.
  The original author's 3549 image is a comparison artifact only.

## Verification boundaries

Each functional group requires focused pytest, Ruff, BasedPyright, compileall
and whitespace validation before commit. Final verification includes the full
public suite, private extension contract pairing, repository static checks,
Git integrity, historical node trees and source-to-candidate SHA mappings.
Use isolated test data and do not connect production bots.

Changes requiring a new SeerAPI release remain unverified for clean remote
installation until that producer revision is actually available. Record that
gate rather than pinning an unpublished SHA or adding runtime schema fallback.
The coupon-deduction contract is such a change: publish the matching SeerAPI
database before deploying the consumer. It does not require a TOML/env migration
or a new Python model package. Do not modify production data to simulate a
published release.

## Progress

Fixed weights: baseline audit 10%, absent capabilities 30%, improvements 25%,
conflict decisions 10%, history and final acceptance 25%. Only verified results
count. Verified functional progress is 75%: audit 10%, absent capabilities 30%,
improvements 25%, decisions 10%. The maintenance time contract is confirmed by
independent client code. Historical reconstruction and final candidate
acceptance have not been completed; real server delivery remains a separate
live acceptance item.

## Functional verification, 2026-10-19

- Public full suite after the coupon contract: 4881 passed, 7 skipped. Public Ruff, production and test
  BasedPyright, compileall, static repository checks and whitespace checks pass.
- Private extension tests against the modified public runtime: 49 passed,
  1 skipped; public extension contract subset: 16 passed. Its tracked source and
  published runtime pin were not changed by these functional additions.
- SeerAPI relationship tests: 15 passed, targeted Ruff and BasedPyright pass.
  The earlier effect-relationship changes document and test the existing
  contract. The later coupon contract adds a release sidecar table and requires
  a matching data release; neither change needs a model dependency pin update.
- Coupon producer rule/build tests: 112 passed; publication contract tests:
  3 passed. Read-only release-to-memory replay emits one rule (fashion ticket,
  ten diamonds) and the consumer reads its name and deduction in one query.
  Unknown rules never acquire an inferred value. Producer commit: `b0253e3`.
- The released `seerapi-data-latest` asset from `Murmansk-Seer/seerapi` matches
  SHA256 `92bb0d8f4db05d64adeae0a367bd2c2399ab407d02079c8dd1cced4b53402a6b`.
  Read-only replay loads 627 pets, 993 effect facts and 76 parent references,
  with unique identities and no missing parent or child references.
- The original upstream `e42b7173` renderer produced a 1200x6824 image for pet
  3549 in the E-drive audit directory. It is a comparison artifact; the accepted
  project layout remains unchanged. All six image requests returned HTTP 200.
- Full Git integrity checks pass. Complete before/after functional bundles are
  verified on E. Existing dangling historical objects are retained.

The seven local functional commits are `8641150c`, `b5d06d73`, `b8359686`,
`a435c712`, `f6306a3e`, `ba7b635d` and `a66d4429`. Their current times are
implementation evidence, not the proposed historical insertion dates. All
remote refs, production configuration and production databases remain unchanged.
