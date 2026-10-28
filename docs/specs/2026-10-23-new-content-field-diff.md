# Weekly Content Field Differences

SeerAPI publishes `field_changes_version = 1` and a complete `field_changes`
array inside each modified item's existing JSON payload. Each row has a string
`path` array, boolean `old_exists`/`new_exists`, and the corresponding `old`/`new`
JSON values when present. Missing fields are distinct from null, zero, empty
strings and empty containers. `name` is a top-level path; semantic fields start
with `payload`. ID-indexed lists use `id=<value>` path components.

Differences come from the release's trusted fixed baseline. Display metadata is
excluded from semantic fingerprints. Semantic schema 8 canonicalizes ID-indexed
lists, and old source snapshots are rehashed from their raw baseline database.
Without a trustworthy baseline, historical differences are not reconstructed
from summaries or current values. Existing summaries remain compact; the field
array contains all changes without the summary's length/count limits.

IronsBot presents only changed fields in equal-width old/new columns. Line
alignment precedes character-level comparison. Removed/replaced fragments are
red with a minus marker; inserted/replaced fragments are green with a plus.
Unchanged fragments retain the normal color. Template escaping is mandatory
even when the enclosing renderer does not enable global autoescape.

Missing or incomplete historical fields produce an explicit notice, not an
inferred old value. Peak-pool matrices are unchanged. Current effects are hidden
only when their complete text is already present in a valid difference row.
Ordinary detail queries do not use this presentation. Weekly render keys use
the `new_content_diff_v1` namespace to exclude old cached images.

The weekly list uses image + vertically stacked content instead of a fixed
330-pixel effect sidebar. Empty descriptions do not reserve a column or height.
Card skills, chip effects and attribute grids continue to use their real data.

Tests: `test_new_content_diff.py`, existing weekly renderer/presentation suites,
and SeerAPI `test_new_content_field_changes.py`. Fictional screenshot fixtures
cover description-less cards, multiline chip effects, skill changes and missing
history. No configuration change, data publication or deployment is required
to test the implementation; complete live differences require regenerated
SeerAPI data with the new payload fields.
