# Compact Weekly Content Revisions

Status: `verified`

Contract: `baseline`

Owner: weekly-content presentation service and SeerData render adapter

Related architecture: [ARCHITECTURE.md](../../ARCHITECTURE.md)

## Problem And Goal

The previous side-by-side diff repeated complete descriptions, fragmented numeric
changes such as 50 to 55, and allowed long text and images to exceed native layout
bounds. Root previews also expanded categories outside the configured selection.

Use compact inline revisions: red struck-through old text, a presentation-only
arrow for replacements, and green underlined new text. Compare numbers as complete
tokens. Replace BuffParam, buff_param and buffParam as complete old/new strings,
including all groups and separators. Preserve unchanged prose and line endings.

## Ownership And Compatibility

- Reuse published field_changes and the existing weekly snapshot/menu contracts.
- The presenter owns diff fragments; the adapter prepares and fits image bytes;
  the template owns revision styling, arrows and layout only.
- Retire the two-column diff model and per-position parameter comparison.
- Keep command ownership, permissions, category order, release schema and cycle
  baselines unchanged. No persistence or configuration migration is needed.
- The shared skill macro's optional text renderer defaults to existing behavior;
  bounded inline runs are enabled only by the weekly-content template.

## Display Contract

- Only configured ordinary categories expand, with at most five short previews.
  Category totals and focused submenus retain every item. Existing skill-preview
  eligibility remains unchanged; pool transitions remain separate full matrices.
- Previews show thumbnail, name and change label without full descriptions/diffs.
- Detail headers show image/name/basic information; remaining descriptions and
  compact field revisions use the full body width without repeated current text.
- Use one image at a maximum width of 1080 pixels and natural height. Fit images
  proportionally before native layout and wrap long text without clipping or
  shrinking fonts. Preserve missing-history and required-image failure notices.
- Invalidate previously rendered menus with the revision-v2 cache namespace.

## Verification

- [x] Complete numbers, signs/decimals, multiline prose and source reconstruction.
- [x] Complete parameter replacements, all three aliases, empty values, added or
  removed groups, long strings and exactly one rendered replacement arrow.
- [x] Configured previews show five of nine items; focused menus retain all nine.
- [x] Native pixel margins and all 40 dense-pool avatars remain inside the image.
- [x] Image aspect ratios, source escaping, missing history and retained upgrades.
- [x] Chromium element bounds for real magician data, previews and stress fixtures.
- [x] Final presentation regression suite: 178 passed; Ruff and diff checks passed.

The initial layout stage also passed the full suite (6727 passed, 9 skipped).
That full run preceded the final whole-number/whole-parameter refinements; their
verification is the final targeted suite above, not a new full-suite claim.

## Delivery And Rollback

The user authorized commit and normal push on 2026-11-06. Production deployment,
container changes, database rebuilding and production reply validation are not
part of this delivery. Actions publication does not imply deployment.

Rollback is a normal revert of this presentation commit; no data migration or
destructive history operation is required. Preserve existing unrelated commits,
working files and cumulative original-history snapshots.
