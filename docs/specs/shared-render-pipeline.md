# Shared Render Pipeline And Reply Fallback

Status: `completed`

Contract: `target`

Owner: shared Seer render coordinator; shared command reply delivery

## Problem

The existing coordinator bounds native rendering only after semaphore admission.
Asset preparation and queue admission can outlive that deadline. Weekly-content
commands await image preparation before offering any menu. Production on
2026-11-14 recognized the 16:50:31 request and logged asset failures without a
corresponding weekly-menu receipt. Those logs do not prove its exact stuck stage.

## Design

- One coordinator owns dated/version-bound render requests, structured complete,
  degraded and failed results, preparation/queue/native deadlines and diagnostics.
- Existing presentation models and templates remain domain-owned. Validated
  source images remain cached; missing presentation assets become placeholders.
- Complete image writes are staged until successful completion; failed/degraded
  operations never publish final image entries. Cancellation propagates.
- Public commands convert typed render failures into reliable text. Weekly menus
  retain the same choices, permission checks and navigation without an image.
- Original-image sends, Bilibili composition and GIF processing are excluded.
- Private extension HTML ports enter the same coordinator, not a second renderer.

## Delivery Slices

| Slice | Acceptance | Status |
| --- | --- | --- |
| Shared lifecycle | bounded preparation/queue/render, structured failures | verified |
| Entry migration | built-in templates and extension HTML port | verified |
| Weekly reply | same-model text menu after image failure | verified |
| Validation | targeted/full checks, architecture inventory | verified |

## Boundaries

No production changes, chat test sends, new TOML, database migration, player-cache
policy changes, historical folding or public-main publication. Preserve reserved
working files. Independently verified commits may be appended to clean original
history only. Existing archive script exclusions remain mandatory.

## Interfaces And Entry Inventory

`RenderRequest` identifies the template, bound publication, cache identity and
reliable text alternative. `RenderResult` reports complete/degraded/failed,
image bytes, failed stage and exception type. `RenderCoordinator.execute()`
returns that result; `image()` preserves existing bytes ports using the typed
`RenderFailureError`. The shared command reporter converts it into failed text
delivery. `HtmlTemplateRenderer` accepts awaitable callables, including the
typed coordinator wrappers, rather than requiring a concrete coroutine class.

| Entry | Common route | Text fallback |
| --- | --- | --- |
| Pet info | bound session -> coordinator | verified pet ID |
| Attribute matchup | bound session -> coordinator | target attribute |
| Competitive/expert/master pools | bound session -> coordinator | title, pool and pet list |
| Pool votes | bound session -> coordinator | observation time, names, votes |
| Pet statistics | bound session -> coordinator | title, IDs, matches and wins |
| Weekly root/category | bound session -> coordinator | same menu choices and navigation |
| Lucky window | bound session -> coordinator | verified offer names |
| Private main/details HTML | public extension port -> coordinator | existing dated query fallback or explicit failure |

Equipment/mintmark/card artwork commands send existing images, not dynamically
generated HTML; their direct-source error behavior is intentionally retained.
Weekly card/equipment entries are part of the common weekly template. Bilibili
and GIF processing are not HTML templates and remain outside this change.

Source and final caches are different: `RenderAssetSession` validates/substitutes
presentation assets and stages version-bound final-cache writes. The coordinator
publishes those writes only on complete success. Adapters may define stable
category/content identities, but cannot override this eligibility policy.

## Confirmed Defect And Production Evidence Limit

The old coordinator's semaphore acquisition and all asset preparation occurred
outside its native-only timeout. Weekly commands offered no menu until those
steps completed. Isolated blocked-preparation and blocked-queue tests reproduce
that unbounded wait; the replacement returns a typed failure and offers a
selectable text menu. Existing production logs lack a per-render stage trace,
so they cannot distinguish which step stalled the 2026-11-14 request. Do not
claim that a specific production asset, the native engine or upload was proven
to be its sole cause. Start/finish logs now identify stage, outcome and duration
without message contents, credentials or target identifiers.

## Acceptance

- Success, partial/multiple asset failure, invalid image, optional assets.
- Preparation/queue/native timeout, template exception, cancellation and recovery.
- No degraded/failed final cache writes, no duplicate response/settlement.
- Weekly root/category text menu, navigation and permissions on both platforms.
- Full pytest, Ruff, BasedPyright, compileall, architecture and whitespace checks.

## Evidence

| Date | Verification actually run | Result |
| --- | --- | --- |
| 2026-11-14 | Exact staged core tree: targeted pytest, Ruff, BasedPyright | 266 passed; lint/types clean |
| 2026-11-14 | Final combined targeted pytest | 330 passed |
| 2026-11-14 | Native binding, resource, packaging and pool compatibility | 73 passed, 2 skipped |
| 2026-11-14 | Final exact combined snapshot: complete pytest | 7039 passed, 11 skipped |
| 2026-11-14 | Final Ruff, BasedPyright, compileall, repository static checks, diff check | all passed; 0 type errors |
| 2026-11-14 | Private main / details with the shared public checkout | 56 / 94 passed, 1 skip each |

One earlier complete run failed the unchanged Bilibili immediate-image-retry
assertion (3 sends rather than 4). Its isolated rerun passed; the final full run
also passed. This task does not claim to have diagnosed or fixed that intermittent
assertion, and does not modify Bilibili code or tests. Prior failed-check logs
remain in the diagnostics attempts directory rather than being discarded.

Native callback errors previously only logged and could still return image
bytes. They now raise `NativeResourceError`, entering the same typed fallback
instead of caching a nominally successful incomplete image. Normal prepared
asset failures still use local placeholders, not this engine-failure branch.

Raw evidence is retained under
`E:/IronsBot-history-validation/shared-render-pipeline-20261114` (final logs,
core-only checks, target logs, private compatibility and archive records).
Tests use isolated committed reserved modules, never their protected working
copies. No production root cause is claimed beyond the documented logs and
reproduced lifecycle gaps. No production data, config, network, container or
development branch publication was changed.
