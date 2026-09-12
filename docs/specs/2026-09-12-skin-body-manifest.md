# Skin Body Manifest

Status: `verified` (producer contract; release/consumer acceptance pending)

Target: producer-owned immutable skin artwork inventory. Owner: SeerAPI's
existing render_asset_manifest_build; IronsBot remains a strict consumer.

## Scope

- Collect the effective body ID for every pet_skin row: positive resolved
  body_resource_id first, otherwise the catalogue resource_id, exactly as in
  the consumer. Include resolution-only rows and deduplicate resource IDs.
  Resolve against the same immutable repository snapshot as other material kinds.
- Add independent skin_body completeness scope. Invalid effective IDs, missing
  catalogue/resolution schema, empty inventory, absent snapshot or missing body
  blobs do not prove it. Zero resolution may use a valid catalogue fallback.
- Deduplicate body entries already represented by the base-pet inventory.
  Skin-body incompleteness does not suppress type/peak/pet or standard scopes.
- Preserve existing tables/version and use the current manifest writer/hash;
  no second asset repository, network fetch or runtime SWF path.
- Do not enable lucky-window L3 yet: offer resource fallbacks, complete request
  keys and real release consumer smoke remain required before that change.

## Verification And Release

SeerAPI tests cover complete/missing/unresolved/empty bodies, independent scopes,
deduplication and changed blob revision. Run focused builder tests and lint.
Commit producer first, then record consumer ledger. No push/release/production
replacement in this item. Rollback is producer commit revert.

Program 4/8; item estimate 30-60 minutes, overall ETA unestablished.
Producer commit: `ce42f5f`. Builder module: 80 passed in 15.88 seconds; focused
manifest/scope cases: 34 passed. Ruff, targeted BasedPyright on the manifest
module (0 errors/warnings), compileall and diff checks passed. The type checker
was invoked from the public workspace environment because the producer has no
local basedpyright executable. No full producer type-clean claim.

IronsBot runtime was not changed. Existing consumer still does not advertise
lucky-window cache scope. Next gate is a real revision-pinned release inventory
and consumer request/material coverage, including unresolved offer fallbacks.

## Real Inventory And Consumer Key

Read-only verification of the public release on 2026-09-12:

- SQLite SHA256: `a9dabe9c1b5414c672fdf65323934933d8304b467f64c0c93e49b2f2232de705`.
- Config package: `20260911183817`; SQLite quick_check: `ok`.
- Asset revision: `1b53a16cfe32d36d921a04fbd8423116c5b1e2e1`, 42,196 blobs.
  REST recursive tree returned HTTP 500; existing blob-free Git adapter succeeded.
- All 268 resolution rows have positive body IDs and corresponding immutable
  body blobs. New producer skin_body proof succeeds for this resolved inventory.
- The full pet_skin table has 868 rows. This is NOT proof of coverage for every
  dynamic offer or all skins, and the published database has no new manifest.

Replace the consumer's hand-built/truncated hash with render_request_cache_key.
Hash day, player identity and the actual ordered offer dataclasses, including
names, resource IDs and watch state. Do not hash from_cache: it changes delivery
provenance, not rendered pixels. Do not enable category scope in this batch.
Regression covers changed offer fields/order and an early hit that cannot query
the repository, load images or invoke native rendering. Run only the affected
rendering/cache tests and static checks; no deployment or real browser claim.

Consumer verification: 6 focused rendering/cache tests passed in 2.05 seconds;
Ruff and targeted BasedPyright passed (0 errors/warnings). No full-suite rerun.

## Full Catalogue Follow-Up

The first proof covered only resolved entries. The target now includes all
catalogue fallback requests, not just those 268 rows. An overridden catalogue
resource must not be required; resolution-only rows remain represented.
Tests cover override precedence, absent and zero-resolution fallbacks, duplicate
body IDs, a missing fallback blob and a missing catalogue schema.

Against the same SQLite hash and asset revision above: 868 effective body IDs,
867 available, missing `1400840` (skin 840, pet 4911). The full `skin_body` scope
correctly remains incomplete. This is an upstream material gap, not evidence
that a partial inventory is enough. No consumer scope or runtime fallback was
enabled. Builder module: 83 passed in 18.52 seconds; Ruff, targeted BasedPyright
(0 errors/warnings), compileall and diff checks passed. No new tables/modules.

## Incomplete Material Cache Policy

Target contract: optional image failures may produce a degraded reply, never a
durable final-cache hit. Reuse fetch_optional_image for lucky-window materials;
delete its private exception wrapper. Preserve missing/invalid-resource cards,
but cache only when all requested cards have images. Pet-info optional item and
status images follow the same policy: material loading reports completeness to
its integration, not the pure presenter. A subsequent request retries failures;
after recovery, an early cache hit skips repository, image and rendering work.
No new service, TOML flag or cache scope. Verify degradation/recovery/early-hit
paths in the two adapter tests alongside the existing request-key regressions.

Verified: 15 targeted adapter/presentation/key tests passed in 2.16 seconds;
targeted BasedPyright reports 0 errors/warnings; Ruff and diff checks passed.
The lucky-window adapter also deduplicates equal positive body resource IDs
before optional loading. Invalid IDs retain blank cards and suppress cache
writes. Pet-info completeness stays in the integration, not the presentation
model. These tests use fake image/render ports; no browser or deployment claim.
Other adapters' mandatory image fallback behaviour is outside this batch's
verified scope and still requires review before complete Phase 4 acceptance.
