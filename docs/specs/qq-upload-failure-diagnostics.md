# QQ Upload Failure Diagnostics

Status: `verified-with-limitations`

Contract: `baseline`

Owner: QQ HTTP adapter, shared command delivery and existing media reuse batch.

## Problem And Goal

On 2026-11-02 two image uploads reached COS successfully but their part-finish
requests returned HTTP 404/code 11001. The response explanation was discarded.
Unconfirmed command receipts also became fabricated ConnectionError exceptions.
Preserve safe structured diagnostics and identify reuse boundaries without
assuming that concurrency caused the platform rejection.

## Design And Boundaries

- HTTP adapter sanitizes explanations and exposes only method/route templates.
- SendResult carries optional phase, HTTP status, request route and original type;
  existing JSON receipt storage keeps these optional fields without a DB migration.
- Shared error reporting handles failed receipts directly; real exceptions retain
  stack locations. No synthetic ConnectionError or invented exception location.
- Upload logs identify batch, format key, source target and hashed upload session.
  Reuse remains scoped to account, batch, chat kind and compatible image format.
- Never broaden retries for 11001, resend historical messages, change permissions,
  deploy, or edit production configuration. Preserve unrelated working changes.

## Delivery Slices

| Slice | Acceptance | Status |
| --- | --- | --- |
| Safe diagnostics | Response redaction, phase and durable receipt round trips | verified |
| Receipt reporting | No fabricated exception, concise contextual notices | verified |
| Reuse investigation | Boundary diagnostics, concurrency and cancellation tests | verified; live access unavailable |

## Validation

Targeted and full pytest, Ruff, BasedPyright, compileall and diff checks. Reserved
working files are excluded. Authorized live probes use only development AppID
1904152026 and configured accessible test groups: at most eight logical uploads,
two concurrent, no chat messages. Missing access or unavailable evidence is
reported, not replaced with production account testing.

Each verified slice is separately committed and archived as a local-source
snapshot. No development branch publication or historical rewrite is authorized.

## Evidence

2026-11-04: production logs confirm COS HTTP 200 followed by confirmation HTTP
404/code 11001. The historical explanation and upload IDs were not retained;
the exact cause remains unconfirmed. This initial observation preceded testing.

2026-11-04: HTTP explanation, phase propagation and receipt JSON round trip:
30 targeted tests passed in the normal test environment. An initial sandbox
test run stalled and was interrupted; it is not counted as passing evidence.

2026-11-04: shared receipt reporting and existing upload/batch regression:
153 tests passed. Raw unstructured transport errors remain excluded from notices;
only HTTP-boundary diagnostics expose a sanitized platform explanation.

2026-11-04: upload boundary tests: 48 passed, including persistent-outbox
integration and case-insensitive PNG reuse, failure cleanup and cancellation.
Production read-only discovery found no trusted mapping for development AppID
1904152026 in either configured test group (robot, huohuo_test). No live upload
or chat message was issued. Concurrent duplicate-upload failure was not
reproduced; no speculative serialization or retry expansion was introduced.
Batch/format/session/origin diagnostics now allow a subsequent failure to be
correlated. Exact historical 11001 cause remains unknown.

## Final Verification

2026-11-04: isolated committed source
`f82f14735d38d40970955032e33974759b552091`: **6707 passed, 9 skipped**
in 362.09 seconds. Ruff, BasedPyright (zero diagnostics), compileall, static
repository checks and git diff --check passed. Only committed copies in E-drive
isolation were used for the full suite; the reserved working files were not
edited, staged, formatted or restored.

The first full run had 6706 passes, nine skips and one privacy-fixture failure:
a log-derived identifier accidentally appeared in a newly added test. It was
replaced with a runtime-generated synthetic value; no runtime behavior changed.
Initial failure evidence is retained beside the final results at
`E:/IronsBot-history-validation/upload-diagnostics-20261104/`.

Delivery limitations: zero live uploads (no trusted development test-group
mapping), no reproduction of the platform 11001 cause, no speculative upload
serialization, no retry expansion, no historical resend, no development-branch
publication and no production deployment/configuration change.
