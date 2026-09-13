# Portable Pet Configuration Query

## Status

Implemented on `codex/multiplatform-architecture-v5`.

## Goal

Expose configured pet artwork through the shared command router without
duplicating OneBot query menus or image delivery code.

## Contract

- `pet_config.query` remains the single command-catalog owner.
- The existing `PetConfigQueryService` owns pet resolution and image loading.
- The existing portable query session owns ambiguous-result selection.
- The operation returns the same platform-neutral text and binary-image parts
  used by other portable Seer queries.
- Configured fixed-image commands remain reserved, using the same command set
  as the OneBot parser.

The operation is installed only when the command exists in the loaded catalog,
which already reflects `pet_config.enabled` and feature visibility.

## Acceptance

- A unique pet result returns its configured image.
- Ambiguous names open the shared numeric selection menu.
- Missing pets and missing images preserve the service result.
- Reserved fixed-image commands are not claimed.
- Existing OneBot behavior remains unchanged.
