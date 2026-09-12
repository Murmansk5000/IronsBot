# Skin Body Manifest

Status: `verified` (producer contract; release/consumer acceptance pending)

Target: producer-owned immutable skin artwork inventory. Owner: SeerAPI's
existing render_asset_manifest_build; IronsBot remains a strict consumer.

## Scope

- Collect resolved skin body_resource_id values from skin_image_resolution.
  Resolve every positive ID against the same immutable repository snapshot as
  other material kinds, using existing pet_body paths and source/blob metadata.
- Add independent skin_body completeness scope. Unknown/zero resolutions,
  absent inventory, absent snapshot or missing body blobs do not prove it.
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
