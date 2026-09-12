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
