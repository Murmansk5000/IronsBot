# Shared Asset Fetch Ownership

Status: verified (focused contract). Target: the existing SeerAssetStore owns shared material
work; a caller owns only its wait. No dependency on runtime user deduplication.

## Contract

- One task per material key covers disk read, network request and cache write.
- Every caller shields its wait, including the first caller. Cancelling one
  request cannot cancel other callers' work or force a second download.
- Hold shared tasks until completion; remove completed entries and consume
  exceptions even when all callers have left. An abandoned completed download
  may populate the bounded cache. HTTP timeouts remain owned by the HTTP port.
- Keep existing source-revision keys, verified disk writes, network semaphore
  and negative caching. Transient failures remain retryable.
- Task lookup/creation has no await and is atomic on the application's event
  loop; remove the redundant future forwarding and lock machinery.

## Verification

Test first/follower cancellation, one surviving result, shared failure followed
by successful retry, and the existing disk/corruption/revision/negative-cache
cases. Run the asset store and HTTP integration tests plus targeted static
checks. No production configuration or runtime image changes. Phase 4 remains
incomplete; this item is not a release/deployment acceptance claim.

## Evidence

Asset-store plus HTTP integration tests: 13 passed in 12.95 seconds. After the
abandoned-waiter regression was added, the final asset-store module passed all
9 cases in 0.47 seconds. Ruff, targeted BasedPyright (0 errors/warnings),
compileall and diff checks passed. Cancellation tests use a gated source and
assert one network fetch; the failure test asserts both waiters receive the
error and a later request retries successfully. No new production module or
dependency; existing source revision separation and corruption tests retained.

## Immutable Request Preparation

Target: the upstream source synchronously prepares a request with one captured
identity and executable download operation. The HTTP implementation captures
the published snapshot once and freezes all candidate URLs before any await.
The asset store hashes that prepared identity and executes that same operation
after disk/network admission. Delete the independent source_identity_getter
from store construction and application composition; no legacy fallback.
Use a new asset-key namespace so previous potentially mismatched records cannot
be reused. Keep the public image-consumer port unchanged. Regression switches
the snapshot while a request is queued and checks URL revision, response bytes,
and subsequent cache isolation. Final-render multi-material snapshot ownership
is a separate remaining requirement, not claimed solved by this item.

Verified: 15 HTTP/material-cache tests passed in 12.42 seconds; 7 database
version tests passed in 8.59 seconds (2 existing ORM relationship warnings).
Ruff, targeted BasedPyright (0 errors/warnings), compileall and diff checks
passed. The regression changes the snapshot after prepare signals capture but
before queued I/O executes, verifies old/new URL bytes, then returns to the old
revision and verifies the cached bytes without another HTTP request. Removed
the now-unused database render_asset_cache_identity method. The consumer-facing
SeerImageSource remains unchanged; only upstream storage input uses prepared
requests. No old identity-getter compatibility path or new module/dependency.

## Final Render Entry Ownership

Target: RenderCache.entry(category, request_key) returns one RenderCacheEntry
whose get/put operations share a captured version and scope decision. Unknown or
unavailable entries cannot gain write permission later. A changed version or
revoked scope prevents reads and writes through that entry. Change the physical
key namespace to reject older potentially mixed-version images.

Migrate all seven public cached renderers and the private lineup extension to
retain one entry across their awaits. Delete separate cache get/put and private
cached_image/cache_image methods; keep no compatibility wrappers. The public
extension contract re-exports the same entry type rather than a duplicate type.
Storage tests cover version changes during render, late old writes, unknown
versions, scope grants/revocations, corruption and cleanup. Public/private
renderer regressions retain early-hit and incomplete-material checks.

This prevents persistence of work crossing a detected version change; it does
not yet guarantee every returned multi-material image came from one repository
snapshot, or detect an old-new-old ABA switch. Those remain explicit acceptance
gaps rather than a reason to claim the whole render transaction is complete.

Verified: public rendering/storage 49 passed (3.75s), architecture/extension
boundaries 20 passed (2.41s), private repository 26 passed (2.32s). Public Ruff
and BasedPyright over ironsbot/tests passed (0 type errors/warnings), private
changed files passed Ruff using the public environment executable, compileall
and diff checks passed. No full public pytest rerun. Public and private must
ship together because the old render-port methods were removed; no production
deployment in this batch. The private untracked uv.lock was left untouched.

