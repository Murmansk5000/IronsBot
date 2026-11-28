# Pet effect icon stacks

Pet information shows one list of published effects, ordered by numeric status
ID, with unidentified effects last. It shows explicit soulmark and named skill
sources only; provenance and parent links remain available in the data.

SeerAPI physical schema and effect association contracts both move to version 3.
The new schema requires `pet_special_effect_icon`, keyed
by pet, effect, asset kind and asset key, with optional numeric status and
variant IDs. Its list is authoritative, including an empty list. The producer
and consumer must be released together: there are no single-icon columns or
fallback readers.

Display-only artwork candidates live in `pet_special_effect_icon_candidate`.
The same list draws their available images in status-ID order, without showing
candidate labels, IDs, or configuration text. Candidate IDs do not affect
card order, and missing artwork never replaces confirmed art.

The renderer requests each published asset once, shows the successful images
in numeric order beside the effect, and collapses identical image bytes only
within that effect. Existing cache fingerprinting and asset-failure handling
apply. No name-based or minimum-ID association is introduced.
