# Account-Scoped Platform Target Aliases

## Status

Implemented on `codex/multiplatform-architecture-v5`.

## Goal

Allow one global business configuration to address OneBot and QQ Official
recipients without losing the QQ Official AppID that owns each OpenID.

## Contract

- OneBot aliases remain in `features.group_aliases` and
  `features.user_aliases`.
- QQ Official aliases live under each enabled account's `group_aliases` and
  `user_aliases` tables.
- A configured alias resolves to one `ConversationRef` or `ActorRef` carrying
  `platform`, target ID and, for QQ Official, the owning AppID.
- Group aliases and user aliases are independently globally unique across
  OneBot and all enabled QQ Official accounts.
- A raw QQ Official OpenID is not accepted by global target maps because it
  does not identify the owning bot account.
- Account-local feature policies and superuser lists may use their account's
  aliases or raw OpenIDs.

This follows Tencent's multi-account boundary: every bot account owns an
independent connection and token cache, and an OpenID received by one bot must
not be used by another bot.

## Bilibili Slice

- Bilibili group and private targets use the shared platform resolver instead
  of a OneBot-only compiler.
- `动态`, `B站账号` and group/private `B站推送模式` operations are available
  through the portable command router when catalog access permits them.
- Runtime push preferences and subscriptions continue to use typed
  account-scoped conversation keys.
- Existing OneBot configuration remains valid without conversion.

## Acceptance

- OneBot numeric IDs and aliases resolve unchanged.
- QQ Official group/user aliases retain their owning AppID.
- Cross-platform and cross-account alias collisions fail during settings
  validation.
- Bilibili configured targets can contain both platforms without adapter
  branching in the business service.
- Official private-history permission checks preserve `account_id`.
- No SDK, image asset, SQLite database or runtime dependency is added.

Real proactive-message permission and rate-limit behavior remain a live QQ
platform acceptance gate.