## Database Publication Prerequisite

The load path currently disposes staged engines only on validator failure;
source-open/backup failures bypass cleanup. It also opens source files with a
write-capable helper, allowing a missing source to become an empty database.
Target: use the existing shared read-only connection helper, close the source
and destination handles, and dispose the staged engine on every pre-publication
failure. Preserve the active engine and do not notify listeners on rejection.
Tests use real missing/corrupt SQLite files and a tracked engine dispose method.
This is prerequisite lifecycle hardening, not completion of render snapshots.

Verified: database-manager/version tests 14 passed in 6.75 seconds, with 2
existing ORM relationship warnings. Ruff, targeted BasedPyright (0 errors and
warnings), compileall and diff checks passed. Failure tests check candidate
dispose exactly once, no listener call, unchanged engine identity and readable
old data; missing-file case also proves no source directory was created.

## Engine Snapshot Lifetime

Target: DatabaseManager.snapshot(names) leases immutable engine references,
without holding SQL sessions open. Publication immediately swaps the active
engine; disposal waits until the last snapshot releases the retired engine.
session/all_sessions share this lifetime mechanism; register and close retire
engines through the same path. Protect registry/reference bookkeeping with an
RLock, never held while user query code runs. No file copies or new database.
Tests query old and new data across a load, share multiple leases, and verify
disposal only after the last lease (including close/re-register paths).
This establishes the generic prerequisite; renderers still need to bind their
metadata/image/cache transaction to the snapshot before phase acceptance.

Verified: database-manager/version tests 19 passed in 7.37 seconds, with 2
existing ORM relationship warnings. The threaded publication test keeps a
single-database session open, publishes on another thread with a bounded wait,
and reads old/new values through the respective sessions. Nested snapshots and
all_sessions verify exactly-once retirement after the final lease; exception
exit also releases the engine. Ruff, targeted BasedPyright (0 errors/warnings),
compileall and diff checks passed. No dependency, configuration or schema change.
This does not claim thread-safe listener publication or full renderer snapshot
binding; the lock protects registry and reference lifetime bookkeeping only.

## Engine-Owned Publication Metadata

Target: replace the SeerDatabase listener-owned version/scopes/assets fields
with one immutable publication record per engine. Prepare it during validation
before engine replacement; constructor attachment to an already loaded engine
uses the same reader. Read the record for the actual leased engine, not the last
listener to finish. Weak engine keys permit retirement without a growing
publication history. Repeated version/scope/image lookups must not run SQL.
Tests inspect metadata inside an earlier load listener, after close/register,
and after rejected loads; late construction and cache-hit SQL counts are covered.
This is a render-transaction prerequisite, not yet a binding of all render inputs.

Verified: registry, publication, mintmark query, pet rendering and data-sync
tests 42 passed in 10.55 seconds (2 existing ORM relationship warnings).
Earlier-listener observations see the candidate manifest, rejected schema loads
retain the active record, late attachment reads an already published database,
and an SQL execution spy proves repeated metadata reads execute no SQL.
Close/re-register return unknown rather than stale publication information.
Ruff, targeted BasedPyright (0 errors/warnings), compileall and diff checks passed.
Removed the old listener-owned fields and refresh callback; production code is
9 lines smaller. No new module, dependency, config field or publication run.

## Explicit Read Snapshot

Target: SeerDatabase.read_snapshot() exposes a query-only SeerReadSnapshot with
the same immutable SeerPublication used for version/assets/scope selection.
Keep the engine leased across preparation/download awaits, but open SQL sessions
only for individual repository operations. Existing query() uses this same path.
After context exit, discard the engine reference and reject further queries;
publication value objects may safely outlive the lease. No ContextVar/global
render state, SQL session held during network I/O, or duplicate category mapping.
Test a suspended render read across replacement and close, and verify old/new
query values agree with their respective publication records.

