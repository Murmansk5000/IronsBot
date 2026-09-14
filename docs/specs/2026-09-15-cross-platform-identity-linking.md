# Explicit Cross-Platform Identity Linking

Date: 2026-09-15

Status: completed

Owner: core platform identity, identity-link service, QQ state storage, and
portable/OneBot command adapters.

## Contract

- A OneBot actor with a decimal QQ ID explicitly requests a challenge for one
  enabled QQ Official account alias.
- The challenge is short-lived, single-use, and stored only as a SHA-256 hash.
- A QQ Official actor confirms the challenge under the AppID that received the
  event. The persisted identity includes actor kind, OpenID, and group scope.
- C2C user OpenIDs and group member OpenIDs remain distinct identities. One QQ
  may link both explicitly; neither is inferred from the other.
- An official identity cannot be reassigned to another QQ until its existing
  link is revoked.
- Either side can inspect or revoke its links. User-facing status masks QQ IDs
  and OpenIDs.

## Commands

- OneBot: `关联官方账号 [账号别名]`
- QQ Official: `关联账号 <令牌>`
- Both: `账号关联`, `解除账号关联`

The account alias is the key under `[bot.qq_official.accounts.<alias>]`; no new
TOML or environment variable is introduced. Without a documented trusted
cross-application deep-link contract, the implementation does not pretend a
button can transfer identity proof between two clients.

## Security

Nickname, avatar, message time, message history, and `union_openid` are not
identity proofs and are never used to create a link. Challenge issuance,
successful linking, and revocation are audited without recording the raw token.

## Acceptance

- Challenge expiry, AppID scope, one-time consumption, conflict handling, and
  concurrent consumption have automated storage/service coverage.
- OneBot and QQ Official command contracts expose only their platform-owned
  inputs while status and revocation remain shared.
- Offline platform-state migration preserves existing explicit links and their
  migration namespace.
- Full repository tests and static checks pass before this spec becomes
  `completed`.

## Verification

- Identity, command catalog, portable/OneBot routing, QQ Official, state
  migration, and platform migration set: `285 passed`.
- Application composition, lifecycle, plugin registry/import hygiene, and
  configuration set: `117 passed`.
- Ruff, BasedPyright, compileall, repository static checks, and diff checks
  passed.
