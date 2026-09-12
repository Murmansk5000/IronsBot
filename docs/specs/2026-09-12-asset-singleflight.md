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