Verified: registry/version/mintmark/pet-render/data-sync regression 43 passed
in 10.80s; after making publication access read-only and naming the closed-snapshot
error, the await/replacement test passed again (2.33s). Both runs report 2 existing
ORM relationship warnings. Ruff, targeted BasedPyright (0 errors/warnings),
compileall and diff checks passed. query() now consumes the snapshot directly;
asset/cache binding at composition boundaries remains outstanding. No runtime
dependencies, configuration changes or new database copies.

## Bound Render Inputs

Target: SeerRenderSessions.open() composes one read snapshot, an HTTP image
source pinned to its publication, and a final-cache view with the same release
and renderer fingerprint. Bound asset sources share the existing cache,
singleflight map and network semaphore, rather than constructing new stores.
Fully bound final-cache entries use a fresh namespace and may finish writing
their original version after an update, without contaminating the new release.
Unknown/unproven scopes remain non-cacheable. Pet-info composition is the first
consumer; other public renderers and the private extension remain to migrate.
Test interleaved old/new sessions with real SQLite and MockTransport, including
late old writes, cache hits without repository SQL, and shared asset fetches.

Verified: assets/final-cache/publication/version/pet-adapter regression 37 passed
in 18.19s (2 existing ORM relationship warnings); architecture, size, application
catalog and final asset-source regressions 30 passed in 3.43s. Ruff over
ironsbot/tests passed. Whole-tree BasedPyright found only three fake-source
keyword-name mismatches; correcting that fixture passed the targeted type check.
Compileall and diff checks passed. No runtime dependency, extra store instance,
TOML or private-contract changes. Added the minimal SeerDataReader protocol so
the pet adapter accepts a snapshot without requiring unrelated search methods.

The production pet-info callback now opens SeerRenderSessions before cache
lookup or repository access. The SQLite/MockTransport test switches manifests
and asset revisions between awaits, confirms old-source requests after the
switch, and restores the original release with matching cached bytes. This
is not a real-platform/pixel acceptance test. Other renderer callbacks may
receive data prepared earlier by their service, so migrating them requires
moving the snapshot boundary before that preparation, not merely wrapping an
already-built view model at render time.

## Type-Matchup Preparation Boundary

Target: the type-query service accepts a context-managed reader/renderer pair.
Its dataset load, pure matchup calculation and rendering use the same bound
session from composition. Close the repository SQL session before awaiting
rendering, but retain the engine lease until rendering completes or fails.
Name/alias selection still yields request IDs; no ORM-selected row is used to
build the image. Reuse SeerRenderSessions and the existing renderer, with no
new global/context-local state or per-feature snapshot implementation.
Test search/custom/select paths and failure/cancellation cleanup, with a
different global dataset to catch accidental use of the unbound query source.

Verified: type service/rendering, publication and application-catalog tests
28 passed in 16.40s (2 existing ORM warnings). The 3-by-3 search/select/custom
and success/error/cancellation matrix uses an empty global dataset and a valid
bound dataset, asserts the render scope remains open after an await while its
SQL query context is closed, and checks scope cleanup on every outcome. Ruff,
targeted BasedPyright (0 errors/warnings), compileall and diff checks passed.
The service is 9 lines smaller; composition supplies the existing snapshot
factory rather than a feature-specific snapshot implementation. Alias/name
selection still produces only request IDs; render facts use the bound reader.
No TOML, dependencies, private extension or production deployment changed.

## Peak Preparation Boundary

Target: pool/vote/pet-rank queries receive a single context-managed bound
reader and three existing rendering callbacks from SeerRenderSessions. Hold
the same read snapshot across online vote/rank requests, progress callbacks,
and native rendering. Individual SQL sessions still end before network awaits.
Pet-rank's post-network pet lookup moves to peak_repository and uses the same
reader as its pre-network season lookup. Item rankings remain unchanged.
Tests must verify bound-reader use and cleanup on success, timeout, error and
cancellation. Online ranks remain live observations, not immutable release data.

