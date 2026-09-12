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
