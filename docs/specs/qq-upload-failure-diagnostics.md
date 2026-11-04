# QQ Upload Failure Diagnostics

Status: `in-progress`

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
| Reuse investigation | Boundary diagnostics, concurrency and cancellation tests | planned |

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
the exact cause remains unconfirmed. No tests or live probes completed yet.

2026-11-04: HTTP explanation, phase propagation and receipt JSON round trip:
30 targeted tests passed in the normal test environment. An initial sandbox
test run stalled and was interrupted; it is not counted as passing evidence.

2026-11-04: shared receipt reporting and existing upload/batch regression:
153 tests passed. Raw unstructured transport errors remain excluded from notices;
only HTTP-boundary diagnostics expose a sanitized platform explanation.