Verified: peak service/vote/pool/pet-rank plus architecture/size checks 54 passed
in 10.27s (2 existing ORM relationship warnings). Twelve bound-reader cases
cover standard/expert pools, votes and pet ranks with successful completion,
progress failure and cancellation. Online callbacks assert the render lease
is active and the SQL context closed. The existing vote-render timeout also
asserts lease cleanup. A real SQLModel/SQLite repository test verifies requested
IDs only, absent IDs, empty input and detached values after engine disposal.
Ruff, targeted BasedPyright (0 errors/warnings), compileall and diff checks passed.
No new module/dependency/config/private-contract changes. The old three standalone
render callback constructor arguments and unbound pet-map helper were removed.
New-content, lucky-window and private-lineup binding remain outstanding.

## Lucky-Window Render Boundary

Target: treat the ordered offers and watch flags as immutable request inputs,
not new release facts. Open the shared render session before reading skin-image
resolution, then use its source and final-cache view throughout rendering.
Keep scope gating disabled for the lucky-window category until its full published
skin-body manifest is verified; do not enable L3 merely because binding exists.
The adapter needs only SeerDataReader and the shared HtmlTemplateRenderer callable,
not full search access or the concrete RenderCoordinator. Preserve four offers,
ordering, names and watch flags; unavailable art keeps the existing partial-image
and text fallback behaviour.

Verified: lucky-window service/rendering and publication regression 42 passed
in 19.75s (44 existing NoneBot deprecation warnings and 2 ORM warnings). New
adapter test checks four unchanged offers, ordering/names/watch flags, resolved
body-ID precedence, SQL scope closed before downloads and no cache creation for
an unavailable category. Existing request-key and missing-art recovery tests
remain green. Ruff, targeted BasedPyright (0 errors/warnings), compileall and
diff checks passed. Only composition and the adapter's minimal port types changed;
no new dependencies, TOML, category enablement or private extension change.

## New-Content Render Boundary

Target: each menu image uses the shared SeerRenderSessions reader, immutable
asset source and bound final cache. The preparation repository queries ORM
identifiers through SeerDataReader, not unbound full search/getter access.
Autocard and Flash mount readers need only that same query port. SQL sessions
close before image awaits; the publication lease lasts through final rendering.

Retained menu actions already carry entity IDs; they do not drift by numeric
position. Their index can nevertheless be older than a later rendering session.
Compare the complete index (including payloads and category state, not just its
config version) against the bound reader before reading image cache/details.
If it changed, preserve the existing text menu instead of rendering mixed facts.
This expected condition is not logged as a renderer exception. No engine lease
is held while waiting for human input.

Verified: new-content renderer/service/OneBot menu and real SQLite publication
tests 46 passed in 47.98s (2 existing ORM warnings). Same-version corrections
are detected, an old leased reader remains stable after replacement, a new
reader rejects the retained index, and text fallback keeps the same action IDs.
Ruff, targeted BasedPyright (0 errors/warnings), compileall and diff checks pass.
Additional Autocard, Flash mount, menu/presentation and architecture/size
regressions: 35 passed in 11.51s.

Still outstanding: multi-turn item-detail dispatch uses current domain services;
it has not acquired a common version policy with the retained index. Missing
detail fallback completeness and actual material/pixel acceptance also remain.
This batch does not claim the entire new-content conversation is version-bound,
enable another cache scope, or advance the 4/8 phase count.

## New-Content Detail Ownership

Target: one platform-neutral detail selector owns category dispatch. Reuse the
existing pet, mintmark, equipment and Autocard services; return their reply/text
or card entry without introducing a second lookup or delivery model. Embedded
skill, achievement and sanctuary descriptions continue using retained index
facts without reading current data. Composition shares the same service
instances with direct commands. OneBot only selects and delivers, with typed
detail/menu dependencies instead of five Any fields.

Verified: 62 detail/menu/catalog/architecture/size tests passed in 14.77s;
all twelve categories, selector arguments, returned partial reply identity,
missing/error messages, absent cards, data failure and cancellation are covered.
Ruff, targeted BasedPyright (0 errors/warnings), compileall and diff passed.
Production Python is 7 lines smaller overall; the OneBot adapter is 64 lines
smaller. No new file, dependency, TOML or compatibility facade was added.

This establishes the detail business boundary, not publication consistency:
the domain selectors still use their current readers. Next bind or explicitly
invalidate the selected publication at this service boundary, rather than
adding per-category guards in the OneBot plugin. Phase 4 remains unaccepted.

