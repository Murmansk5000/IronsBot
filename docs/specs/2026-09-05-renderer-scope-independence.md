# Renderer Asset Scope Independence

Status: consumer matrix verified; compatible remote publication remains open

Contract: target, build-time completeness proof for each renderer's actual
immutable asset inputs. No runtime asset guessing or mutable-source fallback.

## Inventory

| Consumer | Published remote inputs | Other inputs / remaining boundary |
| --- | --- | --- |
| Pet info | pet head/body, element types/prop, mintmarks, optional items/sign buffs | release-owned soulmark PNG and packaged gender icon |
| Type matchup | element types | pure snapshot and packaged template |
| Peak pool/vote/pet rank | pet heads and element types | pure snapshot and packaged template |
| New content standard | pet/skin heads, types, mintmarks, suit/equip/title | mount fallback still awaits its separate publication Spec |
| Private lineup | pet heads/types and release data through public port | shares peak_pool scope and the same asset loader |
| Lucky window | skin bodies | intentionally not cache-enabled without full skin-body inventory |
| Arbitrary card URL / preview | outside immutable repository contract | no new L3 admission |

## Change

SeerAPI currently grants type/peak scopes only when pet_info is complete. This
incorrectly couples their cache availability to unrelated pet bodies and
mintmarks. Derive these two scopes from their own available manifest families,
using the existing collected inventory. Missing required entries or an absent
inventory cannot prove the scope. Do not add another inventory collector.

Keep pet_info and new_content_standard's existing conservative admission;
this slice does not declare mount, skin-body or arbitrary URL coverage. The
schema and contract version stay unchanged: only supported complete-scope
values are published. IronsBot already gates the same categories independently;
map private lineup to the existing head/type scope used by its shared loader,
instead of unnecessarily depending on pet bodies and mintmarks.

## Acceptance

- Real temporary SQLite inventory and repository-tree fixture: missing body or
  mintmark disables pet_info but not type/peak; missing head disables peak but
  not type; missing element/prop disables both.
- Optional item/sign absence does not disable unrelated mandatory scopes.
- No snapshot or unreadable inventory grants no unproven scope.
- Consumer maps each scope to exactly its renderer family, with pinned URLs
  and revision-separated caches; unlisted categories stay disabled.
- Run producer and consumer regressions, Ruff/types/compile checks, and diff
  checks. Record actual cross-repository evidence and unresolved gates.

## Release / Rollback

No production data writes or automatic publication. Commit each repo separately.
Older main consumers use the same v2 metadata keys; no old-schema compatibility
layer or new dependency is added. Revert the scoped commits to roll back.
Real remote-release download/render/cache smoke and missing upstream assets
remain Phase 4 gates; this is not complete renderer-publication acceptance.

## Evidence

- SeerAPI commit `e383e83`: 3 old completeness failures reproduced using a
  temporary SQLite inventory and immutable repository-tree fixture. Expanded
  matrix covers 20 cases, including absent standard inventory and optional
  resources. Full producer pytest: 287 passed (64.92 seconds).
- Producer Ruff, explicit script/test Ruff, changed producer module type check
  (0 errors/warnings), compileall and diff checks pass. Whole-producer type
  debt is not declared cleared by this scoped type check.
- Public renderer/cache/database regression: 64 passed; HTTP source tests:
  4 passed. After mapping lineup to the shared head/type scope, database/cache/
  lineup regression: 13 passed; private extension: 26 passed. Public Ruff,
  full public BasedPyright (0 errors/warnings), compileall and diff checks pass.
- The consumer scope matrix loads temporary SQLite through DatabaseManager
  and SeerDatabase. It verifies independent category admission and keeps
  unknown, preview and lucky-window categories unavailable. HTTP tests verify
  revision-pinned URLs; asset cache tests verify revision isolation.
- Producer production code net +9 lines; consumer changes one existing scope
  mapping. No new runtime modules, dependencies, database schema or TOML fields.
- No producer-to-consumer real remote release was published or downloaded in
  this slice. Its fixtures do not substitute for that final acceptance gate.
  Public full-suite startup timing risk from the preceding slice is unchanged;
  no full public rerun is claimed here. Local main remains `963a83c3`, read only.
- 2026-09-12 follow-up expanded the opt-in consumer test to type matchup, normal
  and expert pools, pet info, pool vote, pet rank, and private lineup. All seven
  passed against a current producer-built release and immutable remote assets;
  public full suite passed 3110 tests, private passed 43, and producer passed
  308. The downloaded `seerapi-data-latest` matched its SHA-256 but was rejected
  before rendering because it does not publish schema contract version 1.
  Publishing that compatible database and rerunning the same seven consumers is
  the remaining remote gate; no legacy-schema fallback is permitted.
