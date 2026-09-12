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