## Retained-Menu Detail Invalidation

Target policy: explicitly invalidate, rather than retain an engine while the
user considers a menu. Each detail selection validates membership in the
retained index and opens a mandatory selection scope. Composition leases the
current Seer engine, checks the complete index, and verifies that engine is
still current before and after the awaited domain selection. OneBot sends
nothing from a changed operation and ends the menu with an explicit reopen
instruction. There is no automatic retry or per-category exception policy.

SeerReadSnapshot.require_current compares actual engine identity through the
manager's locked accessor. Identical version strings, same-version rebuilds and
A-B-A reloads cannot masquerade as the same load generation. Closed snapshots
remain unusable. Error/cancellation still unwind the existing context manager;
the new check does not catch or convert cancellation into a successful result.

Verified: 72 menu/detail/publication/catalog/architecture/size tests passed in
21.78s (2 existing ORM warnings). Coverage includes before/after selection
invalidation, rejected foreign menu items, no result delivery on invalidation,
real SQLite identical-metadata reload and rollback, and closed-snapshot checks.
Targeted BasedPyright reports 0 errors/warnings; Ruff, compileall and diff pass.
No new file, dependency, TOML, background job or database schema was introduced.

This validates database generation consistency by discarding interrupted
selections. It is not a claim that every domain selector or remote card image
has immutable bound inputs. Render preparation completeness, private-lineup
binding and real published-material/pixel/platform acceptance remain Phase 4
work; the phase count remains 4/8.

## New-Content Completeness and Cache Identity

Target: prepared detail rows carry completeness into final-cache admission.
Absent rows, caught read failures, missing referenced titles/types/skin pets and
unavailable skill-effect data remain displayable but do not populate L3.
Legitimately empty effect lists and index-only descriptions remain complete.
Required images stay required even if their ID/URL could not be resolved;
missing type and attribute-skill icons also suppress final-cache writes.
A build-time Flash fallback is sufficient art, but cannot make absent detail
facts complete. The existing shared request normalizer hashes the full retained
index, including item names/payloads/change kinds, rather than its version only.

Verified: 114 new-content/service/menu/presentation/architecture/size regressions
passed in 7.73s. After adding a query-error recovery case, the 39 rendering
tests passed in 1.85s. Real FileRenderCache recovery tests cover absent detail
rows, query failure, type-icon failure and attribute-icon failure: partial image
first, fresh complete image after recovery, then a cache hit without rerendering.
Other tests distinguish empty and missing effects, index-only rows, unresolved
required IDs, Flash art with/without complete details, and same-version content
corrections with dictionary-order-invariant keys. Ruff, targeted BasedPyright
(0 errors/warnings), compileall and diff pass. No new module, dependency, TOML
or cache implementation; unused asset-helper fallback argument was removed.

These are cache-contract tests, not native pixel or live publication acceptance.
Private-lineup binding and the remaining real-material/platform gates still
prevent Phase 4 completion; total verified phases remain 4/8.

## Private-Lineup Publication Session

The extension now receives one PlayerLineupRenderSession factory instead of
independent global entry and rendering capabilities. Composition binds its
repository reader, material source and final cache through SeerRenderSessions.
The private service opens that context after the online packet is obtained and
keeps it through entry resolution and awaited rendering. Errors and cancellation
release the database lease; SQL sessions remain short-lived. No ORM rows cross
the extension boundary. Removed composition exports are no longer consumed.

The packet fetch contract now explicitly declares keyword-only timeout_seconds,
matching the private implementation. The public caller previously supplied it
positionally; the observation-time regression uses a strict keyword-only stub.

Verified: 35 publication/observation tests passed in 20.35s (2 existing ORM
warnings), 41 extension/cache/architecture/size tests in 4.10s, and all 29 private
tests against this public worktree in 1.96s. Real SQLite tests prove old lineup
names/resources remain bound after replacement, new sessions see new facts and
closed readers reject access. Parameterized material/final-cache tests cover
lineup heads across publication, late writes and rollback. Private tests cover
lease lifetime, resolution/render failure and cancellation. Both repositories
pass Ruff, compileall and diff; changed production contracts pass BasedPyright
with zero errors/warnings. No dependency, TOML, schema or compatibility adapter
was added. Both repositories must be released together for the new contract.

