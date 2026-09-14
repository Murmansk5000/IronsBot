# Portable Lucky Skin Window

Status: `implemented`

Contract: `target`

Owner: platform reference configuration, lucky-window domain service, portable
command adapter, and proactive outbound delivery.

## Goal

Run all six lucky-window commands through the shared portable command router without
interpreting QQ Official OpenIDs as numeric QQ IDs or copying the OneBot business
logic.

## Identity Contract

- `seer.lucky_skin_window.accounts[].user` resolves through
  `PlatformReferenceResolver.user_actor_ref()`.
- OneBot references remain aliases or numeric QQ IDs.
- QQ Official references must name an alias in the owning account's `user_aliases`;
  the resulting `ActorRef` retains both OpenID and AppID.
- Bindings, watch preferences, feature policy, and proactive delivery use that same
  `ActorRef` identity.
- Official accounts configured for the daily notice require
  `proactive_messages = true`.

## Command Contract

The portable router executes the existing catalog IDs for querying the window and
listing, adding, removing, clearing, or resetting watched skins. The adapter only
owns login confirmation and numeric selection presentation. Account validation,
cache lookup, headless query, skin resolution, watch persistence, rendering, and
detail selection continue to use the existing domain services.

An uncached query accepts only confirmation or cancellation responses. Unrelated
chat text is not claimed by the pending confirmation. The headless query starts only
after the confirmation acknowledgement is delivered, using the shared
`progress_operation_reply()` gate.

## Footprint

This increment adds no dependency, database, binary asset, image layer, or duplicate
cache. The existing platform-scoped binding and watch tables remain authoritative.
The complete example command catalog has 75 of 75 commands backed by portable
operations.

## External Gate

Portable coverage does not prove that a QQ application has proactive-message quota
or receives a particular event intent. A real AppID smoke test remains required to
close the final platform phase.
