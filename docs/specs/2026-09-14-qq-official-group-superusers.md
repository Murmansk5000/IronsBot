# QQ Official Group Superusers

## Status

Implemented on `codex/multiplatform-architecture-v5`.

## Goal

Authorize trusted QQ Official group members without pretending that a group
`member_openid` is the same identity or delivery target as a C2C
`user_openid`.

## Contract

- `bot.qq_official.accounts.<alias>.superusers` contains C2C
  `user_openid` values and remains eligible for private administrative notices.
- `bot.qq_official.accounts.<alias>.group_superusers` maps a group alias or raw
  group OpenID to the `member_openid` values observed in that group.
- Group superusers compile to scoped member `ActorRef` values containing
  platform, owning AppID, group OpenID and member OpenID.
- Authorization uses exact typed identity. A member configured for one group
  or one AppID is not a superuser in another group or account.
- Group member identities are never converted into private conversations and
  are excluded from private schedules and administrator notices.

This mirrors Tencent's separate `allowFrom` and `groupAllowFrom` concepts. The
application does not infer a relationship between the two OpenID forms.

## Acceptance

- A configured group member passes superuser command access in only its group.
- The same member OpenID in another group or AppID does not pass.
- C2C superusers continue to receive private notices.
- Group superusers do not become private push recipients.
- Existing OneBot superuser behavior is unchanged.
- No state migration, dependency, asset or image-layer change is required.