This does not validate real pixels or live deployment. Missing lineup facts and
the separate persistent player reply cache still require completeness review;
historical replies are not the same cache as bound final-render entries. Phase 4
remains incomplete and the total remains 4/8.

## Lineup Completeness Admission

Published lineup snapshots explicitly carry completeness. Missing pet rows no
longer fabricate a portrait resource from the pet ID; missing names, base
resources, type facts or unresolved skin portraits cannot be complete. The
private entry preserves this flag. Its renderer returns an image plus a
completeness result, verifying required head/type assets before writing L3.
Incomplete facts bypass early cache reads as well. A legitimate empty lineup
remains complete and cacheable.

The service still sends partial images with an explicit missing-data notice,
but only complete renders replace the persistent player reply. Existing complete
historical replies are left untouched. Exceptions while downloading materials
continue through the error path without writing either cache. Private renderer
source fingerprint changes invalidate earlier final-render entries; existing
persistent historical replies are not retroactively certified or migrated.

Verified: 34 public publication/extension/architecture/size tests passed in
13.70s (2 existing ORM warnings), and all 41 private tests in 1.50s. Tests cover
missing pet/skin snapshots, flag propagation, absent facts/resources/types/head
images/type images, recovery and subsequent cache hits, bypass of existing cache
for incomplete facts, asset exceptions, valid empty lineups, and persistence
admission with an existing historical reply. Both repositories pass Ruff and
compileall; changed production paths pass BasedPyright (0 errors/warnings).
No new module, dependency, schema or TOML field. Real pixel/material/deployment
acceptance remains outstanding; total verified phases stay at 4/8.

## Native Lineup Evidence and Release Gate

Native Windows htmlkit rendering was exercised with the retained real release
database and six real pet records (70, 3549, 4511, 4911, 3407, 4525), using
official asset-tree revision 1b53a16cfe32d36d921a04fbd8423116c5b1e2e1.
The release at `.tmp/skin-body-publication/seerapi-data.sqlite` is rejected by
the production loader because ironsbot_schema_contract_version is absent.
No version marker was injected and no production validator was relaxed.
The subsequent visual probe therefore used an explicitly offline, read-only
repository reader and a test-only asset pin with final caching disabled. This
is native material/presentation evidence, not release or deployment acceptance.

Artifacts: `.tmp/lineup-visual-acceptance/{complete,partial,empty}.png` and
`report.json`. The full image visibly contains six correct named portraits,
their type badges, level labels and a pool-limit marker. The initial native
outputs had heights 714, 723 and 710 respectively despite identical slot counts.
The inline-block grid now has zero line height and an explicit two-row height;
all three outputs are 490x704. Pixel color counts are 48197, 1115 and 323.
Full and partial images were visually inspected; no title/card overlap was seen.

An opt-in subprocess regression in the existing private rendering test module
uses native htmlkit on empty, one-card and twelve-card/long-name documents and
asserts stable dimensions and nonblank pixels. It isolates NoneBot/fontconfig
initialization from other tests and makes no network requests. With
IRONSBOT_NATIVE_RENDER_TESTS=1, all 42 private tests passed in 3.42s; Ruff passes.
The native probe required an explicit Windows fontconfig directory, so this is
not proof that default Windows deployment font discovery works. Linux fonts,
full renderer coverage, validated producer output and live deployment remain
separate gates. No runtime dependency or new production module was added.

## Real Producer-to-Consumer Build

Ran `uv run python -m scripts.build_seerapi_data_db` in the V5 producer checkout,
with SEERAPI_DATA_OUTPUT=tmp/v5-release-acceptance/seerapi-data.sqlite and
IRONSBOT_DATA_EFFECT_ICON_PNG_REQUIRE_CACHED=1. All source loaders used real
network inputs. The process completed normally and produced 55.71 MiB; SHA256:
6e3e20c364e67d1ee75e17e05b65abe3441e9c069fb5e564b6df40e253398cb5.
Quick-check is ok. The database declares schema contract 1 and asset contract 2,
and loads through the unchanged public DatabaseManager/SeerDatabase validator.

