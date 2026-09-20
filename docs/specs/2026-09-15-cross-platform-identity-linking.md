# Cross-Platform Identity Linking

Date: 2026-09-15

Status: completed

Owner: core platform identity, identity-link service, QQ state storage, and
portable/OneBot command adapters.

## Authoritative Contract

An exact link may come from one of three sources. They converge on the same
AppID-scoped identity repository and permission lookup; handlers do not maintain
separate identities for each source.

1. A deployment-owned `[identities]` alias explicitly names the OneBot and QQ
   Official endpoints of one trusted principal.
2. A user completes the explicit challenge flow below.
3. Silent group observation matches an official `member_openid` to the numeric
   sender of the source message referenced by the trusted official bot's reply.
   The official bot and NapCat must share a configured logical group, and two
   independent, unique, consistent observations are required.

Before member correlation, any normal command reply may establish the logical
group itself. The official inbound event supplies `(AppID, group_openid)` and
NapCat supplies the numeric group containing the trusted bot's exact reply.
Only numeric groups already declared by `[identities.groups].qq` are candidates.
A unique match is persisted in a separate group-link table; either-side conflicts
fail closed and are never overwritten. The learned group immediately inherits
the numeric group's feature policy and is restored before message handling after
a restart. `官方身份` remains an optional diagnostic command, not a provisioning
step.

Silent observation fails closed on ambiguity, expiry, untrusted bot origin, or
an existing conflicting link. It never overwrites a link. C2C `user_openid`
does not participate because NapCat cannot authenticate its private-message
sender through a group source reference.

## Explicit Challenge Contract

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

Nickname, avatar, `union_openid`, fuzzy content similarity, bare timing, and
unreferenced message history are not identity proofs and are never used to
create a link. The silent observer uses only a trusted official reply's exact
source-message reference, normalized content as a consistency check, the same
logical group, and a bounded time window. Challenge issuance, successful
linking, observation and revocation are audited without recording raw tokens or
platform identifiers. Group links and member links are separate records because
a conversation identity is not an actor identity.

## Acceptance

- Challenge expiry, AppID scope, one-time consumption, conflict handling, and
  concurrent consumption have automated storage/service coverage.
- OneBot and QQ Official command contracts expose only their platform-owned
  inputs while status and revocation remain shared.
- Offline platform-state migration preserves existing explicit links and their
  migration namespace.
- Trusted observation requires two matches and covers ambiguity, conflict,
  expiry and untrusted-source rejection.
- Group discovery accepts a normal command reply, requires a unique trusted-bot
  match in a configured numeric group, persists across restarts, projects the
  existing group feature policy, and rejects either-side conflicts.
- Full repository tests and static checks pass before this spec becomes
  `completed`.

## Verification

- The original challenge slice passed its focused identity, command, routing,
  migration and lifecycle suites before this spec was marked completed.
- The later trusted-observation slice is covered by identity-observation,
  platform-identity and ingress-policy tests. Production Unraid evidence on
  2026-09-19 confirmed that QQ Official replies expose source references to
  NapCat without sending verification messages.