Important limitation: REQUIRE_CACHED alone does not disable conversion. A
cache-only invocation must also set PNG_RENDER_ENABLED=0. This run had no FFDec
jar; the Flash loader raised and the coordinator fell back to Unity for the
whole batch. Output metadata reports 0 Flash PNGs, 2108 Unity PNGs and 4 missing
icons. Thus this run verifies build/load mechanics, not original Flash icon
fidelity. The all-batch exception path discards otherwise reusable cached Flash
results when one uncached icon needs a missing renderer; review this path before
declaring source-preference acceptance complete.

Manifest revision:
3bcee795c7d4e7ffb10f32d11478212b984bd705785e0fddced6c1c67bfae13a.
Asset repository revision remains 1b53a16cfe32d36d921a04fbd8423116c5b1e2e1.
Only type_matchup is a proven complete scope. Missing manifest rows by kind:
equip 11, item 3577, mintmark 1, pet_body 13, pet_head 9, sign_buff 5,
soulmark_icon_png 4, title 11. These counts include optional resources, so they
are not all fatal. Required head IDs include 2690, 3011, 3083, 3687-3692;
mintmark 20447 and skin body 1400840 are also missing. The existing consumer
correctly leaves lineup/pet-info/new-content final caching disabled.

The same six-pet native probe was rerun through SeerRenderSessions using this
validated producer artifact, bound asset store and bound final cache. No offline
reader, injected metadata or test-only asset pin was used for that run. Complete,
partial and empty results remain 490x704 with the previous pixel color counts;
artifacts and report are in `.tmp/lineup-v5-release-acceptance/`. No final-cache
files were written under the unproven lineup scope. This closes the local real
producer/load/lineup-render loop, not all-renderer, Flash-fidelity, Linux or live
platform acceptance. No remote release, production file or main merge occurred.

## Per-Icon Flash Failure Isolation

Producer rendering now validates Java/FFDec only after a particular icon misses
its validated PNG cache and is eligible for rendering. The batch-wide preflight
and its duplicate cache scan were removed. Missing tools produce a failed record
for that icon before downloading its SWF; cached successes and confirmed absent
assets do not need tool checks. The existing source coordinator can therefore
request Unity only for missing icons instead of discarding all Flash results.

Combined-source resolution defers REQUIRE_CACHED validation until after fallback.
Required unresolved icons still raise an explicit error; standalone PNG cache
construction retains its strict precondition. Confirmed unavailable official
assets remain recorded as unavailable, not silently counted as successes. The
coordinator reuses Flash/Unity callback types instead of declaring weaker object
return aliases. No additional module or runtime dependency was introduced.

Verified: 88 builder/metadata tests passed in 14.93s. New cases use real PNG
cache files and renderer logic with controlled HTTP/Unity adapters: missing Java
or jar preserves the cached Flash icon, Unity receives only the uncached ID,
successful fallback meets the strict contract, unsuccessful fallback raises.
Existing SWF sprite/shape, alpha, cache invalidation, missing-resource and strict
cache tests remain covered. Their stubbed subprocess fixtures now provide valid
tool paths for the moved checks. Targeted BasedPyright reports 0 errors/warnings;
Ruff, compileall and diff pass. A full real-network producer rerun after this fix
has not yet been performed; previous artifact hashes describe the pre-fix run.

## Post-Fix Real Build and Native Cache Acceptance

The subsequent real-network build at producer commit 825ea05 completed normally
with REQUIRE_CACHED=1 and PNG_RENDER_ENABLED=0. Output:
`seerapi/tmp/v5-release-acceptance-fixed/seerapi-data.sqlite`, 58,413,056 bytes,
SHA256 `1ef66a0039326f1f2a8d2ca523af02e6e44da7134f3edff5ce15e0d385119845`.
Full integrity_check returned ok. The unchanged V5 DatabaseManager/SeerDatabase
accepted schema contract 1 and asset contract 2. Source publication and manifest
revisions match the previous run; binary hash equality is not assumed.

Metadata reports 2108 Unity PNGs, zero reusable Flash PNGs and four missing icons.
The run validates strict combined-source build/load, not preservation of a large
real Flash cache or visual equivalence to Flash. Those source-preference cases
remain supported by the focused regression tests, not this network experiment.
Only type_matchup remains a proven complete render scope.

Native rendering against this new validated artifact produced complete, partial
and empty lineup images at 490x704, with 48197/1115/323 RGB colors respectively.
Grass type-matchup produced an 848x3453 PNG (1,295,126 bytes); visual inspection
confirmed populated attack/defense icon grids, readable values and no overlapping
sections. Two consecutive adapter calls returned identical bytes with exactly
one native-render invocation. Generated evidence is in the ignored local directory
`.tmp/lineup-v5-fixed-acceptance/`, including report.json.

The first type-cache assertion failed because the probe set a 1 MiB total cache
budget, smaller than the resulting image. With an isolated 32 MiB probe budget
the check passes; production defaults to 500 MiB and was not changed. This is not
a production cache defect. This adapter-level probe does not prove zero SQL on
the full TypeQueryService cache-hit path. It uses explicit Windows fontconfig;
default font discovery, Linux/native deployment, full renderer coverage and live
platform acceptance remain open. The two existing ORM relationship warnings also
remain. No production data, main checkout or remote release was changed.

## Ordered Custom-Type Cache Identity

Target: final-image identity includes every presentation-affecting input.
Baseline: DIY type titles and primary/secondary icons retain user input order.
Inspection found that custom_type_matchup sorted IDs only in its cache key, so
grass+water and water+grass could share the first rendered image despite different
titles and icon order. Keep IDs ordered in the existing key and use a v2 prefix
to reject old unordered entries. No additional cache, module, dependency or TOML
field is introduced; obsolete entries expire through normal cache cleanup.

The regression uses the real FileRenderCache and renderer adapter with controlled
image/native ports. It checks both an empty cache and a seeded legacy entry,
opposite input orders, and separator variants sharing the same ordered result.
Exactly two renders and two sets of asset requests are required across four
requests. The seeded-cache case failed before the change. Type query/render tests
pass (18 cases), including session closure before awaiting, cancellation, normal
type exclusion and menu behavior. This is cache-identity acceptance only:
TypeQueryService still resolves names and loads the matchup dataset before the
adapter cache check. Zero-SQL hits remain open rather than being claimed here.

## Type Query Cache Ownership (Supersedes Adapter-Level Cache)

Target: TypeQueryService owns the single final-image cache entry before any
repository query. Its TypeRenderSession contains a publication-bound reader,
renderer and the existing shared RenderCache. Name resolution now delegates to
the existing TypeCombinationDataGetter inside that same reader snapshot and
returns detached values. There is no global-data lookup before opening the
snapshot and no SQL session held across the native-render await.

The adapter now only loads assets and renders prepared facts. Its old cache
lookup/write and the calculator's unused cache_key field were removed. Request
identity distinguishes selection IDs from exact search text, preserving order
without guessing normalization rules for the name resolver. Different spellings
may occupy separate entries; they no longer share the old calculated key. Only
successful images are stored, not menus, messages or exceptions. Existing
publication completeness and version gates remain authoritative. Query and
calculator source paths are included in the shared rendering fingerprint.

Service tests cover zero reader calls on hits for search/select/custom requests,
version changes and rollback, disabled completeness scopes, failed-render retry,
opposite DIY input order, and fingerprint inputs. Relevant query/render/key tests
pass (27); database snapshot tests previously passed together with this migration
(39 including the then-current query cases). Architecture/bootstrap tests pass
(19). The prior adapter-cache tests were moved to the service boundary rather
than retaining two caching implementations.

Real post-fix producer SQLite plus SeerRenderSessions and Windows native rendering
was exercised with search("1"): cold query 6 SQL statements, repeated query 0,
one native render, identical 848x3453 image bytes. Search("草") produced a
non-image response through the existing broad resolver, so the image probe uses
an unambiguous ID; no search semantics were relaxed to make acceptance pass.
Evidence remains in `.tmp/lineup-v5-fixed-acceptance/report.json`. This verifies
the local type query path, not live platform deployment or completion of Phase 4.
